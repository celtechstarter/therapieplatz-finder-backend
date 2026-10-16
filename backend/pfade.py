"""Alle Datei- und Ordnerpfade des Backends an einer Stelle.

Die Pfade hängen nur davon ab, wo diese Datei liegt, nicht davon, aus
welchem Ordner ein Skript gestartet wird. So landen Ergebnisse immer in
`data/`, egal wie man `python ...` aufruft.

    therapie-mailer/
    |- backend/   <- Python-Code (dieser Ordner)
    |- data/      <- alle Ergebnisse als JSON (nicht im Git)
       |- archiv/ <- alte Sicherungen
"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJEKT_ROOT = BACKEND_DIR.parent

DATA_DIR = PROJEKT_ROOT / "data"
DATA_ARCHIV_DIR = DATA_DIR / "archiv"

# Rohdaten aller Quellen und das Ergebnis nach Filter + Analyse.
RESULTS_RAW = DATA_DIR / "results_raw.json"
RESULTS_ANALYZED = DATA_DIR / "results_analyzed.json"

# Rohdaten der zusätzlichen Register. Bewusst neutral benannt, damit das
# öffentliche Repo nicht verrät, welche Verzeichnisse genau abgeglichen werden.
RESULTS_QUELLE_A_RAW = DATA_DIR / "results_quelle_a_raw.json"
RESULTS_QUELLE_B_RAW = DATA_DIR / "results_quelle_b_raw.json"
RESULTS_QUELLE_C_RAW = DATA_DIR / "results_quelle_c_raw.json"
RESULTS_QUELLE_D_RAW = DATA_DIR / "results_quelle_d_raw.json"
RESULTS_QUELLE_E_RAW = DATA_DIR / "results_quelle_e_raw.json"
RESULTS_QUELLE_G_RAW = DATA_DIR / "results_quelle_g_raw.json"

# Alte, adressgenaue Entfernungen aus der Zeit vor der PLZ-Tabelle.
# build_webapp_chunks.py liest sie nur noch, neu geschrieben wird nichts.
GEOCODE_CACHE = DATA_DIR / "geocode_cache.json"

# Zwei Ausschluss-Dateien, leicht zu verwechseln:
# - ausgeschlossen.json schreibt der Analyzer bei JEDEM Lauf neu: wer von den
#   Filterregeln aussortiert wurde und warum.
# - excluded.json pflegst du von Hand: Praxen, die nie in der App landen
#   sollen. Wird nie automatisch überschrieben.
AUSGESCHLOSSEN_LOG = DATA_DIR / "ausgeschlossen.json"
MANUELL_AUSGESCHLOSSEN = DATA_DIR / "excluded.json"

# Praxen, die der Analyzer als "keine Kasse" übersprungen hat. Ohne diese
# Liste würde jeder neue Lauf dieselben Privatpraxen wieder an die KI schicken.
UEBERSPRUNGEN_LOG = DATA_DIR / "uebersprungen.json"

# Alte Versandliste aus der Zeit, als das Backend selbst Mails verschickt hat.
# dedupe_bestand.py nutzt sie noch: bereits angeschriebene Praxen bleiben beim
# Zusammenführen von Dubletten bevorzugt erhalten.
SENT_LOG = DATA_DIR / "sent_log.json"

# Reine Zählwerte (keine Namen, keine Kontaktdaten) für den wöchentlichen
# n8n-Bericht, siehe stats_export.py.
STATS_WOECHENTLICH = DATA_DIR / "stats_woechentlich.json"
