"""
Umkreis-Ausbau: therapie.de Ort fuer Ort ueber Firecrawl erweitern.

Idee (30.9.2026): statt auf einen Schlag ganz Deutschland zu holen, wird der
Bestand ringfoermig um Dortmund herum erweitert (siehe UMKREIS_PLAN). Jeder
Lauf arbeitet die naechsten offenen Orte ab, bis das Credit-Budget erreicht
ist, und merkt sich alles in data/umkreis_status.json. Nach jedem Ort wird
docs/UMKREIS_AUSBAU.md automatisch neu geschrieben, damit jederzeit
nachlesbar ist, welche Orte schon dazugekommen sind.

Warum Firecrawl statt scraper.py (Playwright)? Firecrawl holt die Seiten von
seinen eigenen Servern ab. Unser eigener Scraper bleibt fuer Dortmund/Unna/
Boenen (scraper.SUCHORTE) zustaendig und kostet nichts; dieses Skript ist
nur fuer die Erweiterung gedacht.

Credits sparen (Free-Plan: 1.000 Seiten/Monat):
  1. FILTER AN DER QUELLE: die Suchliste wird schon bei therapie.de auf
     "Kassenleistung oder Kostenerstattung" + "Einzeltherapie: Erwachsene"
     eingeschraenkt (URL-Parameter, siehe SUCH_FILTER). Genau diese Praxen
     behaelt filters.py sowieso -- Beispiel Luenen: 277 statt 79 Treffer.
     Nebenwirkung: Profile, die das Feld "Therapie-Angebot" gar nicht
     ausgefuellt haben, fehlen dadurch (filters.py haette sie nur mit
     Warnung behalten).
  2. BEKANNTE PROFILE UEBERSPRINGEN: schon in results_raw.json vorhandene
     Profil-URLs kosten keinen Credit (die Suche "in und um <Ort>"
     ueberlappt stark mit Nachbarorten).
  3. RESUME: bricht ein Lauf mitten in einem Ort ab (Budget leer), werden
     die noch offenen Profil-URLs gespeichert -- die Suchseiten muessen beim
     naechsten Mal nicht erneut abgerufen werden.

Das Auslesen der Profilfelder passiert NICHT hier, sondern ueber
scraper.lies_profil() -- das von Firecrawl gelieferte HTML wird dafuer in
einen lokalen Browser geladen (page.set_content, alle Netzwerk-Requests
blockiert). So gibt es nur eine Stelle, die ein therapie.de-Profil ausliest.

Aufruf (aus backend/):
  python umkreis_ausbau.py                 Uebersicht: Plan, Status, Credits (kostet nichts)
  python umkreis_ausbau.py --los           naechste offene Orte abarbeiten
  python umkreis_ausbau.py --los --budget 200 --max-orte 3
  python umkreis_ausbau.py --ort "Luenen"  genau diesen Ort (auch ausserhalb des Plans)
  python umkreis_ausbau.py --doku          nur docs/UMKREIS_AUSBAU.md neu schreiben

Danach wie gewohnt: python dedupe_bestand.py -> python analyzer.py ->
python build_webapp_chunks.py (siehe docs/UMKREIS_AUSBAU.md).

Benoetigt FIRECRAWL_API_KEY in der .env (siehe .env.example).
"""
import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote

import pfade
import requests
from dateihilfen import json_atomar_schreiben, json_sicher_laden

BASE_URL = "https://www.therapie.de"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

STATUS_DATEI = pfade.DATA_DIR / "umkreis_status.json"
# Eigene Datei (nicht in STATUS_DATEI): ein laufender --los-Prozess haelt den
# Status im Speicher und schreibt ihn nach jedem Profil komplett zurueck --
# ein gleichzeitig laufender Kammer-/KV-Scraper wuerde seinen Vermerk sonst
# verlieren (so passiert am 30.9.2026).
QUELLEN_DATEI = pfade.DATA_DIR / "umkreis_quellen.json"
DOKU_DATEI = pfade.PROJEKT_ROOT / "docs" / "UMKREIS_AUSBAU.md"

# therapie.de-Suchfilter (Werte aus dem Suchformular, geprueft 30.9.2026):
#   abrechnungsverfahren=7 -> "Kassenleistung oder Kostenerstattung"
#   therapieangebot=1      -> "Einzeltherapie: Erwachsene"
SUCH_FILTER = "&abrechnungsverfahren=7&therapieangebot=1"
MAX_SUCHSEITEN = 60          # Notbremse gegen Endlosschleifen (15 Treffer/Seite)
STANDARD_MONATSLIMIT = 1000  # Firecrawl Free-Plan
STANDARD_PAUSE = 6.5         # Sekunden zwischen Abrufen (Free-Plan: 10/Min.)

DOKU_START = "<!-- AUTO:START -->"
DOKU_ENDE = "<!-- AUTO:END -->"

# Ringe um Dortmund-Wickede (PLZ 44319, Referenzpunkt der km-Angaben in der
# Webapp). km-Angaben sind grobe Luftlinien-Schaetzungen fuer die Reihenfolge.
# Ring 0 wurde vor diesem Skript mit scraper.py erfasst (ohne Quellfilter).
UMKREIS_PLAN = [
    {"ring": 0, "titel": "Bestand (scraper.py)", "orte": [
        ("Dortmund", 0), ("Unna", 10), ("Bönen", 17)]},
    {"ring": 1, "titel": "bis ca. 15 km", "orte": [
        ("Holzwickede", 5), ("Kamen", 10), ("Schwerte", 12), ("Lünen", 13),
        ("Bergkamen", 15), ("Fröndenberg", 15)]},
    {"ring": 2, "titel": "ca. 15 bis 25 km", "orte": [
        ("Herdecke", 18), ("Waltrop", 18), ("Castrop-Rauxel", 20), ("Witten", 20),
        ("Werne", 20), ("Werl", 22), ("Hamm", 22), ("Menden", 22), ("Iserlohn", 22),
        ("Wetter (Ruhr)", 22), ("Selm", 23), ("Hagen", 23)]},
    {"ring": 3, "titel": "ca. 25 bis 40 km", "orte": [
        ("Bochum", 25), ("Datteln", 25), ("Herne", 28), ("Sprockhövel", 28),
        ("Hemer", 30), ("Recklinghausen", 30), ("Hattingen", 32), ("Schwelm", 35),
        ("Ennepetal", 35), ("Lüdinghausen", 35), ("Soest", 38), ("Ahlen", 38),
        ("Arnsberg", 38), ("Gelsenkirchen", 38), ("Marl", 38), ("Haltern am See", 40)]},
    {"ring": 4, "titel": "ca. 40 bis 60 km", "orte": [
        ("Essen", 45), ("Wuppertal", 45), ("Lüdenscheid", 45), ("Gladbeck", 45),
        ("Bottrop", 48), ("Dorsten", 50), ("Beckum", 50), ("Münster", 55),
        ("Lippstadt", 55)]},
]

# Ortsnamen, die es in Deutschland mehrfach gibt, liefern bei therapie.de
# 0 Treffer ("0 Therapeuten in und um |", Befund 30.9.2026: Hamm, Hagen,
# Muenster, Marl, Menden, Froendenberg). Dafuer eindeutige Suchbegriffe
# (Hauptpostleitzahl bzw. Name mit Zusatz), geprueft im Browser.
SUCHBEGRIFF = {
    "Hamm": "59065",
    "Hagen": "58095",
    "Münster": "48143",
    "Marl": "45768",
    "Fröndenberg": "58730",
    "Menden": "Menden (Sauerland)",
}

BESTAND_ORTE = {o for ring in UMKREIS_PLAN if ring["ring"] == 0 for o, _ in ring["orte"]}


def suchorte(bis_ring=0):
    """Alle Orte der Ringe 0..bis_ring in Plan-Reihenfolge. Damit arbeiten die
    ortsbasierten Zusatz-Scraper (Kammer, KV) denselben Plan ab wie der
    therapie.de-Ausbau -- eine Liste, keine Kopien in jedem Scraper."""
    return [o for ring in UMKREIS_PLAN if ring["ring"] <= bis_ring for o, _ in ring["orte"]]


def bis_ring_aus_argv(argv, standard=0):
    """Liest '--bis-ring N' aus der Kommandozeile der Zusatz-Scraper."""
    if "--bis-ring" in argv:
        i = argv.index("--bis-ring")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            return int(argv[i + 1])
        raise SystemExit("--bis-ring braucht eine Zahl, z.B. --bis-ring 1")
    return standard


def lade_quellen(pfad=None):
    daten = json_sicher_laden(pfad or QUELLEN_DATEI, {})
    return daten if isinstance(daten, dict) else {}


def vermerke_quelle(quelle, bis_ring, orte_ohne_treffer=(), status_pfad=STATUS_DATEI,
                    doku_pfad=DOKU_DATEI, jetzt=datetime.now, quellen_pfad=None):
    """Haelt fest, bis zu welchem Ring eine Zusatzquelle abgefragt wurde, und
    aktualisiert docs/UMKREIS_AUSBAU.md -- damit dort auch fuer Kammer/KV
    nachlesbar ist, was schon dazugekommen ist."""
    quellen_pfad = quellen_pfad or QUELLEN_DATEI
    quellen = lade_quellen(quellen_pfad)
    quellen[quelle] = {"bis_ring": bis_ring, "datum": jetzt().strftime("%Y-%m-%d"),
                       "ohne_treffer": sorted(orte_ohne_treffer)}
    json_atomar_schreiben(quellen_pfad, quellen)
    schreibe_doku(lade_status(status_pfad), doku_pfad, quellen=quellen)


class FirecrawlFehler(Exception):
    pass


class CreditsLeer(FirecrawlFehler):
    """Firecrawl meldet 402: Monats-Credits aufgebraucht."""


class ZielBlockiert(FirecrawlFehler):
    """therapie.de selbst antwortet mit 403/429 -> sofort aufhoeren."""


# ---------------------------------------------------------------------------
# Status (data/umkreis_status.json)
# ---------------------------------------------------------------------------

def lade_status(pfad=STATUS_DATEI):
    status = json_sicher_laden(pfad, {})
    if not isinstance(status, dict):
        status = {}
    status.setdefault("orte", {})
    status.setdefault("credits_pro_monat", {})
    return status


def speichere_status(status, pfad=STATUS_DATEI):
    json_atomar_schreiben(pfad, status)


def monat(jetzt=None):
    return (jetzt or datetime.now()).strftime("%Y-%m")


def credits_diesen_monat(status, jetzt=None):
    return int(status["credits_pro_monat"].get(monat(jetzt), 0))


def buche_credits(status, anzahl, ort=None, jetzt=None):
    m = monat(jetzt)
    status["credits_pro_monat"][m] = credits_diesen_monat(status, jetzt) + anzahl
    if ort:
        eintrag = status["orte"].setdefault(ort, {})
        eintrag["credits"] = int(eintrag.get("credits", 0)) + anzahl


def ort_status(status, ort):
    if ort in BESTAND_ORTE:
        return "bestand"
    return status["orte"].get(ort, {}).get("status", "offen")


def naechste_orte(status, max_orte=None):
    """Offene oder angefangene Orte in Ring-Reihenfolge (angefangene zuerst
    innerhalb ihres Rings, damit nichts halb liegen bleibt)."""
    ergebnis = []
    for ring in UMKREIS_PLAN:
        if ring["ring"] == 0:
            continue
        orte = [o for o, _ in ring["orte"] if ort_status(status, o) in ("offen", "teilweise")]
        orte.sort(key=lambda o: 0 if ort_status(status, o) == "teilweise" else 1)
        ergebnis.extend(orte)
    return ergebnis[:max_orte] if max_orte else ergebnis


# ---------------------------------------------------------------------------
# Suchseiten
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Firecrawl
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Profil-Auslese (lokaler Browser, kein Netzwerk)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

class BudgetErreicht(Exception):
    pass


async def bearbeite_ort(ort, status, ergebnisse, holen, leser, budget_rest,
                        speichern=lambda: None, jetzt=datetime.now):
    """Arbeitet einen Ort ab. budget_rest ist eine Liste mit einem Element
    (veraenderbar), damit der Aufrufer den Rest sieht. Wirft BudgetErreicht,
    wenn das Budget mitten im Ort endet (Status bleibt 'teilweise')."""
    eintrag = status["orte"].setdefault(ort, {})
    eintrag["status"] = "teilweise"
    bekannt = {r.get("profil_url") for r in ergebnisse if isinstance(r, dict)}

    def abbuchen(credits):
        buche_credits(status, credits, ort, jetzt())
        budget_rest[0] -= credits

    offene = eintrag.get("offene_urls")
    if offene is None:
        gefunden = []
        for seite in range(1, MAX_SUCHSEITEN + 1):
            if budget_rest[0] <= 0:
                raise BudgetErreicht()
            html, credits = await asyncio.to_thread(holen, such_url(ort, seite))
            abbuchen(credits)
            if seite == 1:
                eintrag["treffer"] = trefferzahl_aus_html(html)
                if not eintrag["treffer"] and not profil_links_aus_html(html):
                    # Meist ein mehrdeutiger Ortsname (siehe SUCHBEGRIFF) --
                    # nicht als "fertig" abhaken, sonst faellt der Ort still weg.
                    eintrag["status"] = "kein_treffer"
                    eintrag.pop("offene_urls", None)
                    speichern()
                    print(f"  {ort}: 0 Treffer -- Suchbegriff pruefen (SUCHBEGRIFF in umkreis_ausbau.py)")
                    return
            links = profil_links_aus_html(html)
            neue = [link for link in links if link not in gefunden]
            if not neue:
                break
            gefunden.extend(neue)
            print(f"  {ort}: Suchseite {seite} -> {len(neue)} Profile")
        eintrag["suchseiten"] = seite
        eintrag["gefunden"] = len(gefunden)
        offene = [u for u in gefunden if u not in bekannt]
        eintrag["offene_urls"] = offene
        eintrag.setdefault("neu", 0)
        speichern()
        print(f"  {ort}: {len(gefunden)} gefunden, davon {len(offene)} neu")

    while offene:
        if budget_rest[0] <= 0:
            raise BudgetErreicht()
        url = offene[0]
        if url not in bekannt:
            html, credits = await asyncio.to_thread(holen, url)
            abbuchen(credits)
            profil = await leser.lesen(url, html)
            if profil:
                profil["suchort"] = ort
                profil["erfasst_ueber"] = "firecrawl"
                ergebnisse.append(profil)
                bekannt.add(url)
                eintrag["neu"] = int(eintrag.get("neu", 0)) + 1
                print(f"    + {profil.get('name', '?')}")
            else:
                eintrag.setdefault("fehlgeschlagen", []).append(url)
                print(f"    ! kein Profil erkannt: {url}")
        offene.pop(0)
        speichern()

    eintrag["status"] = "fertig"
    eintrag["datum"] = jetzt().strftime("%Y-%m-%d")
    eintrag.pop("offene_urls", None)
    speichern()


async def lauf(orte, holen, leser_fabrik=ProfilLeser, budget=None, monatslimit=STANDARD_MONATSLIMIT,
               status_pfad=STATUS_DATEI, raw_pfad=pfade.RESULTS_RAW, doku_pfad=DOKU_DATEI,
               jetzt=datetime.now):
    status = lade_status(status_pfad)
    ergebnisse = json_sicher_laden(raw_pfad, [])
    rest_monat = monatslimit - credits_diesen_monat(status, jetzt())
    budget_rest = [min(budget, rest_monat) if budget is not None else rest_monat]
    print(f"Budget fuer diesen Lauf: {budget_rest[0]} Credits "
          f"(diesen Monat schon {credits_diesen_monat(status, jetzt())} von {monatslimit}).")
    if budget_rest[0] <= 0:
        print("Monatslimit erreicht -- naechsten Monat weitermachen.")
        return status

    def speichern():
        json_atomar_schreiben(raw_pfad, ergebnisse)
        speichere_status(status, status_pfad)

    try:
        async with leser_fabrik() as leser:
            for ort in orte:
                print(f"\n=== {ort} ===")
                try:
                    await bearbeite_ort(ort, status, ergebnisse, holen, leser, budget_rest,
                                        speichern, jetzt)
                finally:
                    schreibe_doku(status, doku_pfad)
    except BudgetErreicht:
        print("\nBudget fuer diesen Lauf aufgebraucht -- Fortschritt gespeichert.")
    except CreditsLeer as e:
        print(f"\n{e} Fortschritt gespeichert.")
    except ZielBlockiert as e:
        print(f"\nSTOPP: {e}. Bitte einige Stunden warten. Fortschritt gespeichert.")
    finally:
        speichern()
        schreibe_doku(status, doku_pfad)
    return status


# ---------------------------------------------------------------------------
# docs/UMKREIS_AUSBAU.md
# ---------------------------------------------------------------------------

_STATUS_TEXT = {"bestand": "Bestand", "offen": "offen", "teilweise": "angefangen", "fertig": "fertig",
                "kein_treffer": "0 Treffer, Suchbegriff prüfen"}


def doku_tabelle(status, jetzt=None, quellen=None):
    zeilen = [f"_Automatisch aktualisiert am {(jetzt or datetime.now()).strftime('%d.%m.%Y %H:%M')}. "
              f"Firecrawl-Credits: " +
              (", ".join(f"{m}: {c}" for m, c in sorted(status["credits_pro_monat"].items())) or "noch keine") +
              "_", ""]
    fertig = sum(1 for o in status["orte"].values() if o.get("status") == "fertig")
    neu = sum(int(o.get("neu", 0)) for o in status["orte"].values())
    zeilen += [f"**Stand:** {fertig} Orte fertig, {neu} neue Profile über Firecrawl.", ""]
    plan_orte = set()
    for ring in UMKREIS_PLAN:
        zeilen += [f"### Ring {ring['ring']}: {ring['titel']}", "",
                   "| Ort | ca. km | Status | Datum | Treffer (gefiltert) | gefunden | neu geholt | Credits |",
                   "|---|---|---|---|---|---|---|---|"]
        for ort, km in ring["orte"]:
            plan_orte.add(ort)
            e = status["orte"].get(ort, {})
            zeilen.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                ort, km, _STATUS_TEXT[ort_status(status, ort)], e.get("datum", ""),
                e.get("treffer") if e.get("treffer") is not None else "",
                e.get("gefunden", ""), e.get("neu", ""), e.get("credits", "")))
        zeilen.append("")
    quellen = quellen if quellen is not None else lade_quellen()
    if quellen:
        zeilen += ["### Weitere Quellen (eigene Scraper, keine Credits)", "",
                   "| Quelle | abgefragt bis Ring | Datum | Orte ohne Treffer |", "|---|---|---|---|"]
        for name, q in sorted(quellen.items()):
            zeilen.append(f"| {name} | {q.get('bis_ring', '')} | {q.get('datum', '')} | "
                          f"{', '.join(q.get('ohne_treffer') or []) or '-'} |")
        zeilen.append("")
    extra = [o for o in status["orte"] if o not in plan_orte]
    if extra:
        zeilen += ["### Zusätzliche Orte (außerhalb des Plans)", "",
                   "| Ort | Status | Datum | gefunden | neu geholt | Credits |", "|---|---|---|---|---|---|"]
        for ort in extra:
            e = status["orte"][ort]
            zeilen.append(f"| {ort} | {_STATUS_TEXT.get(e.get('status', 'offen'), '?')} | {e.get('datum', '')} | "
                          f"{e.get('gefunden', '')} | {e.get('neu', '')} | {e.get('credits', '')} |")
        zeilen.append("")
    return "\n".join(zeilen)


def schreibe_doku(status, pfad=DOKU_DATEI, jetzt=None, quellen=None):
    """Ersetzt nur den Bereich zwischen den AUTO-Markern; der Text drumherum
    (Erklaerung, Notizen) bleibt unangetastet."""
    tabelle = doku_tabelle(status, jetzt, quellen)
    alt = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
    if DOKU_START in alt and DOKU_ENDE in alt:
        vorne = alt.split(DOKU_START)[0]
        hinten = alt.split(DOKU_ENDE, 1)[1]
    else:
        vorne = alt or "# Umkreis-Ausbau\n\n"
        hinten = "\n"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(f"{vorne}{DOKU_START}\n{tabelle}\n{DOKU_ENDE}{hinten}", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def uebersicht(status):
    print(f"Credits diesen Monat: {credits_diesen_monat(status)} "
          f"von {int(os.getenv('FIRECRAWL_MONATSLIMIT', STANDARD_MONATSLIMIT))}")
    for ring in UMKREIS_PLAN:
        print(f"\nRing {ring['ring']} ({ring['titel']}):")
        for ort, km in ring["orte"]:
            e = status["orte"].get(ort, {})
            extra = f"  neu: {e.get('neu', 0)}" if e else ""
            print(f"  {ort:<18} ca. {km:>2} km  {_STATUS_TEXT[ort_status(status, ort)]}{extra}")
    naechste = naechste_orte(status, 3)
    print(f"\nAls Naechstes: {', '.join(naechste) if naechste else 'alles erledigt'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="therapie.de ringfoermig ueber Firecrawl erweitern")
    parser.add_argument("--los", action="store_true", help="naechste offene Orte abarbeiten")
    parser.add_argument("--ort", help="genau diesen Ort abarbeiten")
    parser.add_argument("--budget", type=int, help="max. Credits fuer diesen Lauf")
    parser.add_argument("--max-orte", type=int, help="max. Anzahl Orte in diesem Lauf")
    parser.add_argument("--doku", action="store_true", help="nur docs/UMKREIS_AUSBAU.md neu schreiben")
    args = parser.parse_args(argv)

    status = lade_status()
    if args.doku:
        schreibe_doku(status)
        print(f"Geschrieben: {DOKU_DATEI}")
        return
    if not (args.los or args.ort):
        uebersicht(status)
        return

    from dotenv import load_dotenv
    load_dotenv(pfade.PROJEKT_ROOT / ".env")
    holen = firecrawl_holer(os.getenv("FIRECRAWL_API_KEY"),
                            pause=float(os.getenv("FIRECRAWL_PAUSE", STANDARD_PAUSE)))
    orte = [args.ort] if args.ort else naechste_orte(status, args.max_orte)
    if not orte:
        print("Alle Orte im Plan sind erledigt. Neuen Ring in UMKREIS_PLAN ergaenzen.")
        return
    print(f"Orte in diesem Lauf: {', '.join(orte)}")
    asyncio.run(lauf(orte, holen, budget=args.budget,
                     monatslimit=int(os.getenv("FIRECRAWL_MONATSLIMIT", STANDARD_MONATSLIMIT))))
    print("\nNaechste Schritte: python dedupe_bestand.py -> python analyzer.py -> "
          "python build_webapp_chunks.py")


if __name__ == "__main__":
    main(sys.argv[1:])
