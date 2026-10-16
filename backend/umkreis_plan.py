"""Der Ausbau-Plan: welche Orte in welchem Ring liegen und wie weit jeder
Ort schon ist (data/umkreis_status.json), inklusive verbrauchter
Firecrawl-Credits pro Monat.

Wird von umkreis_ausbau.py und von den ortsbasierten Zusatz-Scrapern
benutzt, damit alle denselben Plan abarbeiten.
"""
from datetime import datetime

import pfade
from dateihilfen import json_atomar_schreiben, json_sicher_laden

STATUS_DATEI = pfade.DATA_DIR / "umkreis_status.json"
# Eigene Datei (nicht in STATUS_DATEI): ein laufender --los-Prozess haelt den
# Status im Speicher und schreibt ihn nach jedem Profil komplett zurueck --
# ein gleichzeitig laufender Kammer-/KV-Scraper wuerde seinen Vermerk sonst
# verlieren (so passiert am 30.9.2026).
QUELLEN_DATEI = pfade.DATA_DIR / "umkreis_quellen.json"

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
