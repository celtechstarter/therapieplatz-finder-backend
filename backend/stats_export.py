"""
Exportiert reine Zaehl-Kennzahlen aus results_analyzed.json, ohne jede
persoenliche oder therapeutenbezogene Information (keine Namen, keine
Adressen, keine Kontaktdaten). Gedacht als Datenquelle fuer einen
woechentlichen n8n-Workflow, der automatisch prueft ob es Neuigkeiten gibt
und daraus mit Claude eine kurze Zusammenfassung schreibt.

Bewusst getrennt vom eigentlichen Analyzer/Mailer: dieses Skript liest nur,
veraendert nichts an results_analyzed.json oder an der laufenden Webapp, und
schreibt ausschliesslich Zahlen in eine eigene, kleine Ausgabedatei
(STATS_WOECHENTLICH). Der Wochenvergleich selbst (Unterschied zur letzten
Woche) passiert nicht hier, sondern im n8n-Workflow ueber dessen eigenen
Zwischenspeicher -- dieses Skript liefert bei jedem Lauf nur den aktuellen
Stand.

Aufruf: python stats_export.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dateihilfen import json_atomar_schreiben, json_sicher_laden
from pfade import RESULTS_ANALYZED, STATS_WOECHENTLICH


def berechne_stats(profile):
    gesamt = len(profile)
    kassensitz = sum(1 for p in profile if p.get("gkv_art") == "kassensitz")
    kostenerstattung = sum(1 for p in profile if p.get("gkv_art") == "kostenerstattung")
    gkv_akzeptiert = sum(1 for p in profile if p.get("GKV_akzeptiert") is True)
    freie_plaetze = sum(1 for p in profile if p.get("Freie_Plaetze") is True)
    mit_email = sum(1 for p in profile if p.get("email"))

    return {
        "erzeugt_am": datetime.now(timezone.utc).isoformat(),
        "gesamt": gesamt,
        "kassensitz": kassensitz,
        "kostenerstattung": kostenerstattung,
        "gkv_akzeptiert": gkv_akzeptiert,
        "freie_plaetze": freie_plaetze,
        "mit_email": mit_email,
    }


def main():
    profile = json_sicher_laden(RESULTS_ANALYZED, fallback=[])
    if not profile:
        print(f"Keine Daten in {RESULTS_ANALYZED} gefunden, breche ab.")
        return

    stats = berechne_stats(profile)
    json_atomar_schreiben(STATS_WOECHENTLICH, stats)

    print(f"Stats geschrieben nach {STATS_WOECHENTLICH}:")
    for schluessel, wert in stats.items():
        print(f"  {schluessel}: {wert}")


if __name__ == "__main__":
    main()
