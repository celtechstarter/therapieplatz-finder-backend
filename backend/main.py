"""Startbefehl für die Backend-Pipeline.

    python main.py                   Scraper, danach KI-Analyse
    python main.py --skip-scraper    nur die KI-Analyse
    python main.py --skip-analyzer   nur der Scraper (kein API-Schlüssel nötig)
    python main.py --only-emails     fehlende E-Mails auf Praxis-Websites suchen
    python main.py --stats           Zahlen zum aktuellen Datenstand

Früher startete main.py zusätzlich einen lokalen Server mit Vorschau und
verschickte Mails über Gmail. Das macht seit Okt. 2026 nur noch die Webapp
(Versand über Resend), deshalb ist dieser Teil entfernt.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

import pfade
from dateihilfen import json_sicher_laden

load_dotenv()


def zahlen_zum_datenstand():
    """Liefert die wichtigsten Zahlen als Dict (getrennt von der Ausgabe,
    damit sie sich ohne print() testen lassen)."""
    roh = json_sicher_laden(pfade.RESULTS_RAW, [])
    analysiert = json_sicher_laden(pfade.RESULTS_ANALYZED, [])
    mit_email = sum(1 for t in analysiert if t.get("email"))
    return {
        "gescrapt": len(roh),
        "in_der_app": len(analysiert),
        "mit_email": mit_email,
        "ohne_email": len(analysiert) - mit_email,
    }


def zeige_statistik():
    z = zahlen_zum_datenstand()
    print("\n=== STATISTIK ===")
    print(f"  Gescrapte Profile:       {z['gescrapt']}")
    print(f"  Praxen in der App:       {z['in_der_app']}")
    print(f"  Davon mit E-Mail:        {z['mit_email']}")
    print(f"  Davon nur Telefon:       {z['ohne_email']}")


def api_key_vorhanden():
    """True, wenn ein echter ANTHROPIC_API_KEY gesetzt ist."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(key) and key != "platzhalter"


def _pruefe_api_key():
    """Bricht VOR dem Scraper ab, wenn der Schlüssel fehlt. Der Scraper läuft
    stundenlang, der Analyzer danach würde ohne Schlüssel sofort abbrechen,
    und die ganze Wartezeit wäre umsonst gewesen."""
    if api_key_vorhanden():
        return
    print("FEHLER: ANTHROPIC_API_KEY ist nicht gesetzt.")
    print("  - Schlüssel in die Datei .env im Projektordner eintragen,")
    print("  - oder kostenlos ohne KI analysieren: python analyzer.py --ohne-ki,")
    print("  - oder nur scrapen: python main.py --skip-analyzer")
    sys.exit(1)


async def run_scraper():
    print("\n=== SCHRITT 1: Scraper ===")
    import scraper
    await scraper.main()


def run_analyzer():
    print("\n=== SCHRITT 2: Analyzer ===")
    import analyzer
    analyzer.main()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    print("=== Therapieplatz Finder: Backend ===\n")

    if "--stats" in argv:
        zeige_statistik()
        return

    if "--only-emails" in argv:
        print("=== MODUS: Nur E-Mail-Suche ===")
        import email_suche
        asyncio.run(email_suche.ergaenze_emails())
        return

    if "--skip-analyzer" not in argv:
        _pruefe_api_key()

    if "--skip-scraper" in argv:
        print("Scraper übersprungen (--skip-scraper)")
    else:
        asyncio.run(run_scraper())

    if "--skip-analyzer" in argv:
        print("Analyzer übersprungen (--skip-analyzer)")
    else:
        run_analyzer()

    zeige_statistik()


if __name__ == "__main__":
    main()
