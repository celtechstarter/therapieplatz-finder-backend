"""
Harte, nachvollziehbare Filterregeln – laufen VOR der KI-Analyse.

Regeln:
1. Muss Einzeltherapie für Erwachsene anbieten.
2. Reine Kinder- und Jugendlichenpsychotherapeuten (KJP) werden ausgeschlossen
   (KJP dürfen nur Patienten bis 21 Jahre behandeln).
3. Heilpraktiker für Psychotherapie ohne Approbation werden ausgeschlossen,
   wenn GKV-Abrechnung gewünscht ist (keine Kassenleistung möglich).

"Approbation fuer Erwachsene" wird seit Review #10 dreistufig bewertet
(siehe _approbations_status): bestaetigt / unklar (-> Warnung, Profil
bleibt drin) / keine (-> Regel 2 bzw. 3 greift). Verneinungen ("ohne
Approbation") und reine KJP-Approbationen zaehlen nicht als Nachweis.

Jedes Profil bekommt eine Begründung (aufgenommen / ausgeschlossen und warum).
"""
import re

# Berufsbezeichnungen
KJP_RE = re.compile(
    r"kinder\W{0,3}und\W{0,3}jugendlichen\W{0,3}psychotherapeut", re.IGNORECASE)

# Starke Nachweise einer Erwachsenen-Approbation: die Berufsbezeichnung selbst.
# Toleriert auch die Genderschreibweise, die therapie.de als Label nutzt
# ("Psychologische/r Psychotherapeut/in", "Facharzt/-aerztin fuer ...").
ERWACHSENEN_BERUF_RE = re.compile(
    r"psychologische(?:[rn]|/r)?\s+psychotherapeut"
    r"|ärztliche(?:[rn]|/r)?\s+psychotherapeut"
    r"|facharzt(?:/-?ärztin)?\s+für\s+psych"
    r"|fachärztin\s+für\s+psych", re.IGNORECASE)

# Schwacher Hinweis: das Wort "Approbation"/"approbiert(e)" allein sagt nicht,
# WOFUER approbiert wurde (Kinder- und Jugendlichenpsychotherapeuten sind
# ebenfalls approbiert) und steht oft in verneinter Form im Profil
# ("ohne Approbation"). Nur ganze Woerter, damit z.B. "Approbationsausbildung"
# (Ausbildung, noch keine Approbation) nicht zaehlt.
APPROBATION_WORT_RE = re.compile(
    r"\bapprob(?:ation|iert(?:e[rnms]?)?)\b", re.IGNORECASE)

# Verneinung kurz VOR einem Treffer ("ohne Approbation", "keine approbierte
# ...", "nicht approbiert"). "nicht nur" ist keine Verneinung.
_VERNEINUNG_RE = re.compile(r"\b(?:ohne|kein\w*|nicht(?!\s+nur\b))\b", re.IGNORECASE)
_VERNEINUNG_FENSTER = 30   # Zeichen vor dem Treffer
# Satzteilgrenzen: eine Verneinung in einem anderen Satz(teil) zaehlt nicht
# ("Keine Kassenzulassung, Psychologische Psychotherapeutin").
_SATZTEIL_GRENZE_RE = re.compile(r"[.,;:!?()\n]")
# Approbations-Wort, das zur KJP-Berufsbezeichnung gehoert: direkt davor
# ("approbierte KJP", "Approbation als KJP") ...
_VOR_KJP_ZWISCHEN_RE = re.compile(r"^\s*(?:als|zur|zum|für|einer?|eines?)?\s*$", re.IGNORECASE)
# ... oder kurz dahinter ("KJP/in approbiert", "KJP mit abschliessender
# Approbation") -- solange keine andere Berufsbezeichnung dazwischen steht.
_NACH_KJP_ABSTAND = 30
_NACH_KJP_STOPP_RE = re.compile(r"[.;:!?\n]|psycholog|ärzt|facharzt", re.IGNORECASE)
# Erwaehnung anderer Personen ("approbierte Kolleginnen", "mit approbierten
# Mitarbeitern") ist kein Nachweis fuer die Person des Profils.
_ANDERE_PERSON_NACH_RE = re.compile(r"^\W{0,3}(?:kolleg|mitarbeiter|supervisor)", re.IGNORECASE)


def _ist_verneint(text, start):
    fenster = text[max(0, start - _VERNEINUNG_FENSTER):start]
    fenster = _SATZTEIL_GRENZE_RE.split(fenster)[-1]
    return bool(_VERNEINUNG_RE.search(fenster))


def _gehoert_zu_kjp(text, treffer, kjp_treffer):
    for k in kjp_treffer:
        if 0 <= k.start() - treffer.end() <= 20 and \
                _VOR_KJP_ZWISCHEN_RE.match(text[treffer.end():k.start()]):
            return True
        abstand = treffer.start() - k.end()
        if 0 <= abstand <= _NACH_KJP_ABSTAND and \
                not _NACH_KJP_STOPP_RE.search(text[k.end():treffer.start()]):
            return True
    return False


def _approbations_status(text):
    """Bewertet, ob das Profil eine Approbation fuer ERWACHSENE belegt.

    Rueckgabe: (status, verneint)
      status 'bestaetigt' - nicht verneinte Berufsbezeichnung Psychologische/
                            Aerztliche Psychotherapeut/in bzw. Facharzt fuer
                            Psych...; und KEINE ausdrueckliche Verneinung
                            ("ohne Approbation") an anderer Stelle
      status 'unklar'     - nur ein allgemeines "Approbation"/"approbiert"
                            ohne Angabe wofuer, oder widerspruechliche Angaben
                            (Berufsbezeichnung UND "ohne Approbation")
      status 'keine'      - nichts davon, oder nur verneinte Erwaehnungen,
                            nur KJP-Approbation ("approbierte Kinder- und
                            Jugendlichenpsychotherapeutin", "Approbation als
                            KJP"), nur Erwaehnung anderer Personen
                            ("approbierte Kolleginnen")
      verneint            - True, wenn irgendwo eine verneinte Erwaehnung
                            gefunden wurde
    Bewusst konservativ: im Zweifel 'unklar' (-> Warnung in der Oberflaeche)
    statt 'bestaetigt'. Grenzen: Verneinungen NACH dem Wort ("Approbation
    liegt nicht vor") und Berufsbezeichnungen anderer Personen ("Supervision
    bei Psychologischer Psychotherapeutin X") werden nicht erkannt.
    """
    kjp_treffer = list(KJP_RE.finditer(text))
    stark = allgemein = verneint = False
    for m in ERWACHSENEN_BERUF_RE.finditer(text):
        if _ist_verneint(text, m.start()):
            verneint = True
        else:
            stark = True
    for m in APPROBATION_WORT_RE.finditer(text):
        if _ist_verneint(text, m.start()):
            verneint = True
        elif _gehoert_zu_kjp(text, m, kjp_treffer):
            continue
        elif _ANDERE_PERSON_NACH_RE.match(text[m.end():]):
            continue
        else:
            allgemein = True
    if stark and not verneint:
        return "bestaetigt", verneint
    if stark or allgemein:
        return "unklar", verneint
    return "keine", verneint


HEILPRAKTIKER_RE = re.compile(r"heilpraktiker", re.IGNORECASE)

# Regel 1 prüfte bisher auf exakte String-Gleichheit mit
# "einzeltherapie: erwachsene". Live-Daten geben aktuell recht (Label kommt
# einheitlich von therapie.de), aber schon eine harmlose Variante wie
# "Einzeltherapie: Erwachsene (ab 18)" oder ein Layout-Wechsel auf der
# Zielseite würde JEDES Profil still ausschließen, ohne Fehlermeldung.
# Deshalb: robuster Teilstring-Vergleich statt Gleichheit.
_EINZEL_ERWACHSEN_RE = re.compile(r"einzel", re.IGNORECASE)
_ERWACHSEN_RE = re.compile(r"erwachsen", re.IGNORECASE)

# Zusatzprüfung über die ZUSAMMENGEFÜGTE Angebotsliste: sollte therapie.de
# das Label eines Tages auf zwei Listenpunkte aufteilen ("Einzeltherapie:" /
# "Erwachsene"), findet die Prüfung pro Einzeleintrag nichts mehr und würde
# stillschweigend alle Profile ausschließen. Die Nähe-Bedingung (max. 25
# Zeichen zwischen "einzel" und "erwachsen") verhindert dabei den
# umgekehrten Fehler: bei ["Einzeltherapie: Kinder/Jugendliche",
# "Gruppentherapie: Erwachsene"] liegen die beiden Wörter weit auseinander
# und der Eintrag gilt weiterhin (korrekt) NICHT als Einzeltherapie für
# Erwachsene.
_EINZEL_ERWACHSEN_NAH_RE = re.compile(r"einzel.{0,25}?erwachsen", re.IGNORECASE | re.DOTALL)


def _bietet_einzeltherapie_erwachsene(angebot_liste):
    eintraege = [str(a) for a in (angebot_liste or []) if a]
    if any(_EINZEL_ERWACHSEN_RE.search(a) and _ERWACHSEN_RE.search(a) for a in eintraege):
        return True
    return bool(_EINZEL_ERWACHSEN_NAH_RE.search(" ".join(eintraege)))


def _text(wert):
    """None-sicher zu String: gescrapte Profile enthalten regelmäßig JSON
    `null` statt eines leeren Strings (Feld auf der Quellseite nicht
    gepflegt). profil.get("name", "") liefert dann None und " ".join(...)
    bzw. .lower() wirft TypeError – der Filterlauf würde für das ganze
    Profil abbrechen."""
    return str(wert) if wert else ""


def _liste_text(wert):
    """None-sicher zu String über ein Listenfeld. Einzelne None-Einträge in
    der Liste werden übersprungen (sonst TypeError in " ".join)."""
    return " ".join(str(x) for x in (wert or []) if x)


def _volltext(profil):
    teile = [
        _text(profil.get("name")),
        _text(profil.get("persoenliches_profil")),
        _text(profil.get("volltext")),
        _liste_text(profil.get("therapieangebot")),
        _liste_text(profil.get("therapieverfahren")),
    ]
    return " ".join(teile).lower()


def pruefe_profil(profil, gkv_erforderlich=True):
    """
    Prüft ein Profil gegen die harten Regeln.
    Rückgabe: dict mit
      ok: True/False
      grund: warum ausgeschlossen (wenn ok=False)
      warnungen: Liste von Hinweisen (wenn ok=True, aber etwas auffiel)
    """
    text = _volltext(profil)
    # None-Einträge in der Liste überspringen (JSON `null` im gescrapten
    # Datensatz), sonst wirft a.strip() einen AttributeError.
    angebot = [str(a).strip().lower() for a in (profil.get("therapieangebot") or []) if a]
    warnungen = []

    # --- Regel 1: Einzeltherapie für Erwachsene ---
    if angebot:
        if not _bietet_einzeltherapie_erwachsene(angebot):
            angebot_klartext = ", ".join(
                str(a) for a in (profil.get("therapieangebot") or []) if a)
            return {
                "ok": False,
                "grund": "Bietet laut Profil keine Einzeltherapie für Erwachsene an "
                         f"(Angebot: {angebot_klartext or 'leer'})",
                "warnungen": [],
            }
    else:
        # Angebot fehlt im Profil -> nicht automatisch ausschließen.
        # Der KJP-Check (Regel 2) unten fängt reine Kinder-/Jugendtherapeuten
        # zuverlässig ab. Fehlt das Feld nur, weil es auf therapie.de nicht
        # gepflegt wurde, wollen wir approbierte Erwachsenen-Therapeuten
        # (z.B. "Psychologische/r Psychotherapeut/in approbiert") nicht verlieren.
        warnungen.append("Therapieangebot im Profil nicht explizit angegeben – bitte im Profil prüfen")

    # --- Regel 2: Reine KJP ausschließen ---
    # Seit Review #10 dreistufig (siehe _approbations_status): nur eine
    # nicht verneinte Erwachsenen-Berufsbezeichnung gilt als Nachweis. Ein
    # allgemeines "Approbation" ohne Angabe wofuer fuehrt NICHT mehr zu
    # "bestaetigt", sondern zu einer Pruef-Warnung (Profil bleibt drin, wie
    # bisher). Verneinte Erwaehnungen ("ohne Approbation") und reine
    # KJP-Approbationen zaehlen gar nicht.
    ist_kjp = bool(KJP_RE.search(text))
    status, verneint = _approbations_status(text)
    ist_approbiert_erwachsene = status == "bestaetigt"
    approbation_unklar = status == "unklar"
    if ist_kjp and status == "keine":
        return {
            "ok": False,
            "grund": "Kinder- und Jugendlichenpsychotherapeut/in – behandelt keine Erwachsenen "
                     "(Zulassung nur bis 21 Jahre)",
            "warnungen": [],
        }
    if ist_kjp and ist_approbiert_erwachsene:
        warnungen.append("Behandelt auch Kinder/Jugendliche – Erwachsenen-Zulassung laut Profil vorhanden")
    if ist_kjp and approbation_unklar:
        warnungen.append("Kinder- und Jugendlichenpsychotherapeut/in – ob eine Approbation für "
                         "Erwachsene vorliegt, ist laut Profil unklar – bitte im Profil prüfen")

    # --- Regel 3: Heilpraktiker ohne Approbation ---
    ist_heilpraktiker = bool(HEILPRAKTIKER_RE.search(text))
    if ist_heilpraktiker and status == "keine":
        if gkv_erforderlich:
            return {
                "ok": False,
                "grund": "Heilpraktiker/in für Psychotherapie ohne Approbation – "
                         "keine Abrechnung über die gesetzliche Krankenkasse möglich",
                "warnungen": [],
            }
        warnungen.append("Heilpraktiker/in – nur Selbstzahler/Privat, keine gesetzliche Kasse")
    if ist_heilpraktiker and approbation_unklar:
        warnungen.append("Heilpraktiker/in – Approbation laut Profil nicht eindeutig belegt – "
                         "Kassenabrechnung bitte im Profil prüfen")

    # --- Widerspruechliche Angaben (Berufsbezeichnung + "ohne Approbation") ---
    if verneint and approbation_unklar and not ist_kjp and not ist_heilpraktiker:
        warnungen.append("Widersprüchliche Angaben zur Approbation im Profil – bitte prüfen")

    # --- Zusatz-Hinweis: keine erkennbare Berufsbezeichnung ---
    if status == "keine" and not ist_kjp and not ist_heilpraktiker:
        if not re.search(r"psychotherapeut", text, re.IGNORECASE):
            warnungen.append("Berufsbezeichnung im Profil nicht eindeutig erkennbar – bitte im Profil prüfen")

    return {"ok": True, "grund": "", "warnungen": warnungen}


def kategorie(profil):
    """
    Ordnet jedes Profil einer Abrechnungs-Kategorie zu:
      'kassensitz'       - normale gesetzliche Kasse (direkter Kassenplatz)
      'kostenerstattung' - nimmt Gesetzliche NUR über das Kostenerstattungsverfahren
      'privat'           - nur Privatversicherte/Selbstzahler
    Wichtig: Eine Absage von 'kostenerstattung'-Praxen zählt bei der Kasse
    NICHT als reguläre Absage – die App zeigt diese daher getrennt an.

    ACHTUNG bei der Prüfung: therapie.de listet Abrechnungsarten manchmal als
    EIN kombiniertes Label statt zwei getrennter Einträge, z. B.
    "Gesetzliche Krankenversicherung im Kostenerstattungsverfahren" (ein
    einziger Listeneintrag). Das heißt: die Praxis behandelt gesetzlich
    Versicherte AUSSCHLIESSLICH über Kostenerstattung, hat keinen eigenen
    Kassensitz – trotzdem enthält der Text die Wörter "gesetzliche
    krankenversicherung". Ein Gesamt-String-Check (frühere Version dieser
    Funktion) matchte das fälschlich als 'kassensitz' (Fall einer Praxis,
    19.8.2026 entdeckt: identischer Bug existierte auch schon
    im Frontend-Pendant `app/app.js`). Deshalb hier: jeden Abrechnungsarten-
    Eintrag EINZELN prüfen, nicht den zusammengefügten Gesamttext.
    """
    eintraege = [str(a) for a in (profil.get("abrechnungsarten") or []) if a]
    hat_kassensitz = False
    hat_kostenerstattung = False
    for eintrag in eintraege:
        s = eintrag.lower()
        if "kostenerstattung" in s:
            hat_kostenerstattung = True
            continue  # "gesetzlich" in diesem Eintrag qualifiziert nur den
            # Kostenerstattungsweg, ist kein eigenstaendiger Kassensitz-Beleg.
        if "gesetzliche krankenversicherung" in s or "gesetzlich" in s:
            hat_kassensitz = True
    if hat_kassensitz:
        return "kassensitz"
    if hat_kostenerstattung:
        return "kostenerstattung"
    return "privat"


def filtere(profile, gkv_erforderlich=True, verbose=True):
    """Wendet die Regeln auf eine Liste an. Gibt (behalten, ausgeschlossen) zurück.

    ACHTUNG: verändert die übergebenen Dicts IN-PLACE. Jedes Profil bekommt
    zusätzlich zu seinen gescrapten Feldern:
      - `filter_warnungen` (Liste): Hinweise, die in der Oberfläche angezeigt
        werden (fehlendes Therapieangebot, Kostenerstattung, Aufnahmestopp, ...)
      - `gkv_art` (String): 'kassensitz' | 'kostenerstattung' | 'privat'
      - `ausschluss_grund` (String, nur bei ausgeschlossenen Profilen)
    Die zurückgegebenen Listen enthalten dieselben Objekte wie `profile`,
    keine Kopien. Wer die Originaldaten unverändert braucht (z.B. um sie
    danach noch einmal roh wegzuschreiben), muss vorher selbst kopieren.
    Der Analyzer nutzt genau dieses Verhalten: er liest `gkv_art` nach dem
    Filterlauf direkt vom Therapeuten-Dict.
    """
    behalten, raus = [], []
    for p in profile:
        ergebnis = pruefe_profil(p, gkv_erforderlich=gkv_erforderlich)
        p["filter_warnungen"] = ergebnis["warnungen"]
        p["gkv_art"] = kategorie(p)
        if p["gkv_art"] == "kostenerstattung":
            p["filter_warnungen"].append(
                "Nimmt Gesetzliche nur über Kostenerstattung – Absage zählt "
                "nicht als reguläre Absage (separater Bereich)")
        if p.get("aufnahmestopp"):
            # Nur ein Hinweis, keine automatische Nachweis-Zaehlung mehr
            # (Aenderung 18.8.2026): die Praxis bleibt in der normalen
            # Kassenplaetze-Liste und wird ganz normal angeschrieben, damit
            # ein echter, persoenlich adressierter Kontaktversuch entsteht -
            # das ist fuer die Krankenkasse ein staerkerer Nachweis als eine
            # aus dem Profiltext abgeleitete Automatik.
            p["filter_warnungen"].append(
                "AUFNAHMESTOPP laut Profil – Praxis wird trotzdem normal "
                "angeschrieben")
        if ergebnis["ok"]:
            behalten.append(p)
        else:
            p["ausschluss_grund"] = ergebnis["grund"]
            raus.append(p)
            if verbose:
                print(f"  AUSGESCHLOSSEN: {p.get('name','?')}")
                print(f"    -> {ergebnis['grund']}")
    if verbose:
        print(f"\n  Filter-Ergebnis: {len(behalten)} behalten, {len(raus)} ausgeschlossen.")
    return behalten, raus


def main(argv=None):
    """Filter von Hand laufen lassen: `python filters.py [rohdatei.json]`.

    Schreibt die Ausgeschlossenen mit Grund nach data/ausgeschlossen.json
    und gibt die Zahl der behaltenen Profile zurück.
    """
    import sys
    import pfade
    from dateihilfen import json_atomar_schreiben, json_sicher_laden
    argv = sys.argv[1:] if argv is None else argv
    quelle = argv[0] if argv else str(pfade.RESULTS_RAW)
    profile = json_sicher_laden(quelle, [])
    print(f"Prüfe {len(profile)} Profile aus {quelle} ...\n")
    behalten, raus = filtere(profile)
    # Atomar schreiben (siehe dateihilfen.py): ein Abbruch mitten im Schreiben
    # würde sonst ein unlesbares Ausschluss-Log hinterlassen.
    json_atomar_schreiben(pfade.AUSGESCHLOSSEN_LOG, raus)
    print(f"Details der Ausgeschlossenen: {pfade.AUSGESCHLOSSEN_LOG}")
    return len(behalten)


if __name__ == "__main__":
    main()
