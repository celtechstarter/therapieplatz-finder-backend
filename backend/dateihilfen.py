"""
Gemeinsame Helfer fuer sicheres Datei-Schreiben.

Grund: alle Skripte in diesem Projekt schrieben JSON-Ergebnisdateien bisher
per `open(pfad, "w")` direkt auf die Zieldatei. Ein Absturz, Ctrl+C oder
Stromausfall MITTEN im Schreiben (bei ~1 MB grossen results_*.json realistisch)
hinterlaesst eine abgeschnittene, nicht mehr parsebare Datei -- und damit den
Totalverlust aller bisherigen Scraping-/Analyse-Ergebnisse bzw. der
Versandhistorie (sent_log.json). json_atomar_schreiben() umgeht das: es
schreibt in eine temporaere Datei im selben Verzeichnis und benennt sie erst
nach vollstaendigem, geflushtem Schreiben atomar auf den Zielnamen um
(os.replace ist unter Windows und Linux atomar).
"""
import json
import os
import tempfile
from pathlib import Path


def json_atomar_schreiben(pfad, daten):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(pfad.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, pfad)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def json_sicher_laden(pfad, fallback):
    """Laedt JSON, faellt bei kaputter/fehlender Datei auf `fallback` zurueck
    statt den ganzen Lauf mit einer unbehandelten Exception abzubrechen."""
    pfad = Path(pfad)
    if not pfad.exists():
        return fallback
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return fallback
