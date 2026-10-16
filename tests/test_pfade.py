"""Tests für pfade.py.

Wichtig ist vor allem: Die Pfade dürfen nicht vom Arbeitsordner abhängen.
Sonst landen Ergebnisse je nach Startordner woanders, und im schlimmsten
Fall wird ein leerer Stand über echte Daten geschrieben.
"""
import importlib
import os
from pathlib import Path

import pfade


def test_pfade_haengen_nicht_vom_arbeitsordner_ab(tmp_path, monkeypatch):
    vorher = (pfade.PROJEKT_ROOT, pfade.DATA_DIR, pfade.RESULTS_RAW)
    monkeypatch.chdir(tmp_path)
    neu = importlib.reload(pfade)
    assert (neu.PROJEKT_ROOT, neu.DATA_DIR, neu.RESULTS_RAW) == vorher
    assert neu.PROJEKT_ROOT.is_absolute()


def test_ordnerstruktur():
    hier = Path(__file__).resolve().parent.parent
    assert pfade.PROJEKT_ROOT == hier
    assert pfade.BACKEND_DIR == hier / "backend"
    assert pfade.DATA_DIR == hier / "data"
    assert pfade.DATA_ARCHIV_DIR == hier / "data" / "archiv"


def test_alle_ergebnisdateien_liegen_in_data():
    dateien = [wert for name, wert in vars(pfade).items()
               if name.isupper() and isinstance(wert, Path) and wert.suffix == ".json"]
    assert len(dateien) >= 10
    for pfad in dateien:
        assert pfad.parent == pfade.DATA_DIR, pfad
        assert os.path.commonpath([str(pfad), str(pfade.PROJEKT_ROOT)]) == str(pfade.PROJEKT_ROOT)


def test_die_beiden_ausschlussdateien_sind_verschieden():
    """Zeigten beide auf dieselbe Datei, würde der nächste Analyzer-Lauf die
    von Hand gepflegten Ausschlüsse überschreiben."""
    assert pfade.AUSGESCHLOSSEN_LOG.name == "ausgeschlossen.json"
    assert pfade.MANUELL_AUSGESCHLOSSEN.name == "excluded.json"
