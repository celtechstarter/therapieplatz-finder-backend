"""
Baut webapp/app/assets/plz-koordinaten.json: Postleitzahl -> [Breite, Laenge]
fuer ganz Deutschland. Damit rechnet die Webapp Entfernungen ab der
Postleitzahl der Nutzerin statt immer ab Dortmund-Wickede (1.10.2026, nach
der Erweiterung des Einzugsgebiets bis ins Ruhrgebiet/Sauerland/Muensterland).

Quelle: GeoNames Postal Codes (https://download.geonames.org/export/zip/DE.zip),
Lizenz CC BY 4.0 -- Quellenangabe steht im Impressum der Webapp.
Pro PLZ gibt es dort mehrere Zeilen (Ortsteile, Grosskunden); wir mitteln die
Koordinaten. Genauigkeit: Mitte des PLZ-Gebiets, fuer eine Umkreissuche
ausreichend (typisch unter 2 km Abweichung).

Aufruf (aus backend/):
  python build_plz_tabelle.py PFAD/ZU/DE.txt
"""
import json
import sys
from collections import defaultdict

import pfade

ZIEL = pfade.PROJEKT_ROOT / "webapp" / "app" / "assets" / "plz-koordinaten.json"
# Nebenprodukt fuer den lokalen KV-Register-Scraper: alle NRW-PLZ in den
# Leitregionen, die (ganz oder teilweise) zum Gebiet der KV Westfalen-Lippe gehoeren. Die
# Regierungsbezirk-Angabe in GeoNames ist zu lueckenhaft (nur ~200 PLZ), daher
# ueber Bundesland + PLZ-Anfang. Ein paar Punkte im Rheinland (z.B. Essen in
# 45xxx) schaden nicht: das Register liefert dort nur die naechsten WL-Praxen.
# Liegt in data/ (lokal, gitignored), weil nur der lokale Register-Scraper sie braucht.
ZIEL_WL = pfade.DATA_DIR / "plz_westfalen_lippe.json"
WL_PRAEFIXE = ("32", "33", "34", "37", "44", "45", "46", "48", "49", "57", "58", "59")


def plz_westfalen_lippe(zeilen, tabelle):
    plzs = set()
    for zeile in zeilen:
        teile = zeile.rstrip("\n").split("\t")
        if len(teile) > 10 and teile[3] == "Nordrhein-Westfalen" and teile[1][:2] in WL_PRAEFIXE:
            plzs.add(teile[1].strip())
    return [{"plz": p, "lat": tabelle[p][0], "lon": tabelle[p][1]} for p in sorted(plzs) if p in tabelle]


def baue_tabelle(zeilen):
    summen = defaultdict(lambda: [0.0, 0.0, 0])
    for zeile in zeilen:
        teile = zeile.rstrip("\n").split("\t")
        if len(teile) < 11 or teile[0] != "DE":
            continue
        plz = teile[1].strip()
        if len(plz) != 5 or not plz.isdigit():
            continue
        try:
            lat, lon = float(teile[9]), float(teile[10])
        except ValueError:
            continue
        s = summen[plz]
        s[0] += lat
        s[1] += lon
        s[2] += 1
    return {plz: [round(s[0] / s[2], 3), round(s[1] / s[2], 3)] for plz, s in sorted(summen.items())}


def main(pfad):
    with open(pfad, encoding="utf-8") as f:
        zeilen = f.readlines()
    tabelle = baue_tabelle(zeilen)
    ZIEL.write_text(json.dumps(tabelle, separators=(",", ":")), encoding="utf-8")
    print(f"{len(tabelle)} Postleitzahlen -> {ZIEL}")
    wl = plz_westfalen_lippe(zeilen, tabelle)
    ZIEL_WL.write_text(json.dumps(wl, ensure_ascii=False), encoding="utf-8")
    print(f"{len(wl)} Postleitzahlen in Westfalen-Lippe -> {ZIEL_WL}")


def kommandozeile(argv):
    """`python build_plz_tabelle.py PFAD/ZU/DE.txt` (Datei von GeoNames)."""
    if len(argv) != 1:
        raise SystemExit("Aufruf: python build_plz_tabelle.py PFAD/ZU/DE.txt")
    main(argv[0])


if __name__ == "__main__":
    kommandozeile(sys.argv[1:])
