"""Scraper für die Therapeutensuche auf therapie.de.

    python scraper.py         Suchorte durchgehen, neue Profile ergänzen
    python scraper.py --neu   alles neu (bisherigen Stand ignorieren)

- Höflich: 4 bis 6,5 Sekunden Pause zwischen zwei Seitenaufrufen.
- Bei HTTP 403/429 oder einer Captcha-Seite stoppt der Lauf sofort und
  speichert den Fortschritt. Später einfach neu starten.
- Keine Tricks gegen Bot-Erkennung: Der Browser gibt sich als automatisiert
  zu erkennen. Blockt die Seite das, ist das ihre Entscheidung.
- Fortsetzen: schon gespeicherte Profile werden übersprungen.
- Keine Screenshots: Fotos und Kontaktdaten werden nicht als Bild gesichert.

Die Profilfelder liest `lies_profil()`. Das ist die einzige Stelle dafür,
umkreis_ausbau.py nutzt sie auch.
E-Mails von Praxis-Websites ergänzt danach email_suche.py.
"""
import asyncio
import random
import re
import sys
from datetime import datetime
from urllib.parse import quote

import pfade
from dateihilfen import json_atomar_schreiben, json_sicher_laden
from merge_hilfen import ist_praxis_website
from playwright.async_api import async_playwright

BASE_URL = "https://www.therapie.de"
# therapie.de sucht pro Ort im Umkreis von 10 km. Unna und Bönen gehören
# laut PTV Dortmund zum Einzugsgebiet. Überschneidungen fallen beim
# Zusammenführen über die profil_url weg.
SUCHORTE = ["Dortmund", "Unna", "Bönen"]
PAUSE_MIN, PAUSE_MAX = 4.0, 6.5
SPEICHERN_ALLE = 5
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Woran eine Sperr- oder Captcha-Seite zu erkennen ist.
SPERR_HINWEISE = ("ich bin kein roboter", "unusual traffic", "access denied")

# Formulierungen für einen Aufnahmestopp. Der Satz wird als Zitat
# gespeichert, er dient als Nachweis für die Krankenkasse.
AUFNAHMESTOPP_MUSTER = [
    "keine neuen patienten", "keine neuen patient:innen", "keine neuen patientinnen",
    "aufnahmestopp", "keine aufnahme neuer",
    "nehme derzeit keine", "nehmen derzeit keine", "nehme zur zeit keine",
    "nehmen zur zeit keine", "nehme aktuell keine", "nehmen aktuell keine",
    "keine kapazitäten für neue", "keine freien therapieplätze",
]

_FREIE_PLAETZE_KOPF = re.compile(r"Freie Pl(?:ä|ae)tze\s*/\s*Wartezeiten\s*\n+\s*([^\n]+)", re.I)


class BanVerdacht(Exception):
    """Die Seite blockiert uns. Sofort aufhören."""


async def _pause():
    await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))


async def oeffne_seite(page, url, timeout=30000):
    """Lädt eine Seite und wirft BanVerdacht bei Sperre oder Captcha."""
    antwort = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if antwort is not None and antwort.status in (403, 429):
        raise BanVerdacht(f"HTTP {antwort.status} bei {url}")
    anfang = (await page.content())[:5000].lower()
    if any(hinweis in anfang for hinweis in SPERR_HINWEISE):
        raise BanVerdacht(f"Captcha/Sperrseite bei {url}")
    return antwort


# ---------- Suchergebnisse ----------

def such_url(ort):
    return f"{BASE_URL}/therapeutensuche/ergebnisse/?ort={quote(ort)}"


async def profil_links(page, url):
    """Alle Profil-Links einer Suchergebnisseite (ohne /info/-Unterseiten)."""
    await oeffne_seite(page, url)
    try:
        await page.wait_for_selector(".search-results-list", timeout=10000)
    except Exception:
        pass
    links = await page.eval_on_selector_all("a[href*='/profil/']", "els => [...new Set(els.map(e => e.href))]")
    return [link for link in links if "/profil/" in link and "/info/" not in link]


async def naechste_suchseite(page):
    weiter = await page.query_selector(".resultnav li.next a")
    href = await weiter.get_attribute("href") if weiter else None
    if not href:
        return None
    return href if href.startswith("http") else BASE_URL + href


async def alle_profil_urls(page, orte=None):
    """Profil-URLs aller Suchorte über alle Ergebnisseiten, ohne Doppelte.
    Eine Seite, die auf eine schon besuchte zurückverweist, beendet den Ort."""
    alle = []
    for ort in orte or SUCHORTE:
        aktuell, besucht = such_url(ort), set()
        while aktuell and aktuell not in besucht:
            besucht.add(aktuell)
            links = await profil_links(page, aktuell)
            print(f"  Suchseite: {aktuell} -> {len(links)} Profile")
            alle.extend(links)
            aktuell = await naechste_suchseite(page)
            if aktuell and aktuell not in besucht:
                await _pause()
    return list(dict.fromkeys(alle))


# ---------- Ein Profil auslesen ----------

def freie_plaetze_aus_text(profil_text):
    """Die Zeile unter der Überschrift "Freie Plätze / Wartezeiten":
    "freie Plätze" bei "Freie Plätze vorhanden", sonst der Wortlaut
    (z. B. "Wartezeit über drei Monate"). Ohne Abschnitt: leer.
    Nur die Zeile zählt, sonst träfe schon die Überschrift selbst."""
    treffer = _FREIE_PLAETZE_KOPF.search(profil_text or "")
    if not treffer:
        return ""
    zeile = treffer.group(1).strip().rstrip(".").strip()
    if re.match(r"freie pl(?:ä|ae)tze vorhanden", zeile, re.I):
        return "freie Plätze"
    return zeile[:120]


def finde_aufnahmestopp(profil_text):
    """(gefunden, zitat): der ganze Satz mit der Aufnahmestopp-Formulierung.
    Gesucht wird direkt im Original, damit das Zitat exakt stimmt."""
    for muster in AUFNAHMESTOPP_MUSTER:
        treffer = re.search(re.escape(muster), profil_text, re.IGNORECASE)
        if not treffer:
            continue
        pos = treffer.start()
        anfang = max(profil_text.rfind(".", 0, pos), profil_text.rfind("\n", 0, pos)) + 1
        enden = [e for e in (profil_text.find(".", pos), profil_text.find("\n", pos)) if e >= 0]
        ende = min(enden) + 1 if enden else min(pos + 200, len(profil_text))
        return True, profil_text[anfang:ende].strip()[:400]
    return False, ""


async def _text(page, selektor, standard=""):
    try:
        element = await page.query_selector(selektor)
        return (await element.inner_text()).strip() if element else standard
    except Exception:
        return standard


async def _adresse(page):
    """Adresse aus den Mikrodaten. Fehlen die, die Zeilen 3 bis 5 der
    Kontaktkarte (Zeile 1 ist der Name, Zeile 2 der Beruf). Gibt (adresse, plz)."""
    strasse = await _text(page, "[itemprop='streetAddress']")
    plz = await _text(page, "[itemprop='postalCode']")
    if strasse:
        stadt = await _text(page, "[itemprop='addressLocality']")
        return f"{strasse}, {plz} {stadt}".strip(", "), plz
    zeilen = [z.strip() for z in (await _text(page, ".therapist-details")).splitlines() if z.strip()]
    return " | ".join(zeilen[2:5]), plz


async def _email(page):
    link = await page.query_selector("a[href^='mailto:']")
    href = await link.get_attribute("href") if link else ""
    return href.replace("mailto:", "").split("?")[0].strip() if href else ""


async def _website(page):
    """Erster Link in den Profilblöcken, der eine echte Praxis-Website ist
    (keine therapie.de- oder Kartenlinks)."""
    for link in await page.query_selector_all(".therapist-details a[href^='http']:not([href*='therapie.de'])"):
        href = await link.get_attribute("href")
        if href and ist_praxis_website(href):
            return href
    return ""


async def _abschnitt(page, ueberschrift):
    """Listeneinträge unter einer h4-Überschrift in den Profilblöcken."""
    return await page.evaluate("""(titel) => {
        const h4 = [...document.querySelectorAll('.therapist-details h4')].find(h => h.innerText.includes(titel));
        const liste = h4 && h4.nextElementSibling;
        return liste ? [...liste.querySelectorAll('li')].map(li => li.innerText.trim()).filter(Boolean) : [];
    }""", ueberschrift)


async def _gesamttext(page):
    text = ""
    try:
        for block in await page.query_selector_all(".therapist-details"):
            text += await block.inner_text() + "\n"
    except Exception:
        pass
    return text


async def _persoenliches_profil(page):
    """Der eigene Freitext steht im letzten von mindestens drei Blöcken
    (1. Kontaktkarte, 2. Fachangaben). Bei weniger Blöcken gibt es keinen."""
    return await page.evaluate("""() => {
        const bloecke = [...document.querySelectorAll('.therapist-details')];
        if (bloecke.length < 3) return '';
        const letzter = bloecke[bloecke.length - 1];
        const absatz = letzter.querySelector('p');
        return absatz ? absatz.innerText.trim() : letzter.innerText.trim().substring(0, 1000);
    }""")


async def lies_profil(page, url):
    """Liest alle Felder aus der Profilseite, die gerade in `page` geladen ist.
    Navigiert nicht."""
    adresse, plz = await _adresse(page)
    gesamttext = await _gesamttext(page)
    stopp, zitat = finde_aufnahmestopp(gesamttext)
    abrechnung = await _text(page, "#abrechnungsverfahren")
    return {
        "profil_url": url,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
        "name": await _text(page, "h1"),
        "adresse": adresse,
        "plz": plz,
        "telefon": await _text(page, "[itemprop='telephone']"),
        "email": await _email(page),
        "website": await _website(page),
        "abrechnungsarten": [a.strip() for a in abrechnung.split(",") if a.strip()],
        "behandlungsschwerpunkte": await _abschnitt(page, "Behandlungs-Schwerpunkte"),
        "therapieverfahren": await _abschnitt(page, "Verfahren"),
        "therapieangebot": await _abschnitt(page, "Therapie-Angebot"),
        "freie_plaetze": freie_plaetze_aus_text(gesamttext),
        "aufnahmestopp": stopp,
        "aufnahmestopp_zitat": zitat,
        "persoenliches_profil": await _persoenliches_profil(page),
        "volltext": gesamttext,
    }


async def profil_laden(page, url):
    """Öffnet ein Profil und liest es aus. None bei Ladefehler,
    BanVerdacht wird weitergereicht."""
    try:
        await oeffne_seite(page, url)
        await page.wait_for_selector(".therapist-details", timeout=10000)
    except BanVerdacht:
        raise
    except Exception as fehler:
        print(f"  Ladefehler: {fehler}")
        return None
    return await lies_profil(page, url)


# ---------- Gesamtlauf ----------

def bekannte_urls(profile):
    """profil_urls des bisherigen Stands. Einträge ohne URL werden ignoriert."""
    return {p.get("profil_url") for p in profile if isinstance(p, dict) and p.get("profil_url")}


def _sperre_melden(fehler, anzahl):
    print("\n" + "=" * 60)
    print(f"STOPP: Die Seite blockiert uns gerade ({fehler}).")
    print(f"Fortschritt gespeichert ({anzahl} Profile). In ein paar Stunden neu")
    print("starten, der Lauf macht dort weiter, wo er aufgehört hat.")
    print("=" * 60)


async def main(neu=False, datei=None):
    """Sammelt neue Profile und speichert laufend. Auch bei Fehlern oder
    Strg+C wird der Stand gesichert und der Browser geschlossen."""
    datei = datei or pfade.RESULTS_RAW
    profile = [] if neu else json_sicher_laden(datei, [])
    bekannt = bekannte_urls(profile)
    print(f"=== Scraper therapie.de ({len(bekannt)} Profile schon vorhanden) ===")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            kontext = await browser.new_context(user_agent=USER_AGENT, locale="de-DE")
            page = await kontext.new_page()
            offen = [u for u in await alle_profil_urls(page) if u not in bekannt]
            print(f"Neu zu holen: {len(offen)} Profile")
            for i, url in enumerate(offen, 1):
                print(f"[{i}/{len(offen)}] {url}")
                await _pause()
                profil = await profil_laden(page, url)
                if profil:
                    profile.append(profil)
                if i % SPEICHERN_ALLE == 0:
                    json_atomar_schreiben(datei, profile)
        except BanVerdacht as fehler:
            _sperre_melden(fehler, len(profile))
        finally:
            json_atomar_schreiben(datei, profile)
            try:
                await browser.close()
            except Exception as fehler:
                print(f"  Browser konnte nicht sauber geschlossen werden: {fehler}")
    print(f"\nFertig: {len(profile)} Profile in {datei}")
    return profile


if __name__ == "__main__":
    asyncio.run(main(neu="--neu" in sys.argv))
