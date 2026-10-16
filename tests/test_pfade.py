"""Tests fuer pfade.py -- die zentralen Pfad-Konstanten.

Warum das getestet wird: vor dem pfade.py-Refactor hatte jedes Skript seine
eigenen CWD-relativen Dateinamen ("results_raw.json", ...). Startet man ein
Skript aus einem anderen Verzeichnis, landen neue Dateien dann am falschen
Ort oder bestehende werden nicht gefunden -- im schlimmsten Fall wird ein
leerer Stand ueber echte Ergebnisse geschrieben. Alles hier muss deshalb
ausschliesslich von Path(__file__) abhaengen, nie vom Arbeitsverzeichnis.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pfade


def test_projekt_root_und_data_dir_sind_absolut():
    assert pfade.PROJEKT_ROOT.is_absolute()
    assert pfade.DATA_DIR.is_absolute()
    assert pfade.BACKEND_DIR.is_absolute()


def test_pfade_haengen_nicht_am_arbeitsverzeichnis(tmp_path, monkeypatch):
    """Kern des Tests: aus einem beliebigen anderen Verzeichnis neu geladen
    muessen exakt dieselben Pfade herauskommen."""
    import importlib
    vorher = (pfade.PROJEKT_ROOT, pfade.DATA_DIR, pfade.RESULTS_RAW,
              pfade.CREDENTIALS_FILE, pfade.TOKEN_FILE)
    monkeypatch.chdir(tmp_path)
    neu = importlib.reload(pfade)
    nachher = (neu.PROJEKT_ROOT, neu.DATA_DIR, neu.RESULTS_RAW,
               neu.CREDENTIALS_FILE, neu.TOKEN_FILE)
    assert vorher == nachher


def test_struktur_stimmt_mit_dem_readme_ueberein():
    assert pfade.BACKEND_DIR.name == "backend"
    assert pfade.BACKEND_DIR.parent == pfade.PROJEKT_ROOT
    assert pfade.DATA_DIR == pfade.PROJEKT_ROOT / "data"
    assert pfade.DATA_ARCHIV_DIR == pfade.DATA_DIR / "archiv"
    assert pfade.FRONTEND_DIR == pfade.BACKEND_DIR / "frontend"
    # Secrets liegen im Projekt-Root, nicht in data/ (siehe .gitignore):
    assert pfade.CREDENTIALS_FILE.parent == pfade.PROJEKT_ROOT
    assert pfade.TOKEN_FILE.parent == pfade.PROJEKT_ROOT


def test_alle_ergebnisdateien_liegen_in_data():
    for pfad in (pfade.RESULTS_RAW, pfade.RESULTS_ANALYZED, pfade.RESULTS_QUELLE_A_RAW,
                 pfade.AUSGESCHLOSSEN_LOG, pfade.MANUELL_AUSGESCHLOSSEN, pfade.SENT_LOG):
        assert pfad.parent == pfade.DATA_DIR


def test_ausschlussdateien_sind_nicht_dieselbe_datei():
    """Die beiden 'Ausschluss'-Dateien sind leicht zu verwechseln, haben aber
    voellig unterschiedliche Bedeutung:
      - AUSGESCHLOSSEN_LOG (ausgeschlossen.json): AUSGABE des Filterlaufs,
        wird bei jedem Lauf komplett neu geschrieben.
      - MANUELL_AUSGESCHLOSSEN (excluded.json): die vom Nutzer per
        'Ausblenden' gepflegte Liste, muss dauerhaft erhalten bleiben.
    Zeigten beide auf dieselbe Datei, wuerde der naechste Analyzer-Lauf die
    manuellen Ausblendungen ueberschreiben."""
    assert pfade.AUSGESCHLOSSEN_LOG != pfade.MANUELL_AUSGESCHLOSSEN
    assert pfade.AUSGESCHLOSSEN_LOG.name == "ausgeschlossen.json"
    assert pfade.MANUELL_AUSGESCHLOSSEN.name == "excluded.json"


def test_pfade_liegen_tatsaechlich_im_projektordner():
    hier = Path(__file__).resolve().parent.parent
    assert pfade.PROJEKT_ROOT == hier
    assert os.path.commonpath([str(pfade.DATA_DIR), str(hier)]) == str(hier)
