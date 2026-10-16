"""
Gemeinsame Bausteine zum Zusammenfuehren einer Zusatzquelle (results_*_raw.json)
in die Haupt-Rohdatei (results_raw.json).

Frueher lebte diese Normalisierungs-/Duplikat-Logik ausschliesslich in einem
einzelnen quellenspezifischen Merge-Skript. Mit einer zweiten Zusatzquelle
waere sie sonst 1:1 dorthin kopiert worden -- verboten laut CLAUDE.md ("keine
Duplikate"). Stattdessen: die quellen-UNABHAENGIGEN Teile (Name/Adresse
normalisieren, Duplikat-Erkennung, Index bauen) leben hier, jede Quelle
bringt nur noch ihre eigene, quellenspezifische Anreicherungslogik mit
(siehe reichere_an() im jeweiligen merge_*.py -- die unterscheiden sich
bewusst, z.B. je nachdem ob ein Treffer einen echten Kassensitz belegt oder
nur eine Mitgliedschaft).
"""
import re

_TITEL_MUSTER = re.compile(
    r'^(Dipl\.?-?Psych\.?|Dr\.?|M\.?Sc\.?|Diplom-?Psycho\w+|Diplom\s+Psycho\w+|Prof\.?|Herr|Frau|Herrn)\s+',
    re.IGNORECASE,
)


def normalisiere_name(name):
    """Titel/Grade UND Anrede entfernen, nur Buchstaben behalten,
    Kleinschreibung -- macht 'Dipl.-Psych. Anna Beispiel', 'Frau Anna Beispiel'
    und 'Anna Beispiel' vergleichbar.

    Mehrfach anwenden (Titel + Anrede koennen kombiniert vorkommen, z.B.
    liefert eine Zusatzquelle "Herr Dr. phil. Max Beispiel" -- ein einzelner
    sub() wuerde nur "Herr " entfernen und "Dr. phil." stehen lassen)."""
    n = name or ""
    for _ in range(3):
        n = _TITEL_MUSTER.sub("", n)
    n = re.sub(r"[^a-zA-ZäöüÄÖÜß\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n


def normalisiere_adresse(adresse):
    """Nur Buchstaben/Ziffern behalten -- macht 'Beispielstr. 26-28, 44137
    Dortmund' und 'Beispielstr 26 28 44137 Dortmund' vergleichbar.

    Zwei weitere Quellen-Eigenheiten werden hier ebenfalls ausgeglichen
    (sonst rutschen Dubletten durch, siehe Meldungen von Nutzer:innen zu
    zwei Praxen, 23.9.2026):
    - "Straße"/"Strasse" vs. die Abkuerzung "Str." (eine Quelle kuerzt ab,
      andere Quellen schreiben aus) werden auf "str" vereinheitlicht.
    - eine andere Quelle haengt hinter PLZ+Stadt zusaetzlich noch den
      Dortmunder Stadtteil an (z.B. "44319 Dortmund-Husen" statt "44319
      Dortmund") -- das wird abgeschnitten, da nach PLZ+Stadt in einer
      deutschen Adresse regulaer nichts mehr folgt."""
    a = (adresse or "").lower()
    a = re.sub(r"stra(ß|ss)e", "str", a)
    a = re.sub(r"[^a-zäöüß0-9\s]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    a = re.sub(r"(\d{5}\s+[a-zäöüß]+)\s+\S.*$", r"\1", a)
    return a


_TELEFON_LAENDERVORWAHL = re.compile(r"^49(\d+)$")


def normalisiere_telefon(telefon):
    """Nur Ziffern behalten und die Laendervorwahl vereinheitlichen -- macht
    '+49(231)1234567', '0231-1234567' und '02 31 / 1 23 45 67' vergleichbar.
    Leer, wenn keine Ziffern enthalten sind (bewusst kein Fallback-Wert, der
    faelschlich als Uebereinstimmung durchgehen koennte)."""
    ziffern = re.sub(r"\D", "", telefon or "")
    m = _TELEFON_LAENDERVORWAHL.match(ziffern)
    if m:
        ziffern = "0" + m.group(1)
    return ziffern


def dedup_schluessel(eintrag):
    """Vergleichsschluessel (normalisierter Name, normalisierte Adresse).

    Gibt None zurueck, wenn BEIDE Teile nach der Normalisierung leer sind.
    Ohne dieses None wuerde jeder Datensatz ohne Name UND ohne Adresse auf
    denselben Schluessel ("", "") fallen -- der zweite solche Eintrag waere
    dann faelschlich ein "Duplikat" des ersten und statt uebernommen nur
    "angereichert" worden, d.h. still verworfen. Ein Eintrag ohne Name und
    Adresse ist kaputt, aber Datenverlust ist hier das schlechtere Ergebnis
    als ein sichtbarer Doppeleintrag."""
    schluessel = (normalisiere_name(eintrag.get("name")),
                  normalisiere_adresse(eintrag.get("adresse")))
    if not schluessel[0] and not schluessel[1]:
        return None
    return schluessel


def baue_index(eintraege):
    index = {}
    for e in eintraege:
        schluessel = dedup_schluessel(e)
        if schluessel is None:
            continue  # nicht dedupbar, siehe dedup_schluessel()
        index.setdefault(schluessel, []).append(e)
    return index


def merge(raw_eintraege, zusatz_eintraege, reichere_an):
    """Gibt (neue_raw_liste, anzahl_neu, anzahl_angereichert) zurueck.

    `reichere_an(bestehender_eintrag, zusatz_eintrag) -> bool` ist
    quellenspezifisch (siehe Modul-Docstring) und wird nur bei einem
    erkannten Duplikat aufgerufen; ihr Rueckgabewert sagt, ob tatsaechlich
    etwas geaendert wurde.

    raw_eintraege wird nicht in-place veraendert (Kopie der Liste, aber die
    dict-Objekte darin werden bei Anreicherung mutiert -- das ist gewollt,
    da wir dieselben Objekte am Ende zurueckschreiben)."""
    ergebnis = list(raw_eintraege)
    index = baue_index(ergebnis)
    raw_urls = {e.get("profil_url") for e in ergebnis if e.get("profil_url")}

    anzahl_neu = 0
    anzahl_angereichert = 0

    for zusatz_eintrag in zusatz_eintraege:
        if zusatz_eintrag.get("profil_url") in raw_urls:
            continue  # schon exakt (per URL) vorhanden

        schluessel = dedup_schluessel(zusatz_eintrag)
        if schluessel is not None:
            treffer = index.get(schluessel)
            if treffer:
                for bestehender in treffer:
                    if reichere_an(bestehender, zusatz_eintrag):
                        anzahl_angereichert += 1
                continue

        ergebnis.append(zusatz_eintrag)
        if schluessel is not None:
            index.setdefault(schluessel, []).append(zusatz_eintrag)
        if zusatz_eintrag.get("profil_url"):
            raw_urls.add(zusatz_eintrag.get("profil_url"))
        anzahl_neu += 1

    return ergebnis, anzahl_neu, anzahl_angereichert


# Kartenlinks, die Verzeichnisse (z.B. therapie.de) neben jede Adresse setzen --
# das ist NICHT die Website der Praxis (Befund 30.9.2026: ohne diese Sperre
# landete bei Profilen ohne eigene Website der Google-Maps-Link im Feld
# "website", live bei 17 Praxen als "Website"-Link sichtbar).
_KARTEN_HOSTS = ("google.com/maps", "maps.google.", "goo.gl/maps", "maps.apple.com",
                 "openstreetmap.org")


def ist_praxis_website(href):
    h = (href or "").lower()
    return bool(h) and "therapie.de" not in h and not any(k in h for k in _KARTEN_HOSTS)
