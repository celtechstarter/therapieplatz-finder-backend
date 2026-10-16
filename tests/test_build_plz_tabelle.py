"""Tests fuer backend/build_plz_tabelle.py (PLZ-Koordinaten fuer die Webapp)."""


import build_plz_tabelle as b

ZEILEN = [
    "DE\t44319\tDortmund\tNordrhein-Westfalen\tNW\t\t\t\t\t51.52\t7.59\t\n",
    "DE\t44319\tDortmund Wickede\tNordrhein-Westfalen\tNW\t\t\t\t\t51.54\t7.61\t\n",
    "DE\t45127\tEssen\tNordrhein-Westfalen\tNW\t\t\t\t\t51.45\t7.01\t\n",
    "DE\t80331\tMünchen\tBayern\tBY\t\t\t\t\t48.13\t11.57\t\n",
    "DE\t40210\tDüsseldorf\tNordrhein-Westfalen\tNW\t\t\t\t\t51.22\t6.78\t\n",
    "kaputt\n",
]


def test_tabelle_mittelt_mehrere_zeilen_pro_plz():
    t = b.baue_tabelle(ZEILEN)
    assert t["44319"] == [51.53, 7.6]
    assert set(t) == {"44319", "45127", "80331", "40210"}


def test_westfalen_lippe_nur_nrw_und_passende_leitregion():
    t = b.baue_tabelle(ZEILEN)
    plzs = [p["plz"] for p in b.plz_westfalen_lippe(ZEILEN, t)]
    assert plzs == ["44319", "45127"]   # 40210 (Rheinland) und 80331 (Bayern) nicht


def test_westfalen_lippe_liefert_die_koordinaten_aus_der_tabelle():
    t = b.baue_tabelle(ZEILEN)
    [dortmund] = [p for p in b.plz_westfalen_lippe(ZEILEN, t) if p["plz"] == "44319"]
    assert dortmund == {"plz": "44319", "lat": 51.53, "lon": 7.6}


def test_ungueltige_zeilen_werden_uebersprungen():
    zeilen = [
        "AT\t44319\tWien\tWien\t\t\t\t\t\t48.2\t16.3\t\n",      # anderes Land
        "DE\t4431\tKurz\tNRW\t\t\t\t\t\t51.0\t7.0\t\n",          # nur 4 Ziffern
        "DE\t4431X\tBuchstabe\tNRW\t\t\t\t\t\t51.0\t7.0\t\n",    # keine reine Zahl
        "DE\t44320\tOhneZahl\tNRW\t\t\t\t\t\tabc\t7.0\t\n",      # Koordinate kaputt
        "DE\t44321\tGenau elf Spalten\tNRW\t\t\t\t\t\t51.5\t7.5",   # Grenze: 11 Felder reichen
    ]
    assert b.baue_tabelle(zeilen) == {"44321": [51.5, 7.5]}


def test_westfalen_lippe_braucht_mindestens_elf_spalten():
    zeilen = ["DE\t44321\tX\tNordrhein-Westfalen\t\t\t\t\t\t51.5\t7.5",   # 11 Felder: ok
              "DE\t44322\tY\tNordrhein-Westfalen\t\t\t\t\t\t51.5"]         # 10 Felder: nicht
    t = {"44321": [51.5, 7.5], "44322": [51.5, 7.5]}
    assert [p["plz"] for p in b.plz_westfalen_lippe(zeilen, t)] == ["44321"]


def test_kommandozeile_schreibt_beide_dateien(tmp_path, monkeypatch):
    import json
    quelle = tmp_path / "DE.txt"
    quelle.write_text("".join(ZEILEN), encoding="utf-8")
    monkeypatch.setattr(b, "ZIEL", tmp_path / "plz.json")
    monkeypatch.setattr(b, "ZIEL_WL", tmp_path / "wl.json")
    b.kommandozeile([str(quelle)])
    assert json.loads((tmp_path / "plz.json").read_text(encoding="utf-8"))["80331"] == [48.13, 11.57]
    assert [p["plz"] for p in json.loads((tmp_path / "wl.json").read_text(encoding="utf-8"))] == ["44319", "45127"]


def test_kommandozeile_ohne_datei_bricht_mit_hinweis_ab():
    import pytest
    with pytest.raises(SystemExit, match="Aufruf"):
        b.kommandozeile([])
