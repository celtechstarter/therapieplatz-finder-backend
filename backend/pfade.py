"""
Zentrale Pfade fuer alle Backend-Skripte.

Vorher hatte jedes Skript seine eigenen bare-relativen Dateinamen
("results_raw.json", "credentials.json", ...). Das funktioniert nur, wenn
man das jeweilige Skript zufaellig mit dem Projekt-Root als aktuellem
Arbeitsverzeichnis startet -- ruft man z.B. main.py aus einem anderen Ordner
auf, oder importiert ein Skript aus einem anderen Ordner, landen neue
Dateien am falschen Ort oder bestehende werden nicht gefunden.

Alles hier basiert auf Path(__file__), nicht auf dem Arbeitsverzeichnis --
funktioniert also unabhaengig davon, von wo aus ein Skript gestartet wird.

Verzeichnis-Layout (siehe auch README.md im Projekt-Root):
    therapie-mailer/
    |- backend/          <- dieses Verzeichnis (Scraper, Analyzer, Mailer, ...)
    |  |- frontend/       <- einfache lokale Vorschau-Oberflaeche (siehe main.py)
    |- data/              <- alle Scraping-/Analyse-Ergebnisse (JSON)
    |  |- archiv/          <- alte, ueberholte Zwischenstaende (nicht mehr live genutzt)
    |- credentials.json   <- Gmail-OAuth-Client (Secret, siehe .gitignore)
    |- token.json         <- Gmail-Login-Token (Secret, siehe .gitignore)
"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJEKT_ROOT = BACKEND_DIR.parent

DATA_DIR = PROJEKT_ROOT / "data"
DATA_ARCHIV_DIR = DATA_DIR / "archiv"
FRONTEND_DIR = BACKEND_DIR / "frontend"

CREDENTIALS_FILE = PROJEKT_ROOT / "credentials.json"
TOKEN_FILE = PROJEKT_ROOT / "token.json"

RESULTS_RAW = DATA_DIR / "results_raw.json"
RESULTS_ANALYZED = DATA_DIR / "results_analyzed.json"
# Generisch benannt (nicht nach der jeweiligen externen Quelle), damit dieses
# oeffentliche Repo nicht dokumentiert, welche zusaetzlichen Register/Verzeichnisse
# konkret abgeglichen werden -- siehe README fuer den Hintergrund.
RESULTS_QUELLE_A_RAW = DATA_DIR / "results_quelle_a_raw.json"
RESULTS_QUELLE_B_RAW = DATA_DIR / "results_quelle_b_raw.json"
RESULTS_QUELLE_C_RAW = DATA_DIR / "results_quelle_c_raw.json"
RESULTS_QUELLE_D_RAW = DATA_DIR / "results_quelle_d_raw.json"
RESULTS_QUELLE_E_RAW = DATA_DIR / "results_quelle_e_raw.json"
RESULTS_QUELLE_G_RAW = DATA_DIR / "results_quelle_g_raw.json"

# Alte, adressgenaue km-Werte aus der Zeit vor der PLZ-Tabelle (bis 4.10.2026
# per Nominatim ermittelt). build_webapp_chunks.py liest sie nur noch und
# bevorzugt sie vor dem PLZ-Wert; neu geschrieben wird hier nichts mehr.
GEOCODE_CACHE = DATA_DIR / "geocode_cache.json"

# Zwei unterschiedliche "Ausschluss"-Dateien, leicht zu verwechseln:
AUSGESCHLOSSEN_LOG = DATA_DIR / "ausgeschlossen.json"        # AUSGABE von analyzer.py/filters.py: alle automatisch ausgeschlossenen Profile MIT Begruendung (Audit-Log, wird bei jedem Lauf neu geschrieben)
MANUELL_AUSGESCHLOSSEN = DATA_DIR / "excluded.json"          # von main.py gepflegt: Profile, die man ueber "Ausblenden" in der lokalen Vorschau manuell ausgeblendet hat (persistent, wird nicht ueberschrieben)

# Persistente Skip-Liste fuer analyzer.py: Profile, die die KI in Kombination
# mit gkv_art == "privat" als "keine GKV-Option" eingestuft hat (siehe grosser
# Kommentar in analyzer.main()). Ohne diese Datei wuerden bei jedem Resume-Lauf
# dieselben Profile am Anfang der Liste erneut per KI-Call neu bewertet -- bei
# einem laengeren zusammenhaengenden Block aus Privatpraxen kommt der Batch
# dadurch nie ueber diesen Block hinaus (siehe Audit-Befund B12).
UEBERSPRUNGEN_LOG = DATA_DIR / "uebersprungen.json"

SENT_LOG = DATA_DIR / "sent_log.json"                        # Versandhistorie (main.py /send-Endpunkt)

# AUSGABE von stats_export.py: reine Zaehl-Kennzahlen (keine Namen, keine
# Kontaktdaten) fuer den woechentlichen n8n-Automatisierungs-Workflow, siehe
# stats_export.py fuer Details.
STATS_WOECHENTLICH = DATA_DIR / "stats_woechentlich.json"
