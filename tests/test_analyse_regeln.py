"""Tests für analyse_regeln.py: die festen, kostenlosen Bewertungsregeln."""

import pytest


import analyse_ki
import analyse_regeln as regeln


def _profil(**extra):
    p = {"profil_url": "https://www.therapie.de/profil/hash/", "name": "Dipl.-Psych. Hash",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
         "persoenliches_profil": "Freie Plaetze ab sofort.",
         "volltext": "Profiltext\n123 Seitenaufrufe seit 01.01.2020\n"}
    p.update(extra)
    return p


# ---------- inhalt_hash ----------

def test_hash_ignoriert_seitenzaehler_leerzeichen_und_metadaten():
    a = _profil()
    b = _profil(volltext="Profiltext\n  99999 Seitenaufrufe seit 01.01.2020  \n",
                scraped_at="2026-09-26", quelle="x", gkv_art="kassensitz", filter_warnungen=["w"])
    assert regeln.inhalt_hash(a) == regeln.inhalt_hash(b)
    assert regeln.inhalt_hash(a) == regeln.inhalt_hash({**a, "email": None, "website": ""})
    assert regeln.inhalt_hash(a) == regeln.inhalt_hash({**a, "behandlungsschwerpunkte": [None, ""]})


@pytest.mark.parametrize("feld,wert", [
    ("persoenliches_profil", "Derzeit keine freien Plaetze."),
    ("abrechnungsarten", ["Private Krankenversicherung"]),
    ("email", "neu@praxis.de"),
    ("therapieangebot", ["Gruppentherapie"]),
])
def test_hash_aendert_sich_bei_echter_aenderung(feld, wert):
    assert regeln.inhalt_hash(_profil()) != regeln.inhalt_hash(_profil(**{feld: wert}))


def test_hash_ist_ein_sha256_hexwert():
    h = regeln.inhalt_hash({})
    assert len(h) == 64 and int(h, 16) >= 0


# ---------- zu_wenig_angaben ----------

def test_zu_wenig_angaben_bei_reinem_registereintrag():
    assert regeln.zu_wenig_angaben({"name": "A", "adresse": "x", "email": "a@b.de",
                                    "volltext": "Registereintrag", "persoenliches_profil": "   "})


@pytest.mark.parametrize("feld,wert", [
    ("abrechnungsarten", ["Gesetzliche Krankenversicherung"]),
    ("therapieangebot", ["Einzeltherapie: Erwachsene"]),
    ("behandlungsschwerpunkte", ["Depression"]),
    ("persoenliches_profil", "Ich arbeite mit Erwachsenen."),
])
def test_zu_wenig_angaben_eine_angabe_reicht(feld, wert):
    assert not regeln.zu_wenig_angaben({"name": "A", feld: wert})


# ---------- analyse_ohne_ki ----------

def test_ohne_ki_bei_kassenpraxis_ohne_eigenen_text():
    p = {"abrechnungsarten": ["Gesetzliche Krankenversicherung", "Selbstzahler"],
         "persoenliches_profil": " ", "freie_plaetze": ""}
    bewertung = regeln.analyse_ohne_ki(p)
    assert bewertung["GKV_akzeptiert"] is True
    assert bewertung["Freie_Plaetze"] == "unklar"
    assert set(bewertung) == analyse_ki.ERLAUBTE_FELDER


@pytest.mark.parametrize("p", [
    {"abrechnungsarten": ["Gesetzliche Krankenversicherung"], "persoenliches_profil": "Neue Patienten willkommen."},
    {"abrechnungsarten": ["Gesetzliche Krankenversicherung"], "freie_plaetze": "Wartezeit ca. 3 Monate"},
    {"abrechnungsarten": ["Private Krankenversicherung", "Selbstzahler"]},
    {"abrechnungsarten": []},
    {},
])
def test_ohne_ki_nur_wenn_die_ki_nichts_beitragen_kann(p):
    assert regeln.analyse_ohne_ki(p) is None


# ---------- analyse_per_regel (--ohne-ki) ----------

@pytest.mark.parametrize("text,erwartet", [
    ("Derzeit keine freien Therapieplätze.", False),
    ("Aktuell Aufnahmestopp, bitte keine Anfragen.", False),
    ("Ich nehme leider keine neuen Patienten auf.", False),
    ("Zur Zeit leider ausgebucht.", False),
    ("Die Warteliste ist geschlossen.", False),
    ("Freie Therapieplätze vorhanden!", True),
    ("Ich habe aktuell wieder freie Plätze.", True),
    ("Ich nehme gerne neue Patientinnen und Patienten auf.", True),
    ("Kurzfristige Termine verfügbar.", True),
    ("Schwerpunkt Depression und Angst.", "unklar"),
    ("Freie Plätze vorhanden ab 2027, derzeit keine freien Plätze.", False),  # Verneinung gewinnt
])
def test_regel_erkennt_freie_plaetze(text, erwartet):
    assert regeln.analyse_per_regel({"persoenliches_profil": text})["Freie_Plaetze"] == erwartet


def test_regel_liest_auch_die_angabe_freie_plaetze():
    assert regeln.analyse_per_regel({"freie_plaetze": "Aufnahmestopp"})["Freie_Plaetze"] is False


@pytest.mark.parametrize("profil,erwartet", [
    ({"abrechnungsarten": ["Gesetzliche Krankenversicherung"]}, True),
    ({"persoenliches_profil": "Gesetzlich Versicherte sind willkommen."}, True),
    ({"persoenliches_profil": "Ich habe einen Kassensitz."}, True),
    # Der Text nennt die Kasse -> schlägt die Einstufung "privat":
    ({"gkv_art": "privat", "persoenliches_profil": "Alle Kassen."}, True),
    ({"gkv_art": "privat", "abrechnungsarten": ["Selbstzahler"]}, False),
    ({"gkv_art": "kostenerstattung"}, "unklar"),
    ({}, "unklar"),
])
def test_regel_kasse(profil, erwartet):
    assert regeln.analyse_per_regel(profil)["GKV_akzeptiert"] == erwartet


def test_regel_liefert_genau_die_erlaubten_felder():
    assert set(regeln.analyse_per_regel({})) == analyse_ki.ERLAUBTE_FELDER


# ---------- muss_analysiert_werden ----------

def test_neues_profil_muss_bewertet_werden():
    assert regeln.muss_analysiert_werden(_profil(), None) == (True, "neu")


def test_unveraendertes_profil_nicht():
    p = _profil()
    assert regeln.muss_analysiert_werden(p, {"inhalt_hash": regeln.inhalt_hash(p)}) == (False, "unveraendert")


def test_geaendertes_profil_schon():
    assert regeln.muss_analysiert_werden(_profil(), {"inhalt_hash": "alt"}) == (True, "Inhalt geaendert")


def test_altes_ergebnis_ohne_hash_nur_mit_schalter():
    assert regeln.muss_analysiert_werden(_profil(), {"Notiz": "alt"}) == (False, "alt ohne Hash")
    assert regeln.muss_analysiert_werden(_profil(), {"Notiz": "alt"}, alte_neu=True) == (True, "alt ohne Hash")


# ---------- ist_reine_privatpraxis ----------

@pytest.mark.parametrize("gkv,gkv_art,erwartet", [
    (False, "privat", True),
    (False, "kassensitz", False),       # KI-Absage allein reicht nicht
    ("unklar", "privat", False),        # "unklar" reicht nicht
    (True, "privat", False),
    (False, None, False),
])
def test_privatpraxis_nur_wenn_bewertung_und_filter_sich_einig_sind(gkv, gkv_art, erwartet):
    assert regeln.ist_reine_privatpraxis({"GKV_akzeptiert": gkv}, {"gkv_art": gkv_art}) is erwartet
