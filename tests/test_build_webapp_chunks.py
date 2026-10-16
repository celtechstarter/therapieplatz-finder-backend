"""Tests fuer build_webapp_chunks.py -- das Skript, das aus
results_analyzed.json die Webapp-Datenchunks baut (siehe Modul-Docstring
dort fuer den vollen Kontext/die Herleitung der einzelnen Felder).

Kein Test geht ins Netz: die Entfernung kommt seit 4.10.2026 aus der lokalen
PLZ-Tabelle (km_aus_plz), main() laeuft komplett in einem Temp-Ordner (siehe
Abschnitt "main()" unten)."""
import sys


import build_webapp_chunks as b


# ---------- extrahiere_anrede() / extrahiere_therapieform() ----------

def test_extrahiere_anrede_findet_standardmuster():
    text = "Guten Tag Frau Dr. Müller,\n\nich möchte mich bei Ihnen melden..."
    assert b.extrahiere_anrede(text) == "Frau Dr. Müller"


def test_extrahiere_anrede_leer_wenn_muster_fehlt():
    assert b.extrahiere_anrede("Sehr geehrte Damen und Herren, ...") == ""


def test_extrahiere_anrede_leer_bei_none():
    assert b.extrahiere_anrede(None) == ""


def test_extrahiere_therapieform_findet_standardmuster():
    text = "...Falls Sie tiefenpsychologisch fundierte Psychotherapie anbieten, wäre das..."
    assert b.extrahiere_therapieform(text) == "tiefenpsychologisch fundierte Psychotherapie"


def test_extrahiere_therapieform_default_wenn_muster_fehlt():
    assert b.extrahiere_therapieform("Ein Text ohne das Muster.") == "Einzeltherapie"


def test_extrahiere_therapieform_default_bei_none():
    assert b.extrahiere_therapieform(None) == "Einzeltherapie"


# ---------- haversine_km() ----------

def test_haversine_km_gleicher_punkt_ist_null():
    assert b.haversine_km(51.5, 7.5, 51.5, 7.5) == 0.0


def test_haversine_km_symmetrisch():
    a = b.haversine_km(51.5371637, 7.5989724, 51.4996817, 7.5248620)
    c = b.haversine_km(51.4996817, 7.5248620, 51.5371637, 7.5989724)
    assert abs(a - c) < 1e-9


def test_haversine_km_bekannte_distanz_plausibel():
    # Dortmund-PLZ 44319 zu einer realen Adresse (Testweg 13, 44269
    # Dortmund) -- bekannter Live-Wert ist 6.6 km (siehe build_webapp_chunks.py
    # Modul-Docstring, dort mit 4 Adressen gegen Nominatim verifiziert).
    dist = b.haversine_km(51.5371637, 7.5989724, 51.4996817, 7.5248620)
    assert abs(dist - 6.6) < 0.15


# ---------- naechste_ids() ----------

def test_naechste_ids_bei_leerer_liste_startet_bei_eins():
    assert b.naechste_ids([], 3) == [1, 2, 3]


def test_naechste_ids_setzt_nach_maximum_fort():
    assert b.naechste_ids([273, 475, 42], 2) == [476, 477]


def test_naechste_ids_null_neue_gibt_leere_liste():
    assert b.naechste_ids([5], 0) == []


# ---------- bevorzuge_frisch() ----------

def test_bevorzuge_frisch_nimmt_nicht_leeren_frischen_wert():
    assert b.bevorzuge_frisch("neu@example.de", "alt@example.de") == "neu@example.de"


def test_bevorzuge_frisch_faellt_bei_leerem_string_zurueck():
    assert b.bevorzuge_frisch("", "alt@example.de") == "alt@example.de"


def test_bevorzuge_frisch_faellt_bei_leerer_liste_zurueck():
    assert b.bevorzuge_frisch([], ["Verhaltenstherapie"]) == ["Verhaltenstherapie"]


def test_bevorzuge_frisch_faellt_bei_none_zurueck():
    assert b.bevorzuge_frisch(None, "alt") == "alt"


def test_bevorzuge_frisch_beide_leer_bleibt_leer():
    assert b.bevorzuge_frisch("", "") == ""


# ---------- bevorzuge_frisch_email() ----------

def test_bevorzuge_frisch_email_ohne_marker_verhaelt_sich_wie_bevorzuge_frisch():
    assert b.bevorzuge_frisch_email({"email": "neu@beispiel.de"}, "alt@beispiel.de") == "neu@beispiel.de"
    assert b.bevorzuge_frisch_email({"email": ""}, "alt@beispiel.de") == "alt@beispiel.de"


def test_bevorzuge_frisch_email_regression_absichtliche_korrektur_faellt_nicht_zurueck():
    """Regression (26.8.2026, Marcel gemeldet): eine absichtlich auf leer korrigierte Email (falsch
    zugeordnet durch die Bing-Fallback-Suche, siehe scraper.py) darf beim
    Rebuild NICHT durch bevorzuge_frisch() wieder auf den alten, falschen
    Live-Wert zurueckfallen -- genau das ist vorher passiert."""
    analysiert = {
        "email": "",
        "email_entfernt_grund": "Falsch zugeordnete Email aus automatischer Bing-Recherche entfernt (war: falsch@fremde-seite.example), 26.8.2026",
    }
    assert b.bevorzuge_frisch_email(analysiert, "falsch@fremde-seite.example") == ""


def test_bevorzuge_frisch_email_marker_aber_frischer_wert_gesetzt():
    """Falls email UND email_entfernt_grund gesetzt sind (z.B. neue,
    korrekte Email nachrecherchiert), gewinnt der frische, nicht-leere Wert."""
    analysiert = {"email": "korrekt@beispiel.de", "email_entfernt_grund": "alte Recherche war falsch"}
    assert b.bevorzuge_frisch_email(analysiert, "falsch@beispiel.de") == "korrekt@beispiel.de"


# ---------- baue_datensatz() ----------

def _analysiert(**overrides):
    d = {
        "profil_url": "https://beispiel-quelle.de/psychotherapeuten/neu/mitglied/",
        "name": "Neu Person",
        "adresse": "Musterstr. 1, 44135 Dortmund",
        "telefon": "0231 123",
        "email": "neu@beispiel.de",
        "website": "",
        "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
        "behandlungsschwerpunkte": ["ADHS"],
        "Freie_Plaetze": "unklar",
        "scraped_at": "2026-08-20T10:00:00",
        "Email_generiert": "Guten Tag Frau Person,\n\nFalls Sie Verhaltenstherapie anbieten, ...",
    }
    d.update(overrides)
    return d


def _live(**overrides):
    d = {
        "id": 273,
        "profil_url": "https://www.therapie.de/profil/bestehend/",
        "name": "Alt Person",
        "adresse": "Altstr. 5, 44135 Dortmund",
        "telefon": "0231 999",
        "email": "alt@beispiel.de",
        "website": "",
        "abrechnung": ["Gesetzliche Krankenversicherung"],
        "schwerpunkte": ["Depression"],
        "freie_plaetze": True,
        "scraped_at": "2020-01-01T00:00:00",
        "telefonsprechstunde": [{"tag": "Montag", "von": "10:00", "bis": "11:00"}],
        "km": 3.4,
        "anrede": "Frau Alt",
        "therapieform": "tiefenpsychologisch fundierte Psychotherapie",
        "aufnahmestopp": False,
        "aufnahmestopp_zitat": "",
    }
    d.update(overrides)
    return d


def test_baue_datensatz_neuer_eintrag_extrahiert_anrede_und_therapieform():
    d = b.baue_datensatz(_analysiert(), live=None)
    assert d["anrede"] == "Frau Person"
    assert d["therapieform"] == "Verhaltenstherapie"
    assert d["aufnahmestopp"] is False
    assert d["id"] is None  # wird erst zentral in main() vergeben
    assert d["km"] is None  # wird erst zentral in main() per Geocoding gesetzt


def test_baue_datensatz_neuer_eintrag_uebernimmt_rohfelder():
    d = b.baue_datensatz(_analysiert())
    assert d["name"] == "Neu Person"
    assert d["email"] == "neu@beispiel.de"
    assert d["abrechnung"] == ["Gesetzliche Krankenversicherung"]
    assert d["schwerpunkte"] == ["ADHS"]
    assert d["freie_plaetze"] == "unklar"


def test_baue_datensatz_matched_eintrag_behaelt_id_km_anrede_therapieform():
    """Kernverhalten: fuer bereits live vorhandene Eintraege werden id/km/
    anrede/therapieform NICHT neu berechnet (siehe Modul-Docstring,
    Sicherheitsnetz gegen id-Verschiebung)."""
    live = _live()
    d = b.baue_datensatz(_analysiert(profil_url=live["profil_url"]), live=live)
    assert d["id"] == 273
    assert d["km"] == 3.4
    assert d["anrede"] == "Frau Alt"
    assert d["therapieform"] == "tiefenpsychologisch fundierte Psychotherapie"


def test_baue_datensatz_matched_eintrag_aktualisiert_rohfelder():
    live = _live()
    frisch = _analysiert(profil_url=live["profil_url"], email="neue-email@beispiel.de")
    d = b.baue_datensatz(frisch, live=live)
    assert d["email"] == "neue-email@beispiel.de"


def test_baue_datensatz_leeres_frisches_feld_faellt_auf_live_zurueck_regression():
    """Regression: der aktuelle Scraper liefert kein telefonsprechstunde mehr
    (siehe Modul-Docstring) -- ein Rebuild darf das Feld bei bereits live
    vorhandenen Eintraegen trotzdem nicht loeschen."""
    live = _live()
    frisch = _analysiert(profil_url=live["profil_url"])
    frisch.pop("telefonsprechstunde", None)  # results_analyzed.json hat das Feld aktuell nie
    d = b.baue_datensatz(frisch, live=live)
    assert d["telefonsprechstunde"] == [{"tag": "Montag", "von": "10:00", "bis": "11:00"}]


def test_baue_datensatz_freie_plaetze_false_wird_nicht_zu_unklar_regression():
    """Regression: False ist ein gueltiger, informativer Wert (keine freien
    Plaetze) -- darf nicht mit einem 'leeren Wert' verwechselt und durch den
    unklar-Fallback ueberschrieben werden."""
    live = _live(freie_plaetze="unklar")
    frisch = _analysiert(profil_url=live["profil_url"], Freie_Plaetze=False)
    d = b.baue_datensatz(frisch, live=live)
    assert d["freie_plaetze"] is False


def test_baue_datensatz_absichtlich_geleerte_email_bleibt_leer_regression():
    """End-to-end-Regression ueber baue_datensatz() (nicht nur die isolierte
    Hilfsfunktion): eine mit email_entfernt_grund markierte, absichtlich
    geleerte Email darf beim Rebuild nicht auf den alten Live-Wert
    zurueckfallen (siehe bevorzuge_frisch_email())."""
    live = _live(email="falsch@fremde-seite.example")
    frisch = _analysiert(
        profil_url=live["profil_url"],
        email="",
        email_entfernt_grund="Falsch zugeordnete Email aus automatischer Bing-Recherche entfernt, 26.8.2026",
    )
    d = b.baue_datensatz(frisch, live=live)
    assert d["email"] == ""


def test_baue_datensatz_ohne_email_generiert_neuer_eintrag_kein_crash():
    d = b.baue_datensatz(_analysiert(Email_generiert=""), live=None)
    assert d["anrede"] == ""
    assert d["therapieform"] == "Einzeltherapie"


# ---------- teile_in_chunks() ----------

def test_teile_in_chunks_ergibt_exakte_anzahl_stuecke():
    stuecke = b.teile_in_chunks("x" * 1000, 48)
    assert len(stuecke) == 48


def test_teile_in_chunks_ergebnis_fuegt_sich_wieder_zusammen():
    text = "abcdefghijklmnopqrstuvwxyz" * 37  # nicht durch 48 teilbar
    stuecke = b.teile_in_chunks(text, 48)
    assert "".join(stuecke) == text


def test_teile_in_chunks_kein_stueck_ist_stark_ungleich():
    text = "x" * 4800
    stuecke = b.teile_in_chunks(text, 48)
    assert all(len(s) == 100 for s in stuecke)


# ---------- aufnahmestopp: frisch statt blind aus dem Live-Stand (Review #11) ----------

def test_aufnahmestopp_kommt_frisch_aus_dem_rohprofil_auch_bei_live_eintrag():
    """Frueher wurde aufnahmestopp fuer bestehende Eintraege blind aus dem
    Live-Stand uebernommen -- ein neu erkannter Aufnahmestopp kam nie an."""
    live = _live(aufnahmestopp=False)
    frisch = _analysiert(profil_url=live["profil_url"], aufnahmestopp=True,
                         aufnahmestopp_zitat="Derzeit Aufnahmestopp.")
    d = b.baue_datensatz(frisch, live=live)
    assert d["aufnahmestopp"] is True
    assert d["aufnahmestopp_zitat"] == "Derzeit Aufnahmestopp."
    assert "aufnahmestopp_quelle" not in d
    assert d["id"] == 273 and d["anrede"] == "Frau Alt"  # IDs weiter aus live


def test_aufgehobener_aufnahmestopp_wird_nicht_aus_live_uebernommen():
    live = _live(aufnahmestopp=True, aufnahmestopp_zitat="Aufnahmestopp bis 2025.")
    frisch = _analysiert(profil_url=live["profil_url"], aufnahmestopp=False, aufnahmestopp_zitat="")
    d = b.baue_datensatz(frisch, live=live)
    assert d["aufnahmestopp"] is False
    assert d["aufnahmestopp_zitat"] == ""


def test_fehlendes_aufnahmestopp_feld_ergibt_false_statt_live_wert():
    live = _live(aufnahmestopp=True, aufnahmestopp_zitat="alt")
    d = b.baue_datensatz(_analysiert(profil_url=live["profil_url"]), live=live)
    assert d["aufnahmestopp"] is False
    assert d["aufnahmestopp_zitat"] == ""


def test_manuell_gesetzter_aufnahmestopp_im_live_stand_bleibt_erhalten():
    live = _live(aufnahmestopp=True, aufnahmestopp_zitat="Telefonisch bestaetigt",
                 aufnahmestopp_quelle="manuell")
    frisch = _analysiert(profil_url=live["profil_url"], aufnahmestopp=False)
    d = b.baue_datensatz(frisch, live=live)
    assert d["aufnahmestopp"] is True
    assert d["aufnahmestopp_zitat"] == "Telefonisch bestaetigt"
    assert d["aufnahmestopp_quelle"] == "manuell"


def test_manuelle_korrektur_auf_false_im_live_stand_bleibt_erhalten():
    live = _live(aufnahmestopp=False, aufnahmestopp_quelle="manuell")
    frisch = _analysiert(profil_url=live["profil_url"], aufnahmestopp=True,
                         aufnahmestopp_zitat="Aufnahmestopp (veralteter Profiltext)")
    d = b.baue_datensatz(frisch, live=live)
    assert d["aufnahmestopp"] is False
    assert d["aufnahmestopp_zitat"] == ""
    assert d["aufnahmestopp_quelle"] == "manuell"


def test_manuelle_korrektur_in_results_analyzed_wird_uebernommen():
    frisch = _analysiert(aufnahmestopp=True, aufnahmestopp_zitat="per Mail bestaetigt",
                         aufnahmestopp_quelle="manuell")
    d = b.baue_datensatz(frisch, live=None)
    assert d["aufnahmestopp"] is True
    assert d["aufnahmestopp_quelle"] == "manuell"


def test_neuer_eintrag_uebernimmt_erkannten_aufnahmestopp():
    d = b.baue_datensatz(_analysiert(aufnahmestopp=True, aufnahmestopp_zitat="Z"), live=None)
    assert d["aufnahmestopp"] is True
    assert d["aufnahmestopp_zitat"] == "Z"


def test_kartenlink_wird_nie_als_website_ausgeliefert_auch_nicht_aus_live_stand():
    """Befund 30.9.2026: 17 Live-Eintraege zeigten einen Google-Maps-Link
    als "Website". bevorzuge_frisch() haette den Kartenlink aus dem
    Live-Stand wieder eingesetzt, obwohl das Rohprofil schon bereinigt war."""
    import build_webapp_chunks as b
    live = {"id": 1, "km": 1.0, "website": "https://www.google.com/maps/search/?api=1&query=1,2"}
    d = b.baue_datensatz({"profil_url": "u", "website": ""}, live)
    assert d["website"] == ""
    d = b.baue_datensatz({"profil_url": "u", "website": "https://praxis.de"}, live)
    assert d["website"] == "https://praxis.de"
    live_echt = dict(live, website="https://alte-praxis.de")
    assert b.baue_datensatz({"profil_url": "u", "website": ""}, live_echt)["website"] == "https://alte-praxis.de"


# ---------- main(): kompletter Lauf in einem Temp-Ordner ----------
# Der wichtigste Ablauf des Skripts: aus results_analyzed.json + dem
# aktuellen Live-Stand die neuen Chunks bauen. Geprueft wird, was fuer die
# Webapp zaehlt: bestehende ids bleiben stabil, Neuzugaenge bekommen
# fortlaufende ids, Weggefallene fliegen raus, die Chunks lassen sich exakt
# zurueck entpacken und die Pruefsummen passen.

import base64
import gzip
import hashlib
import json

import pytest


@pytest.fixture
def temp_pfade(tmp_path, monkeypatch):
    chunks = tmp_path / "data-chunks"
    monkeypatch.setattr(b, "CHUNKS_DIR", chunks)
    monkeypatch.setattr(b.pfade, "RESULTS_ANALYZED", tmp_path / "results_analyzed.json")
    monkeypatch.setattr(b.pfade, "GEOCODE_CACHE", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(b.pfade, "DATA_DIR", tmp_path)
    tabelle = tmp_path / "plz.json"
    tabelle.write_text(json.dumps({"44135": [51.51, 7.47]}), encoding="utf-8")
    monkeypatch.setattr(b, "PLZ_TABELLE", tabelle)
    return tmp_path


def _schreibe_live(chunks_dir, liste, anzahl=3):
    b64 = base64.b64encode(gzip.compress(json.dumps(liste).encode())).decode()
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for i, stueck in enumerate(b.teile_in_chunks(b64, anzahl)):
        (chunks_dir / f"chunk{i:03d}.b64").write_text(stueck, encoding="utf-8")


def test_main_ohne_results_analyzed_bricht_ab(temp_pfade, capsys):
    b.main()
    assert "Abbruch" in capsys.readouterr().out
    assert not (temp_pfade / "data-chunks").exists()


def test_lade_live_daten_ohne_chunks_ist_leer(temp_pfade):
    assert b.lade_live_daten() == []


def test_main_kompletter_lauf(temp_pfade, monkeypatch):
    bleibt = _live(id=5, profil_url="https://quelle.de/bleibt", km=3.4)
    faellt_weg = _live(id=9, profil_url="https://quelle.de/weg")
    _schreibe_live(temp_pfade / "data-chunks", [bleibt, faellt_weg])

    analysiert = [
        _analysiert(profil_url="https://quelle.de/bleibt", telefon="0231 neu"),
        _analysiert(profil_url="https://quelle.de/neu1", adresse="A-Str. 1, 44135 Dortmund"),
        _analysiert(profil_url="https://quelle.de/neu2", adresse="B-Str. 2, 44135 Dortmund"),
    ]
    (temp_pfade / "results_analyzed.json").write_text(json.dumps(analysiert), encoding="utf-8")
    # Eine Adresse liegt schon im (adressgenauen) Cache: der Wert hat Vorrang.
    (temp_pfade / "geocode_cache.json").write_text(json.dumps({"A-Str. 1, 44135 Dortmund": 1.5}))

    b.main()

    ergebnis = b.lade_live_daten()
    nach_url = {d["profil_url"]: d for d in ergebnis}
    assert set(nach_url) == {"https://quelle.de/bleibt", "https://quelle.de/neu1", "https://quelle.de/neu2"}
    assert nach_url["https://quelle.de/bleibt"]["id"] == 5           # stabil
    assert nach_url["https://quelle.de/bleibt"]["telefon"] == "0231 neu"
    assert nach_url["https://quelle.de/bleibt"]["km"] == 3.4
    assert [nach_url[u]["id"] for u in ("https://quelle.de/neu1", "https://quelle.de/neu2")] == [6, 7]
    assert nach_url["https://quelle.de/neu1"]["km"] == 1.5           # aus Cache
    assert nach_url["https://quelle.de/neu2"]["km"] == b.km_aus_plz("B-Str. 2, 44135 Dortmund",
                                                                    {"44135": [51.51, 7.47]})

    chunk_dateien = sorted((temp_pfade / "data-chunks").glob("chunk*.b64"))
    assert len(chunk_dateien) == b.ANZAHL_CHUNKS
    hashes = json.loads((temp_pfade / "webapp_chunk_hashes.json").read_text())
    stuecke = [p.read_text(encoding="utf-8") for p in chunk_dateien]
    assert hashes["chunks"] == [hashlib.sha256(s.encode()).hexdigest() for s in stuecke]
    assert hashes["gesamt"] == hashlib.sha256("".join(stuecke).encode()).hexdigest()


# ---------- km_aus_plz(): Entfernung ueber die PLZ-Tabelle ----------

def test_km_aus_plz_referenz_ist_null_und_fremde_plz_positiv():
    tabelle = {"44319": [b.REF_LAT, b.REF_LON], "45127": [51.45, 7.01]}
    assert b.km_aus_plz("Weg 1, 44319 Dortmund", tabelle) == 0.0
    assert 40 < b.km_aus_plz("Weg 1, 45127 Essen", tabelle) < 43


def test_km_aus_plz_nimmt_die_plz_vor_dem_ort_nicht_die_hausnummer():
    tabelle = {"45127": [51.45, 7.01], "12345": [53.0, 13.0]}
    assert b.km_aus_plz("Postfach 12345, 45127 Essen", tabelle) == b.km_aus_plz("45127 Essen", tabelle)


def test_km_aus_plz_ohne_bekannte_plz_ist_none():
    assert b.km_aus_plz("Musterstr. 1, Dortmund", {}) is None
    assert b.km_aus_plz("", {"44319": [51.5, 7.6]}) is None
    assert b.km_aus_plz("Weg 1, 99999 Nirgendwo", {"44319": [51.5, 7.6]}) is None
