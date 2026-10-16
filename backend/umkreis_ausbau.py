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
import sys
from datetime import datetime

import pfade
from dateihilfen import json_atomar_schreiben, json_sicher_laden
from umkreis_abruf import (
    STANDARD_PAUSE,
    CreditsLeer,
    ProfilLeser,
    ZielBlockiert,
    firecrawl_holer,
    profil_links_aus_html,
    such_url,
    trefferzahl_aus_html,
)
from umkreis_doku import DOKU_DATEI, STANDARD_MONATSLIMIT, schreibe_doku, uebersicht
from umkreis_plan import (
    STATUS_DATEI,
    buche_credits,
    credits_diesen_monat,
    lade_status,
    naechste_orte,
    speichere_status,
)

MAX_SUCHSEITEN = 60          # Notbremse gegen Endlosschleifen (15 Treffer/Seite)


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


def main(argv=None, *, status_pfad=STATUS_DATEI, doku_pfad=DOKU_DATEI, starte_lauf=None):
    """Kommandozeile. status_pfad/doku_pfad/starte_lauf sind nur fuer Tests
    austauschbar (sonst wuerde ein Test die echten Dateien ueberschreiben
    oder Firecrawl-Credits verbrauchen)."""
    parser = argparse.ArgumentParser(description="therapie.de ringfoermig ueber Firecrawl erweitern")
    parser.add_argument("--los", action="store_true", help="naechste offene Orte abarbeiten")
    parser.add_argument("--ort", help="genau diesen Ort abarbeiten")
    parser.add_argument("--budget", type=int, help="max. Credits fuer diesen Lauf")
    parser.add_argument("--max-orte", type=int, help="max. Anzahl Orte in diesem Lauf")
    parser.add_argument("--doku", action="store_true", help="nur docs/UMKREIS_AUSBAU.md neu schreiben")
    args = parser.parse_args(argv)

    status = lade_status(status_pfad)
    if args.doku:
        schreibe_doku(status, doku_pfad)
        print(f"Geschrieben: {doku_pfad}")
        return
    if not (args.los or args.ort):
        uebersicht(status)
        return

    orte = [args.ort] if args.ort else naechste_orte(status, args.max_orte)
    if not orte:
        print("Alle Orte im Plan sind erledigt. Neuen Ring in UMKREIS_PLAN ergaenzen.")
        return
    print(f"Orte in diesem Lauf: {', '.join(orte)}")
    monatslimit = int(os.getenv("FIRECRAWL_MONATSLIMIT", STANDARD_MONATSLIMIT))
    if starte_lauf is None:
        from dotenv import load_dotenv
        load_dotenv(pfade.PROJEKT_ROOT / ".env")
        holen = firecrawl_holer(os.getenv("FIRECRAWL_API_KEY"),
                                pause=float(os.getenv("FIRECRAWL_PAUSE", STANDARD_PAUSE)))
        asyncio.run(lauf(orte, holen, budget=args.budget, monatslimit=monatslimit,
                         status_pfad=status_pfad, doku_pfad=doku_pfad))
    else:
        starte_lauf(orte, budget=args.budget, monatslimit=monatslimit)
    print("\nNaechste Schritte: python dedupe_bestand.py -> python analyzer.py -> "
          "python build_webapp_chunks.py")


if __name__ == "__main__":
    main(sys.argv[1:])
