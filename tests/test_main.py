"""Tests für main.py, den Startbefehl der Pipeline.

Scraper und Analyzer werden durch kleine Attrappen ersetzt, die nur
mitschreiben, dass sie aufgerufen wurden. So lässt sich prüfen, welcher
Schalter welche Schritte auslöst, ohne Browser, Netz oder API-Schlüssel.
"""
import json
import sys
import types

import pytest


import main
import pfade


@pytest.fixture
def ablauf(monkeypatch):
    protokoll = []
    scraper = types.ModuleType("scraper")

    async def scraper_main():
        protokoll.append("scraper")

    async def enrich_emails():
        protokoll.append("emails")

    scraper.main = scraper_main
    email_suche = types.ModuleType("email_suche")
    email_suche.ergaenze_emails = enrich_emails
    monkeypatch.setitem(sys.modules, "email_suche", email_suche)
    analyzer = types.ModuleType("analyzer")
    analyzer.main = lambda: protokoll.append("analyzer")
    monkeypatch.setitem(sys.modules, "scraper", scraper)
    monkeypatch.setitem(sys.modules, "analyzer", analyzer)
    monkeypatch.setattr(main, "zeige_statistik", lambda: protokoll.append("stats"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def starte(*schalter):
        main.main(list(schalter))
        return protokoll
    starte.protokoll = protokoll
    return starte


def test_kompletter_lauf_scrapt_analysiert_und_zeigt_zahlen(ablauf):
    assert ablauf() == ["scraper", "analyzer", "stats"]


def test_nur_analyse(ablauf):
    assert ablauf("--skip-scraper") == ["analyzer", "stats"]


def test_nur_scrapen_braucht_keinen_schluessel(ablauf, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert ablauf("--skip-analyzer") == ["scraper", "stats"]


def test_nur_emails(ablauf):
    assert ablauf("--only-emails") == ["emails"]


def test_nur_statistik(ablauf):
    assert ablauf("--stats") == ["stats"]


@pytest.mark.parametrize("wert", [None, "", "platzhalter"])
def test_ohne_schluessel_bricht_vor_dem_scraper_ab(ablauf, monkeypatch, wert):
    """Der Scraper läuft stundenlang. Fehlt der Schlüssel, muss VORHER
    abgebrochen werden, nicht erst danach im Analyzer."""
    if wert is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY")
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", wert)
    with pytest.raises(SystemExit) as fehler:
        ablauf()
    assert fehler.value.code == 1
    assert ablauf.protokoll == []   # weder Scraper noch Analyzer gestartet


def test_api_key_vorhanden(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-echt")
    assert main.api_key_vorhanden() is True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platzhalter")
    assert main.api_key_vorhanden() is False
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert main.api_key_vorhanden() is False


def test_zahlen_zum_datenstand(tmp_path, monkeypatch):
    roh = tmp_path / "raw.json"
    analysiert = tmp_path / "analysiert.json"
    roh.write_text(json.dumps([{}, {}, {}]), encoding="utf-8")
    analysiert.write_text(json.dumps([{"email": "a@x.de"}, {"email": ""}]), encoding="utf-8")
    monkeypatch.setattr(pfade, "RESULTS_RAW", roh)
    monkeypatch.setattr(pfade, "RESULTS_ANALYZED", analysiert)
    assert main.zahlen_zum_datenstand() == {
        "gescrapt": 3, "in_der_app": 2, "mit_email": 1, "ohne_email": 1}


def test_zahlen_bei_fehlenden_dateien_sind_null(tmp_path, monkeypatch):
    monkeypatch.setattr(pfade, "RESULTS_RAW", tmp_path / "fehlt.json")
    monkeypatch.setattr(pfade, "RESULTS_ANALYZED", tmp_path / "fehlt-auch.json")
    assert main.zahlen_zum_datenstand() == {
        "gescrapt": 0, "in_der_app": 0, "mit_email": 0, "ohne_email": 0}
