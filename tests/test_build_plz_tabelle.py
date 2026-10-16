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
