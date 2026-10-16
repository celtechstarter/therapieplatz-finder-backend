"""Seiten von therapie.de ueber Firecrawl holen und auslesen.

- such_url / profil_links_aus_html / trefferzahl_aus_html: Suchergebnisse
- firecrawl_holer: holt eine Seite ueber die Firecrawl-API (mit Pause,
  Wiederholung bei 429 und sofortigem Stopp, wenn therapie.de blockt)
- ProfilLeser: liest das gelieferte HTML in einem lokalen Browser ohne
  Netzwerk mit scraper.lies_profil() aus
"""
import re
import time
from urllib.parse import quote

import requests
from umkreis_plan import SUCHBEGRIFF

BASE_URL = "https://www.therapie.de"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
STANDARD_PAUSE = 6.5         # Sekunden zwischen Abrufen (Free-Plan: 10/Min.)

# therapie.de-Suchfilter (Werte aus dem Suchformular, geprueft 30.9.2026):
#   abrechnungsverfahren=7 -> "Kassenleistung oder Kostenerstattung"
#   therapieangebot=1      -> "Einzeltherapie: Erwachsene"
SUCH_FILTER = "&abrechnungsverfahren=7&therapieangebot=1"


class FirecrawlFehler(Exception):
    pass


class CreditsLeer(FirecrawlFehler):
    """Firecrawl meldet 402: Monats-Credits aufgebraucht."""


class ZielBlockiert(FirecrawlFehler):
    """therapie.de selbst antwortet mit 403/429 -> sofort aufhoeren."""



def such_url(ort, seite=1):
    url = f"{BASE_URL}/therapeutensuche/ergebnisse/?ort={quote(SUCHBEGRIFF.get(ort, ort))}{SUCH_FILTER}"
    return url if seite <= 1 else f"{url}&page={seite}"


_PROFIL_LINK = re.compile(r'href="((?:https://www\.therapie\.de)?/profil/[^"/?#]+/)"')
_TREFFER = re.compile(r"<title>\s*(\d+)\s+Therapeuten", re.I)


def profil_links_aus_html(html):
    """Eindeutige, absolute Profil-URLs in Reihenfolge des Auftretens."""
    links = []
    for m in _PROFIL_LINK.finditer(html or ""):
        url = m.group(1)
        if url.startswith("/"):
            url = BASE_URL + url
        if "/info/" in url:
            continue
        links.append(url)
    return list(dict.fromkeys(links))


def trefferzahl_aus_html(html):
    m = _TREFFER.search(html or "")
    return int(m.group(1)) if m else None


def firecrawl_holer(api_key, pause=STANDARD_PAUSE, http=requests, schlafen=time.sleep):
    """Liefert eine Funktion url -> (html, credits). Wartet vor jedem Abruf
    `pause` Sekunden (Free-Plan-Ratenlimit, und schont therapie.de)."""
    if not api_key:
        raise FirecrawlFehler("FIRECRAWL_API_KEY fehlt in der .env (siehe .env.example).")

    def holen(url):
        for versuch in range(3):
            schlafen(pause)
            antwort = http.post(
                FIRECRAWL_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"url": url, "formats": ["rawHtml"], "onlyMainContent": False},
                timeout=90,
            )
            if antwort.status_code == 402:
                raise CreditsLeer("Firecrawl: Credits fuer diesen Monat aufgebraucht (402).")
            if antwort.status_code == 429:
                if versuch < 2:
                    schlafen(60)
                    continue
                raise FirecrawlFehler("Firecrawl: Ratenlimit (429) auch nach Wartezeit.")
            if antwort.status_code >= 400:
                raise FirecrawlFehler(f"Firecrawl: HTTP {antwort.status_code}")
            daten = (antwort.json() or {}).get("data") or {}
            meta = daten.get("metadata") or {}
            ziel_status = meta.get("statusCode")
            if ziel_status in (403, 429):
                raise ZielBlockiert(f"therapie.de antwortet mit {ziel_status}")
            credits = int(meta.get("creditsUsed") or 1)
            return daten.get("rawHtml") or "", credits
        raise FirecrawlFehler("Firecrawl: kein Ergebnis")  # pragma: no cover

    return holen


class ProfilLeser:
    """Laedt Firecrawl-HTML in einen lokalen Chromium und liest es mit
    scraper.lies_profil() aus. Jeder Netzwerk-Request der Seite wird
    abgebrochen (keine Bilder/Skripte von therapie.de, kein Tracking)."""

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        kontext = await self._browser.new_context(locale="de-DE", java_script_enabled=False)
        await kontext.route("**/*", lambda route: route.abort())
        self._page = await kontext.new_page()
        return self

    async def __aexit__(self, *exc):
        try:
            await self._browser.close()
        finally:
            await self._pw.stop()

    async def lesen(self, url, html):
        import scraper
        if "therapist-details" not in (html or ""):
            return None
        await self._page.set_content(html, wait_until="domcontentloaded")
        return await scraper.lies_profil(self._page, url)
