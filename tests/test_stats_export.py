"""Tests fuer backend/stats_export.py (reine Zaehl-Kennzahlen ohne
persoenliche Daten, siehe Modul-Docstring dort fuer den Hintergrund)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from stats_export import berechne_stats  # noqa: E402


def test_zaehlt_gesamt_richtig():
    profile = [{"gkv_art": "kassensitz"}, {"gkv_art": "privat"}, {"gkv_art": None}]
    stats = berechne_stats(profile)
    assert stats["gesamt"] == 3


def test_zaehlt_kassensitz_und_kostenerstattung_getrennt():
    profile = [
        {"gkv_art": "kassensitz"},
        {"gkv_art": "kassensitz"},
        {"gkv_art": "kostenerstattung"},
        {"gkv_art": "privat"},
    ]
    stats = berechne_stats(profile)
    assert stats["kassensitz"] == 2
    assert stats["kostenerstattung"] == 1


def test_zaehlt_gkv_akzeptiert_nur_bei_true():
    profile = [
        {"GKV_akzeptiert": True},
        {"GKV_akzeptiert": False},
        {"GKV_akzeptiert": "unklar"},
    ]
    stats = berechne_stats(profile)
    assert stats["gkv_akzeptiert"] == 1


def test_zaehlt_freie_plaetze_nur_bei_true():
    profile = [
        {"Freie_Plaetze": True},
        {"Freie_Plaetze": "unklar"},
        {"Freie_Plaetze": False},
    ]
    stats = berechne_stats(profile)
    assert stats["freie_plaetze"] == 1


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
