"""40 vorformulierte Anfrage-Mails an Praxen (Texte in daten/anfrage_vorlagen.json).

Wofuer: analyzer.py legt mit zufaellige_anfrage() pro Praxis einen
Beispieltext in results_analyzed.json ab (Feld Email_generiert). Die
Webapp verschickt diesen Text NICHT. Sie baut die echte Mail selbst im
Browser aus den Angaben der Person (buildEmail() in webapp/app/app-utils.js).

Warum 40 Texte statt einem: viele gleiche Mails an viele Praxen wirken wie
ein Serienbrief. Alle 40 sagen dasselbe, nur anders formuliert.

Regeln fuer jeden Text:
  - einfache Sprache, keine Gedankenstriche
  - fest: gesetzlich versichert, ambulante Therapie fuer Erwachsene
  - fragt nach der ungefaehren Wartezeit (ein "nicht erreicht" reicht
    Kassen wie der TK nicht als Nachweis)
  - endet mit dem eigenen Namen der Person

Platzhalter (werden mit .format() gefuellt):
  {anrede}       z. B. "Frau Dr. Müller" (aus anrede_aus_name())
  {therapieform} z. B. "Verhaltenstherapie" (aus therapieform_aus_profil())
  {name}         Name der Person, die schreibt
  {situation}    ein ganzer Satz mit Punkt, z. B. "Bei mir wurde eine
                 Angststoerung festgestellt."
"""
import json
import random
import re
from pathlib import Path

VORLAGEN = json.loads((Path(__file__).parent / "daten" / "anfrage_vorlagen.json").read_text(encoding="utf-8"))

_PREFIX_MUSTER = re.compile(
    r"^((?:(?:Frau|Herr|Herrn|Dr\.?|Prof\.?|Dipl\.-?Psych\.?|Diplom-?Psycho\w+|"
    r"M\.?\s?Sc\.?|M\.?\s?A\.?|B\.?\s?Sc\.?|Univ\.?|rer\.?|nat\.?|phil\.?|medic\.?)\.?\s*)+)",
    re.IGNORECASE,
)


def anrede_aus_name(name):
    """Leitet aus einem vollen Profilnamen (Frau Dipl.-Psych. Anna Beispiel)
    eine Anrede ab (Frau Dipl.-Psych. Beispiel): Anrede und Titel bleiben
    stehen, der Vorname faellt weg. Grobe Heuristik ohne Anspruch auf
    hundert Prozent Treffsicherheit bei ungewoehnlichen Namen, der Text
    kann vor dem Versand ohnehin noch angepasst werden."""
    name = (name or "").strip()
    if not name:
        return ""
    treffer = _PREFIX_MUSTER.match(name)
    if treffer:
        praefix = treffer.group(1).strip()
        rest = name[len(treffer.group(1)):].strip()
    else:
        praefix = ""
        rest = name
    teile = rest.split()
    nachname = teile[-1] if teile else ""
    if praefix and nachname:
        return f"{praefix} {nachname}"
    return nachname or name


def therapieform_aus_profil(therapeut):
    """Nimmt das erste nicht leere Therapieverfahren aus dem Profil, zum
    Beispiel Verhaltenstherapie (Richtlinie) wird zu Verhaltenstherapie,
    sonst denselben Standardwert, den app/app.js clientseitig sowieso
    verwendet, wenn nichts bekannt ist."""
    for verfahren in (therapeut or {}).get("therapieverfahren") or []:
        v = (verfahren or "").strip()
        v = re.sub(r"\s*\(.*?\)\s*$", "", v).strip()
        if v:
            return v
    return "Einzeltherapie"


def zufaellige_anfrage(therapeut, name, situation, zufallsgenerator=random):
    """Waehlt zufaellig eine der vierzig Vorlagen und befuellt sie mit
    Anrede/Therapieform aus dem Profil sowie dem EIGENEN Namen und
    Situationssatz der absendenden Person (name/situation sind absichtlich
    Pflichtparameter ohne Standardwert -- das verhindert, dass irgendwo
    versehentlich wieder feste Absender-Werte einschleichen, siehe
    Modul-Docstring). Gibt ein Dreiertupel zurueck (email_text, anrede,
    therapieform), damit der Aufrufer anrede/therapieform separat
    speichern kann statt sie spaeter per Regex aus dem Text
    zurueckzugewinnen. zufallsgenerator ist injizierbar fuer deterministische
    Tests (z.B. ein Objekt mit fester choice()-Rueckgabe)."""
    anrede = anrede_aus_name((therapeut or {}).get("name"))
    therapieform = therapieform_aus_profil(therapeut)
    vorlage = zufallsgenerator.choice(VORLAGEN)
    email_text = vorlage.format(anrede=anrede, therapieform=therapieform, name=name, situation=situation)
    return email_text, anrede, therapieform
