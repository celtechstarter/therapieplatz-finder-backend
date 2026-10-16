"""Tests fuer backend/merge_hilfen.py.

Ausgeloest durch einen echten Datenfehler (26.8.2026): eine der Zusatzquellen
liefert Namen mit Anrede ("Herr Max Mustermann"), die alte _TITEL_MUSTER-Regex
kannte nur akademische Titel. Dadurch griff dedup_schluessel() nie zwischen
so einem Eintrag und derselben Person aus einer anderen Quelle -- 88
Therapeuten standen doppelt in den Daten (siehe Commit-Message fuer Details).
"""

import pytest
from merge_hilfen import (
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


# ---------- ist_praxis_website ----------

@pytest.mark.parametrize("href,erwartet", [
    ("https://www.praxis-beispiel.de", True),
    ("https://www.google.com/maps/search/?api=1&query=51.4,7.5", False),
    ("https://maps.google.de/?q=x", False),
    ("https://maps.apple.com/place?q=x", False),
    ("https://www.openstreetmap.org/#map=1", False),
    ("https://WWW.THERAPIE.DE/profil/x/", False),   # Groß-/Kleinschreibung egal
    ("", False), (None, False),
])
def test_ist_praxis_website(href, erwartet):
    from merge_hilfen import ist_praxis_website
    assert ist_praxis_website(href) is erwartet


# ---------- merge ----------

def _anreichern_mit_telefon(bestehend, zusatz):
    if not bestehend.get("telefon") and zusatz.get("telefon"):
        bestehend["telefon"] = zusatz["telefon"]
        return True
    return False


def test_merge_zaehlt_neue_und_angereicherte_eintraege():
    from merge_hilfen import merge
    roh = [{"profil_url": "r1", "name": "Anna Beispiel", "adresse": "Beispielstr 1, 44135 Dortmund"}]
    zusatz = [
        {"profil_url": "z1", "name": "Frau Anna Beispiel", "adresse": "Beispielstr. 1, 44135 Dortmund", "telefon": "0231 1"},
        {"profil_url": "z2", "name": "Peter Probe", "adresse": "Testweg 2, 44137 Dortmund"},
        {"profil_url": "z3", "name": "Peter Probe", "adresse": "Testweg 2, 44137 Dortmund"},   # Dublette von z2
        {"profil_url": "r1", "name": "egal"},                                                 # URL schon da
    ]
    ergebnis, neu, angereichert = merge(roh, zusatz, _anreichern_mit_telefon)
    assert (neu, angereichert) == (1, 1)
    assert [e["profil_url"] for e in ergebnis] == ["r1", "z2"]
    assert roh[0]["telefon"] == "0231 1"
    assert len(roh) == 1   # die Eingabeliste selbst wächst nicht


def test_merge_uebernimmt_eintraege_ohne_name_und_adresse_statt_sie_zu_verwerfen():
    from merge_hilfen import merge
    ergebnis, neu, _ = merge([], [{"profil_url": "a"}, {"profil_url": "b"}], _anreichern_mit_telefon)
    assert neu == 2 and [e["profil_url"] for e in ergebnis] == ["a", "b"]


def test_merge_ohne_aenderung_zaehlt_nicht_als_angereichert():
    from merge_hilfen import merge
    roh = [{"profil_url": "r1", "name": "Anna Beispiel", "adresse": "Beispielstr 1", "telefon": "da"}]
    _, neu, angereichert = merge(roh, [{"profil_url": "z1", "name": "Anna Beispiel", "adresse": "Beispielstr 1",
                                        "telefon": "anders"}], _anreichern_mit_telefon)
    assert (neu, angereichert) == (0, 0)


def test_dedup_schluessel_reicht_name_oder_adresse_allein():
    assert dedup_schluessel({"name": "Anna Beispiel"}) == ("anna beispiel", "")
    assert dedup_schluessel({"adresse": "Beispielstr 1"}) is not None
