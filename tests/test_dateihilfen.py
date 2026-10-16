"""Tests fuer dateihilfen.py: das atomare Schreiben, das den Totalverlust
der Scraping-/Analyse-Ergebnisse bei einem Absturz mitten im Schreiben
verhindern soll (Audit-Befund H1)."""
import json
from pathlib import Path


import dateihilfen


def test_atomar_schreiben_und_lesen_roundtrip(tmp_path):
    ziel = tmp_path / "ergebnis.json"
    daten = [{"name": "Ärztin Müller", "id": 1}]
    dateihilfen.json_atomar_schreiben(ziel, daten)
    assert json.loads(ziel.read_text(encoding="utf-8")) == daten


def test_atomar_schreiben_hinterlaesst_keine_tmp_datei(tmp_path):
    ziel = tmp_path / "ergebnis.json"
    dateihilfen.json_atomar_schreiben(ziel, {"a": 1})
    reste = list(tmp_path.glob("*.tmp"))
    assert reste == []


def test_atomar_schreiben_ueberschreibt_bestehende_datei_vollstaendig(tmp_path):
    ziel = tmp_path / "ergebnis.json"
    dateihilfen.json_atomar_schreiben(ziel, {"a": 1, "b": 2, "c": 3})
    dateihilfen.json_atomar_schreiben(ziel, {"a": 1})  # kuerzere Daten
    assert json.loads(ziel.read_text(encoding="utf-8")) == {"a": 1}


def test_atomar_schreiben_erstellt_fehlendes_verzeichnis(tmp_path):
    ziel = tmp_path / "unter" / "ordner" / "ergebnis.json"
    dateihilfen.json_atomar_schreiben(ziel, {"x": 1})
    assert ziel.exists()


def test_sicher_laden_fehlende_datei_gibt_fallback(tmp_path):
    assert dateihilfen.json_sicher_laden(tmp_path / "gibt-es-nicht.json", []) == []
    assert dateihilfen.json_sicher_laden(tmp_path / "gibt-es-nicht.json", {"leer": True}) == {"leer": True}


def test_sicher_laden_kaputte_datei_gibt_fallback_statt_absturz(tmp_path):
    """Regression zum Audit-Befund H1: eine mitten im Schreiben abgebrochene
    JSON-Datei durfte den ganzen Lauf nicht mit einer unbehandelten
    JSONDecodeError abstuerzen lassen."""
    kaputt = tmp_path / "kaputt.json"
    kaputt.write_text('[{"name": "Halb geschrie', encoding="utf-8")
    assert dateihilfen.json_sicher_laden(kaputt, []) == []


def test_sicher_laden_intakte_datei():
    tmp = Path(__file__).resolve().parent.parent
    ziel = tmp / "_test_sicher_laden_temp.json"
    dateihilfen.json_atomar_schreiben(ziel, [1, 2, 3])
    try:
        assert dateihilfen.json_sicher_laden(ziel, []) == [1, 2, 3]
    finally:
        ziel.unlink(missing_ok=True)


def test_umlaute_bleiben_in_der_datei_lesbar(tmp_path):
    """Die Dateien werden auch von Hand angesehen: "Müller", nicht "M\\u00fcller"."""
    ziel = tmp_path / "ergebnis.json"
    dateihilfen.json_atomar_schreiben(ziel, {"name": "Müller"})
    assert "Müller" in ziel.read_text(encoding="utf-8")
