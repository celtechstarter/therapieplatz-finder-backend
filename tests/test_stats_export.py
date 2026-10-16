"""Tests fuer backend/stats_export.py (reine Zaehl-Kennzahlen ohne
persoenliche Daten, siehe Modul-Docstring dort fuer den Hintergrund)."""


from stats_export import berechne_stats


def test_zaehlt_gesamt_richtig():
    profile = [{"gkv_art": "kassensitz"}, {"gkv_art": "privat"}, {"gkv_art": None}]
    stats = berechne_stats(profile)
    assert stats["gesamt"] == 3


def test_zaehlt_kassensitz_und_kostenerstattung_getrennt():
    profile = [
        {"gkv_art": "kassensitz"},
        {"gkv_art": "kassensitz"},
        {"gkv_art": "kassensitz"},
        {"gkv_art": "kostenerstattung"},
        {"gkv_art": "privat"},
    ]
    stats = berechne_stats(profile)
    assert stats["kassensitz"] == 3
    assert stats["kostenerstattung"] == 1


def test_zaehlt_gkv_akzeptiert_nur_bei_true():
    profile = [
        {"GKV_akzeptiert": True},
        {"GKV_akzeptiert": True},
        {"GKV_akzeptiert": False},
        {"GKV_akzeptiert": "unklar"},
    ]
    stats = berechne_stats(profile)
    assert stats["gkv_akzeptiert"] == 2


def test_zaehlt_freie_plaetze_nur_bei_true():
    # Bewusst ungleich viele True/False, sonst fiele ein Vertauschen nicht auf.
    profile = [
        {"Freie_Plaetze": True},
        {"Freie_Plaetze": True},
        {"Freie_Plaetze": "unklar"},
        {"Freie_Plaetze": False},
    ]
    stats = berechne_stats(profile)
    assert stats["freie_plaetze"] == 2


def test_zaehlt_mit_email():
    profile = [{"email": "a@b.de"}, {"email": ""}, {}]
    stats = berechne_stats(profile)
    assert stats["mit_email"] == 1


def test_ergebnis_enthaelt_keine_persoenlichen_felder():
    profile = [{"name": "Anna Beispiel", "email": "a@b.de", "gkv_art": "kassensitz"}]
    stats = berechne_stats(profile)
    verbotene_felder = {"name", "email", "adresse", "telefon", "profil_url"}
    assert verbotene_felder.isdisjoint(stats.keys())


def test_leere_liste_gibt_nullen():
    stats = berechne_stats([])
    assert stats["gesamt"] == 0
    assert stats["kassensitz"] == 0
    assert stats["freie_plaetze"] == 0


def test_main_schreibt_die_zahlen_in_die_ausgabedatei(tmp_path, monkeypatch):
    import json
    import stats_export
    quelle, ziel = tmp_path / "analysiert.json", tmp_path / "stats.json"
    quelle.write_text(json.dumps([{"gkv_art": "kassensitz", "email": "a@b.de"}, {}]), encoding="utf-8")
    monkeypatch.setattr(stats_export, "RESULTS_ANALYZED", quelle)
    monkeypatch.setattr(stats_export, "STATS_WOECHENTLICH", ziel)
    stats_export.main()
    stats = json.loads(ziel.read_text(encoding="utf-8"))
    assert (stats["gesamt"], stats["kassensitz"], stats["mit_email"]) == (2, 1, 1)


def test_main_ohne_daten_schreibt_nichts(tmp_path, monkeypatch):
    import stats_export
    monkeypatch.setattr(stats_export, "RESULTS_ANALYZED", tmp_path / "fehlt.json")
    monkeypatch.setattr(stats_export, "STATS_WOECHENTLICH", tmp_path / "stats.json")
    stats_export.main()
    assert not (tmp_path / "stats.json").exists()
