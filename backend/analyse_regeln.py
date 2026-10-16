"""Feste Regeln für die Bewertung eines Praxisprofils, ganz ohne KI.

Alles hier sind reine Funktionen: Profil rein, Ergebnis raus, keine Dateien,
kein Netz. Sie entscheiden,
- ob sich ein Profil seit der letzten Bewertung inhaltlich geändert hat
  (`inhalt_hash`, `muss_analysiert_werden`),
- ob die KI überhaupt etwas beitragen könnte (`zu_wenig_angaben`,
  `analyse_ohne_ki`),
- und liefern einen kostenlosen Ersatz für die KI (`analyse_per_regel`).

Jede Bewertung hat genau die drei Felder aus `analyse_ki.ERLAUBTE_FELDER`:
GKV_akzeptiert, Freie_Plaetze, Notiz.
"""
import hashlib
import json
import re

# Diese Felder bestimmen, ob ein Profil "inhaltlich gleich" geblieben ist.
# Bewusst eine feste Liste: Metadaten wie scraped_at oder vom Filter
# ergänzte Felder würden sonst bei jedem Lauf den Hash ändern, und jedes
# Profil ginge erneut (kostenpflichtig) an die KI.
HASH_FELDER = (
    "name", "adresse", "telefon", "email", "website",
    "abrechnungsarten", "behandlungsschwerpunkte", "therapieverfahren",
    "therapieangebot", "freie_plaetze", "persoenliches_profil", "volltext",
)

# Seitenzähler wie "26852 Seitenaufrufe seit 2012" ändern sich ständig,
# sagen aber nichts über die Praxis aus.
_SEITENAUFRUFE = re.compile(r"\d[\d.]*\s+seitenaufrufe\b[^\n]*", re.IGNORECASE)

_KEINE_PLAETZE = re.compile(
    r"keine\s+(?:freien\s+|neuen\s+)?(?:therapie)?pl(?:ä|ae)tze"
    r"|aufnahmestopp|aufnahme-?stopp"
    r"|keine\s+neuen\s+patient"
    r"|(?:derzeit|aktuell|zur\s+zeit|momentan)\s+(?:leider\s+)?(?:voll|ausgebucht)"
    r"|warteliste\s+(?:ist\s+)?geschlossen",
    re.IGNORECASE)
_FREIE_PLAETZE = re.compile(
    r"(?:freie|kurzfristige?)\s+(?:therapie)?(?:pl(?:ä|ae)tze|termine)\s+(?:sind\s+)?(?:vorhanden|verf(?:ü|ue)gbar|frei)"
    r"|(?:habe|haben|gibt\s+es)\s+(?:derzeit|aktuell|zur\s+zeit|momentan)?\s*(?:wieder\s+)?freie\s+(?:therapie)?pl(?:ä|ae)tze"
    r"|nehme\s+(?:gerne\s+|derzeit\s+|aktuell\s+)?neue\s+patient",
    re.IGNORECASE)
_KASSE_IM_TEXT = re.compile(
    r"gesetzlich\s+versichert|alle\s+kassen|krankenkassen|kassensitz|kassenzulassung",
    re.IGNORECASE)


def _normalisiere(wert):
    if isinstance(wert, list):
        return [_normalisiere(x) for x in wert if x not in (None, "")]
    if isinstance(wert, str):
        return " ".join(_SEITENAUFRUFE.sub(" ", wert).split())
    return wert


def inhalt_hash(profil):
    """Fingerabdruck (sha256) über die inhaltlich wichtigen Felder.

    Leere Werte, Leerzeichen und Seitenzähler zählen nicht mit. Gleicher Hash
    heißt: Das Profil muss nicht neu bewertet werden."""
    relevant = {}
    for feld in HASH_FELDER:
        wert = _normalisiere(profil.get(feld))
        if wert not in (None, "", []):
            relevant[feld] = wert
    daten = json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(daten.encode("utf-8")).hexdigest()


def _nennt_kasse(profil):
    return any("gesetzlich" in str(a).lower() for a in (profil.get("abrechnungsarten") or []))


def _eigener_text(profil):
    return " ".join(str(profil.get(f) or "") for f in ("freie_plaetze", "persoenliches_profil"))


def zu_wenig_angaben(profil):
    """True, wenn das Profil nur Name, Adresse und Kontakt hat.

    Typisch für reine Registereinträge. Die KI kann daraus nichts ableiten,
    ein Aufruf wäre bezahlt, aber nutzlos. Solche Profile werden übersprungen,
    aber nicht dauerhaft: Ergänzt später eine andere Quelle Angaben, laufen
    sie ganz normal durch."""
    for feld in ("abrechnungsarten", "therapieangebot", "behandlungsschwerpunkte"):
        if profil.get(feld):
            return False
    return not (profil.get("persoenliches_profil") or "").strip()


def analyse_ohne_ki(profil):
    """Fertige Bewertung, wenn die KI nichts beitragen könnte, sonst None.

    Das ist so, wenn die Kasse laut Abrechnungsangaben feststeht und das
    Profil weder eigenen Text noch eine Angabe zu freien Plätzen hat. Die KI
    hat in genau diesen Fällen immer "Kasse ja, Plätze unklar" geantwortet."""
    if _eigener_text(profil).strip() or not _nennt_kasse(profil):
        return None
    return {
        "GKV_akzeptiert": True,
        "Freie_Plaetze": "unklar",
        "Notiz": "Kassenpraxis laut Abrechnungsangaben/Register. Das Profil enthält "
                 "keine weiteren Angaben, freie Plätze sind unbekannt.",
    }


def analyse_per_regel(profil):
    """Kostenloser Ersatz für die KI (Schalter --ohne-ki).

    - Kasse: ja, wenn Abrechnungsangaben oder Text die Kasse nennen; nein,
      wenn der Filter das Profil als reine Privatpraxis eingestuft hat;
      sonst "unklar".
    - Freie Plätze: Wortsuche im Text. Eine Verneinung ("keine freien
      Plätze", "Aufnahmestopp") gewinnt immer gegen eine positive Aussage."""
    text = _eigener_text(profil)
    if _nennt_kasse(profil) or _KASSE_IM_TEXT.search(text):
        kasse = True
    elif profil.get("gkv_art") == "privat":
        kasse = False
    else:
        kasse = "unklar"
    if _KEINE_PLAETZE.search(text):
        plaetze = False
    elif _FREIE_PLAETZE.search(text):
        plaetze = True
    else:
        plaetze = "unklar"
    return {"GKV_akzeptiert": kasse, "Freie_Plaetze": plaetze,
            "Notiz": "Regelbasiert bewertet (ohne KI) aus Abrechnungsarten und Profiltext."}


def muss_analysiert_werden(profil, vorher, alte_neu=False):
    """Muss dieses Profil (wieder) bewertet werden? Gibt (ja_nein, grund).

    `vorher` ist das bisherige Ergebnis oder der Eintrag aus der Skip-Liste
    mit derselben profil_url (oder None). Alte Ergebnisse ohne Hash werden
    aus Kostengründen nur mit `alte_neu=True` neu bewertet."""
    if vorher is None:
        return True, "neu"
    alter_hash = vorher.get("inhalt_hash")
    if not alter_hash:
        return alte_neu, "alt ohne Hash"
    if alter_hash == inhalt_hash(profil):
        return False, "unveraendert"
    return True, "Inhalt geaendert"


def ist_reine_privatpraxis(bewertung, profil):
    """True nur, wenn KI/Regel UND Filter sich einig sind: keine Kasse.

    Die Abrechnungsangaben (Filter) sind nachprüfbar, die KI-Einschätzung
    stammt aus Freitext. Ein KI-Fehlurteil allein darf keine Kassenpraxis aus
    der Liste werfen, ein verpasster Therapieplatz wiegt schwerer als eine
    überflüssige Anfrage."""
    return bewertung.get("GKV_akzeptiert") is False and profil.get("gkv_art") == "privat"
