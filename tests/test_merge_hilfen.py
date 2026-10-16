"""Tests fuer backend/merge_hilfen.py.

Ausgeloest durch einen echten Datenfehler (26.8.2026): eine der Zusatzquellen
liefert Namen mit Anrede ("Herr Max Mustermann"), die alte _TITEL_MUSTER-Regex
kannte nur akademische Titel. Dadurch griff dedup_schluessel() nie zwischen
so einem Eintrag und derselben Person aus einer anderen Quelle -- 88
Therapeuten standen doppelt in den Daten (siehe Commit-Message fuer Details).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from merge_hilfen import (  # noqa: E402
    dedup_schluessel,
    normalisiere_adresse,
    normalisiere_name,
    normalisiere_telefon,
)


def test_normalisiere_name_entfernt_akademische_titel():
    assert normalisiere_name("Dipl.-Psych. Anna Beispiel") == "anna beispiel"
    assert normalisiere_name("Dr. Michael Probe") == "michael probe"
    assert normalisiere_name("M.Sc. Lisa Beispiel") == "lisa beispiel"
    assert normalisiere_name("Prof. Werner Probe") == "werner probe"


def test_normalisiere_name_entfernt_anrede():
    assert normalisiere_name("Herr Markus Muster") == "markus muster"
    assert normalisiere_name("Frau Erika Beispiel") == "erika beispiel"
    assert normalisiere_name("Herrn Klaus Test") == "klaus test"


def test_normalisiere_name_entfernt_anrede_und_titel_kombiniert():
    # Eine der Zusatzquellen liefert genau dieses Muster: Anrede VOR dem akademischen Titel.
    # "phil."/"rer. medic." sind keine erkannten Titel-Token und bleiben als
    # Resttext stehen (ebenso Akzente wie "é", die nicht im erlaubten
    # Zeichensatz sind) -- wichtig ist nur, dass beide Seiten eines Duplikats
    # auf denselben Schluessel normalisieren, siehe dedup_schluessel-Test.
    assert normalisiere_name("Herr Dr. phil. Max Beispiel") == normalisiere_name(
        "Dr. phil. Max Beispiel"
    )
    assert normalisiere_name("Frau Dr. rer. medic. Pia Muster") == normalisiere_name(
        "Dr. rer. medic. Pia Muster"
    )


def test_normalisiere_name_ohne_titel_unveraendert():
    assert normalisiere_name("Anna Beispiel") == "anna beispiel"
    assert normalisiere_name("") == ""
    assert normalisiere_name(None) == ""


def test_normalisiere_adresse_ignoriert_schreibvarianten():
    a = normalisiere_adresse("Beispielstr. 26-28, 44137 Dortmund")
    b = normalisiere_adresse("Beispielstr 26 28 44137 Dortmund")
    assert a == b


def test_dedup_schluessel_erkennt_anrede_als_gleiche_person():
    # Der eigentliche Bug: ohne die Anrede-Erweiterung waren das zwei
    # unterschiedliche Schluessel und damit zwei "verschiedene" Personen.
    a = {"name": "Diplom-Psychologe Markus Muster", "adresse": "Musterweg 9, 44135 Dortmund"}
    b = {"name": "Herr Markus Muster", "adresse": "Musterweg 9, 44135 Dortmund"}
    assert dedup_schluessel(a) == dedup_schluessel(b)


def test_dedup_schluessel_none_wenn_komplett_leer():
    assert dedup_schluessel({"name": "", "adresse": ""}) is None
    assert dedup_schluessel({}) is None


def test_normalisiere_adresse_ignoriert_strasse_vs_str():
    # Meldung eines Nutzers (23.9.2026): eine Praxis stand 3x in der
    # Liste, weil eine Quelle "Musterstr." abkuerzt, andere Quellen "Musterstraße"
    # ausschreiben.
    a = normalisiere_adresse("Musterstraße 7, 44319 Dortmund")
    b = normalisiere_adresse("Musterstr. 7, 44319 Dortmund")
    assert a == b


def test_normalisiere_adresse_schneidet_angehaengten_stadtteil_ab():
    # eine andere Quelle haengt hinter PLZ+Stadt zusaetzlich den Dortmunder
    # Stadtteil an ("44319 Dortmund-Husen" statt "44319 Dortmund") -- ohne
    # das Abschneiden waere das eine "andere" Adresse als bei den anderen
    # Quellen.
    a = normalisiere_adresse("Musterstraße 7, 44319 Dortmund")
    b = normalisiere_adresse("Musterstraße 7, 44319 Dortmund-Husen")
    assert a == b


def test_dedup_schluessel_erkennt_strasse_und_stadtteil_variante():
    a = {"name": "Maria Muster", "adresse": "Musterstraße 7, 44319 Dortmund"}
    b = {"name": "Frau Maria Muster", "adresse": "Musterstr. 7, 44319 Dortmund"}
    c = {"name": "Frau Dipl.-Psych. Maria Muster", "adresse": "Musterstraße 7, 44319 Dortmund-Husen"}
    assert dedup_schluessel(a) == dedup_schluessel(b) == dedup_schluessel(c)


def test_normalisiere_telefon_ignoriert_schreibvarianten():
    varianten = [
        "+49(231)1234567",
        "0231-1234567",
        "02311234567",
        "02 31 / 1 23 45 67",
    ]
    ergebnisse = {normalisiere_telefon(v) for v in varianten}
    assert len(ergebnisse) == 1


def test_normalisiere_telefon_leer_ohne_ziffern():
    assert normalisiere_telefon("") == ""
    assert normalisiere_telefon(None) == ""
