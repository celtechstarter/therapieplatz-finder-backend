"""Mutationstest: Pruefen die Tests wirklich etwas?

Idee: Das Skript baut absichtlich kleine Fehler in den Code ein (eine
"Mutation"), zum Beispiel `==` statt `!=`, `and` statt `or`, `True` statt
`False` oder eine 1 statt einer 0. Danach laufen die Tests. Schlagen sie
fehl, ist der Fehler "erkannt" (gut). Bleiben sie gruen, hat kein Test die
Stelle wirklich geprueft (Luecke).

Die Abdeckung (Coverage) sagt nur, welche Zeilen beim Testen LAUFEN. Der
Mutationstest sagt, ob ein Fehler in diesen Zeilen AUFFALLEN wuerde.

Sicher: gearbeitet wird in einer Kopie des Projekts in einem
Temp-Ordner. Die echten Dateien werden nie veraendert.

Aufruf (aus dem Projektordner):
  python tools/mutationstest.py backend/filters.py tests/test_filters.py
  python tools/mutationstest.py backend/analyzer.py tests/test_analyzer.py --anzahl 40

Nicht jede ueberlebende Mutation ist eine echte Luecke: manche aendern das
Verhalten gar nicht (z. B. eine Zahl in einem Text oder eine Einstellung
ohne Wirkung im Test). Die Liste am Ende zeigt jede Stelle zum Nachsehen.
"""
import argparse
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent

# (Suchmuster, Ersatz): jede Zeile bekommt hoechstens eine Mutation pro Lauf.
MUTATIONEN = [
    (r" == ", " != "), (r" != ", " == "),
    (r" <= ", " < "), (r" >= ", " > "), (r" < ", " <= "), (r" > ", " >= "),
    (r"\band\b", "or"), (r"\bor\b", "and"), (r"\bnot ", ""),
    (r"\bTrue\b", "False"), (r"\bFalse\b", "True"),
    (r"\breturn (?!None)(\S)", r"return None and \1"),
    (r"(?<![\w.])1(?![\w.])", "2"), (r"(?<![\w.])0(?![\w.])", "1"),
]


def _im_text(code, pos):
    """Grob: liegt die Stelle innerhalb eines Strings? Dann nicht mutieren."""
    davor = code[:pos]
    return davor.count('"') % 2 == 1 or davor.count("'") % 2 == 1


def kandidaten(zeilen):
    """Alle Stellen (Zeile, Muster, Position), an denen eine Mutation passt.
    Kommentare, Docstrings, Importe und print-Ausgaben werden ausgelassen."""
    stellen = []
    im_docstring = False
    for nr, zeile in enumerate(zeilen):
        s = zeile.strip()
        if s.count('"""') == 1 or s.count("'''") == 1:
            im_docstring = not im_docstring
            continue
        if im_docstring or not s or s.startswith(("#", "import ", "from ", "def ", "class ", "@")) or "print(" in s:
            continue
        code = zeile.split("  #")[0]
        for k, (muster, _) in enumerate(MUTATIONEN):
            for treffer in re.finditer(muster, code):
                if not _im_text(code, treffer.start()):
                    stellen.append((nr, k, treffer.start()))
    return stellen


def mutiere(zeile, k, pos):
    muster, ersatz = MUTATIONEN[k]
    return zeile[:pos] + re.sub(muster, ersatz, zeile[pos:], count=1)


def tests_gruen(ordner, testdateien, timeout):
    try:
        lauf = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *testdateien],
            cwd=ordner, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False   # haengt der Test, ist die Mutation auch aufgefallen
    return lauf.returncode == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mutationstest fuer ein Backend-Modul")
    parser.add_argument("modul", help="z. B. backend/filters.py")
    parser.add_argument("tests", nargs="+", help="Testdateien, z. B. tests/test_filters.py")
    parser.add_argument("--anzahl", type=int, default=30, help="hoechstens so viele Mutationen (Zufall)")
    parser.add_argument("--seed", type=int, default=7, help="Zufallsstart, fuer wiederholbare Ergebnisse")
    parser.add_argument("--timeout", type=int, default=60, help="Sekunden pro Testlauf")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "projekt"
        shutil.copytree(PROJEKT, kopie, ignore=shutil.ignore_patterns(
            ".git", ".venv", "node_modules", "webapp", "data", "__pycache__", "*.pyc"))
        ziel = kopie / args.modul
        original = ziel.read_text(encoding="utf-8").split("\n")
        if not tests_gruen(kopie, args.tests, args.timeout):
            sys.exit("Die Tests sind schon ohne Mutation rot. Erst reparieren, dann messen.")

        stellen = kandidaten(original)
        random.Random(args.seed).shuffle(stellen)
        erkannt, unbemerkt = 0, []
        for nr, k, pos in stellen[:args.anzahl]:
            neu = mutiere(original[nr], k, pos)
            if neu == original[nr]:
                continue
            ziel.write_text("\n".join(original[:nr] + [neu] + original[nr + 1:]), encoding="utf-8")
            if tests_gruen(kopie, args.tests, args.timeout):
                unbemerkt.append((nr + 1, original[nr].strip(), neu.strip()))
            else:
                erkannt += 1
        ziel.write_text("\n".join(original), encoding="utf-8")

    gesamt = erkannt + len(unbemerkt)
    anteil = round(100 * erkannt / gesamt) if gesamt else 100
    print(f"{args.modul}: {gesamt} Mutationen, {erkannt} erkannt, {len(unbemerkt)} unbemerkt ({anteil} %)")
    for nr, alt, neu in unbemerkt:
        print(f"  unbemerkt, Zeile {nr}: {alt[:80]}\n                  -> {neu[:80]}")
    return anteil


if __name__ == "__main__":
    main()
