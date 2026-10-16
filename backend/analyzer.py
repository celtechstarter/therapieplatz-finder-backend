"""Analyzer: entscheidet, welche Praxen in die App kommen.

Ablauf (`python analyzer.py`):
1. Harte Filterregeln (filters.py) sortieren aus, wer nicht passt, zum
   Beispiel reine Kinder- und Jugendpraxen. Die KI entscheidet das nicht.
2. Von Hand ausgeblendete Praxen (data/excluded.json) fliegen raus.
3. Jedes übrige Profil wird bewertet: Kasse ja/nein, freie Plätze ja/nein.
   Zuerst mit festen Regeln (kostenlos), nur wenn nötig mit Claude.
   Mit `--ohne-ki` (oder OHNE_KI=1) gibt es gar keine API-Aufrufe.
4. Schon bewertete Profile werden übersprungen, solange sich ihr Inhalt
   nicht geändert hat (Fingerabdruck `inhalt_hash`). Alte Ergebnisse ohne
   Fingerabdruck werden nur mit `--neu-analyse-alt` neu bewertet.
5. Praxen, bei denen Regel/KI UND Filter sagen "nur privat", landen in
   der Skip-Liste und werden nicht erneut bewertet.

Der Kern (`analysiere`) arbeitet nur mit Listen im Speicher und lässt sich
deshalb ohne Dateien und ohne echte KI testen. `main()` kümmert sich um
Dateien, Ausgaben und den API-Schlüssel.
"""
import os
import random
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

import analyse_ki
import email_vorlagen
import filters
import pfade
from analyse_regeln import (analyse_ohne_ki, analyse_per_regel, inhalt_hash,
                            ist_reine_privatpraxis, muss_analysiert_werden,
                            zu_wenig_angaben)
from dateihilfen import json_atomar_schreiben, json_sicher_laden

load_dotenv()

# Neutrale Werte für das Referenzfeld Email_generiert. Die Webapp nutzt das
# Feld nicht, sie baut den echten Text aus den Angaben der jeweiligen Person.
REFERENZ_NAME = os.environ.get("REFERENZ_NAME", "Max Mustermann")
REFERENZ_SITUATION = os.environ.get(
    "REFERENZ_SITUATION", "Ich suche einen ambulanten Psychotherapieplatz.")

# Kostenlose Regel-Ergebnisse werden nur alle N Profile gespeichert (die
# Datei ist mehrere MB groß). Nach jedem bezahlten KI-Aufruf sofort.
SPEICHERN_ALLE_OHNE_KI = 200


def _schalter(name, umgebung, argv):
    argv = sys.argv[1:] if argv is None else argv
    return os.environ.get(umgebung, "").strip() == "1" or name in argv


def ohne_ki_modus(argv=None):
    return _schalter("--ohne-ki", "OHNE_KI", argv)


def alte_neu_analysieren(argv=None):
    return _schalter("--neu-analyse-alt", "NEU_ANALYSE_ALT", argv)


def jetzt_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ohne(eintraege, urls):
    """Kopie der Liste ohne die Einträge mit diesen profil_urls."""
    return [e for e in eintraege if e.get("profil_url") not in urls]


def waehle_zu_bewertende(profile, ergebnisse, skips, alte_neu=False):
    """Welche Profile müssen bewertet werden? Gibt (liste, gruende) zurück.

    `gruende` zählt, warum ein Profil (nicht) dran ist, für die Ausgabe.
    Doppelte profil_urls werden nur einmal bewertet."""
    def nach_url(eintraege):
        index = {}
        for e in eintraege:
            index.setdefault(e.get("profil_url"), e)  # erster Eintrag zählt
        return index

    alte_ergebnisse, alte_skips = nach_url(ergebnisse), nach_url(skips)
    auswahl, gruende, gesehen = [], {}, set()
    for profil in profile:
        url = profil.get("profil_url")
        if url in gesehen:
            continue
        gesehen.add(url)
        vorher = alte_ergebnisse.get(url) or alte_skips.get(url)
        ja, grund = muss_analysiert_werden(profil, vorher, alte_neu)
        if ja and vorher is None and zu_wenig_angaben(profil):
            ja, grund = False, "wartet auf Angaben"
        gruende[grund] = gruende.get(grund, 0) + 1
        if ja:
            auswahl.append(profil)
    return auswahl, gruende


def bewerte(profil, ki, ohne_ki_lauf=False):
    """Bewertet ein Profil. Gibt (bewertung, ohne_ki) zurück.

    Reihenfolge: feste Regel (kostenlos, wenn eindeutig), im --ohne-ki-Modus
    die Wortsuche, sonst die KI. `bewertung` ist None, wenn die KI
    mehrfach scheiterte."""
    bewertung = analyse_ohne_ki(profil)
    if bewertung is not None:
        return bewertung, True
    if ohne_ki_lauf:
        return analyse_per_regel(profil), True
    return ki(profil), False


def als_ergebnis(profil, bewertung, zufall, zeitpunkt):
    """Fügt Profil, Bewertung, Mail-Vorlage und Fingerabdruck zusammen.

    Die Bewertung enthält nur erlaubte Felder, kann also keine
    Originaldaten wie die E-Mail-Adresse überschreiben."""
    text, anrede, therapieform = email_vorlagen.zufaellige_anfrage(
        profil, REFERENZ_NAME, REFERENZ_SITUATION, zufallsgenerator=zufall)
    return {**profil, **bewertung,
            "Email_generiert": text, "anrede": anrede, "therapieform": therapieform,
            "inhalt_hash": inhalt_hash(profil), "analysiert_am": zeitpunkt}


def setze_ergebnis(ergebnisse, neu):
    """Ersetzt ein altes Ergebnis mit gleicher profil_url an seiner Stelle
    (Reihenfolge bleibt stabil) oder hängt das neue an. Weitere Duplikate
    derselben URL fallen weg."""
    url = neu.get("profil_url")
    pos = next((i for i, e in enumerate(ergebnisse) if e.get("profil_url") == url), None)
    if pos is None:
        return [*ergebnisse, neu]
    return [neu if i == pos else e for i, e in enumerate(ergebnisse)
            if i == pos or e.get("profil_url") != url]


def skip_eintrag(profil, zeitpunkt):
    return {"profil_url": profil.get("profil_url"), "name": profil.get("name"),
            "grund": "KI: GKV_akzeptiert=false UND gkv_art=privat",
            "inhalt_hash": inhalt_hash(profil), "analysiert_am": zeitpunkt}


def analysiere(profile, ergebnisse, skips, *, ki, ohne_ki_lauf=False, alte_neu=False,
               zufall=random, zeit=jetzt_iso, zwischenspeichern=lambda e, s: None):
    """Kern des Analyzers, nur im Speicher. Gibt (ergebnisse, skips, statistik).

    `profile` sind die schon gefilterten Rohprofile, `ergebnisse` und `skips`
    der bisherige Stand. `ki` ist die Funktion, die ein Profil bewertet (im
    Betrieb analyse_ki.frage_ki, in Tests eine Attrappe).
    `zwischenspeichern(ergebnisse, skips)` wird nach jedem bezahlten
    KI-Aufruf, jeder Skip-Entscheidung und alle 200 Regel-Ergebnisse
    aufgerufen, damit ein Absturz keinen bezahlten Fortschritt kostet."""
    auswahl, gruende = waehle_zu_bewertende(profile, ergebnisse, skips, alte_neu)
    statistik = {"gruende": gruende, "ohne_ki": 0, "ki": 0, "fehlgeschlagen": 0, "privat": 0}
    for profil in auswahl:
        url = profil.get("profil_url")
        bewertung, kostenlos = bewerte(profil, ki, ohne_ki_lauf)
        statistik["ohne_ki" if kostenlos else "ki"] += 1
        if bewertung is None:
            statistik["fehlgeschlagen"] += 1  # altes Ergebnis bleibt stehen
            continue
        if ist_reine_privatpraxis(bewertung, profil):
            statistik["privat"] += 1
            ergebnisse = ohne(ergebnisse, {url})
            skips = [*ohne(skips, {url}), skip_eintrag(profil, zeit())]
            zwischenspeichern(ergebnisse, skips)
            continue
        ergebnisse = setze_ergebnis(ergebnisse, als_ergebnis(profil, bewertung, zufall, zeit()))
        skips = ohne(skips, {url})
        if not kostenlos or statistik["ohne_ki"] % SPEICHERN_ALLE_OHNE_KI == 0:
            zwischenspeichern(ergebnisse, skips)
    return ergebnisse, skips, statistik


def _pruefe_schluessel(ohne_ki_lauf):
    if ohne_ki_lauf:
        print("Modus --ohne-ki: keine API-Aufrufe, alle Profile per Regeln (kostenlos).")
        return
    schluessel = os.environ.get("ANTHROPIC_API_KEY", "")
    if not schluessel or schluessel == "platzhalter":
        print("\nFEHLER: ANTHROPIC_API_KEY fehlt. Bitte in .env eintragen "
              "oder kostenlos mit --ohne-ki analysieren.")
        sys.exit(1)


def main(argv=None, ki=None):
    """Liest die Dateien in data/, ruft `analysiere` auf und schreibt das
    Ergebnis zurück. Gibt die Ergebnisliste zurück."""
    ohne_ki_lauf, alte_neu = ohne_ki_modus(argv), alte_neu_analysieren(argv)
    _pruefe_schluessel(ohne_ki_lauf)
    if not os.path.exists(pfade.RESULTS_RAW):
        print(f"Fehler: {pfade.RESULTS_RAW} nicht gefunden. Bitte zuerst scrapen.")
        return []

    rohprofile = json_sicher_laden(pfade.RESULTS_RAW, [])
    print(f"=== Filter: {len(rohprofile)} Profile ===")
    behalten, raus = filters.filtere(rohprofile, gkv_erforderlich=True)
    json_atomar_schreiben(pfade.AUSGESCHLOSSEN_LOG, raus)

    von_hand = {e.get("profil_url") for e in json_sicher_laden(pfade.MANUELL_AUSGESCHLOSSEN, [])
                if e.get("profil_url")}
    nicht_mehr_zulaessig = von_hand | {r.get("profil_url") for r in raus if r.get("profil_url")}
    behalten = ohne(behalten, von_hand)
    ergebnisse = ohne(json_sicher_laden(pfade.RESULTS_ANALYZED, []), nicht_mehr_zulaessig)
    skips = ohne(json_sicher_laden(pfade.UEBERSPRUNGEN_LOG, []), nicht_mehr_zulaessig)

    def speichern(e, s):
        json_atomar_schreiben(pfade.RESULTS_ANALYZED, e)
        json_atomar_schreiben(pfade.UEBERSPRUNGEN_LOG, s)

    ergebnisse, skips, statistik = analysiere(
        behalten, ergebnisse, skips, ki=ki or analyse_ki.frage_ki,
        ohne_ki_lauf=ohne_ki_lauf, alte_neu=alte_neu, zwischenspeichern=speichern)
    speichern(ergebnisse, skips)

    print(f"Stand vorher: {statistik['gruende']}")
    print(f"Bewertet: {statistik['ki']} per KI, {statistik['ohne_ki']} ohne KI, "
          f"{statistik['fehlgeschlagen']} fehlgeschlagen, {statistik['privat']} nur privat.")
    print(f"Fertig: {len(ergebnisse)} Praxen in {pfade.RESULTS_ANALYZED}, "
          f"{len(skips)} dauerhaft übersprungen.")
    return ergebnisse


if __name__ == "__main__":
    main()
