"""Die lesbare Uebersicht docs/UMKREIS_AUSBAU.md und die Terminal-Uebersicht.

Geschrieben wird nur zwischen den AUTO-Markern, eigene Notizen darunter
bleiben erhalten.
"""
import os
from datetime import datetime

import pfade
from dateihilfen import json_atomar_schreiben
from umkreis_plan import (
    QUELLEN_DATEI,
    STATUS_DATEI,
    UMKREIS_PLAN,
    credits_diesen_monat,
    lade_quellen,
    lade_status,
    naechste_orte,
    ort_status,
)

DOKU_DATEI = pfade.PROJEKT_ROOT / "docs" / "UMKREIS_AUSBAU.md"
DOKU_START = "<!-- AUTO:START -->"
DOKU_ENDE = "<!-- AUTO:END -->"
STANDARD_MONATSLIMIT = 1000  # Firecrawl Free-Plan

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
