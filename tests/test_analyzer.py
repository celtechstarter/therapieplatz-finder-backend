"""Tests für analyzer.py.

Der Kern `analyzer.analysiere()` arbeitet nur mit Listen. Die Tests geben
ihm eine KI-Attrappe mit, die vorgegebene Bewertungen liefert und
mitschreibt, welche Profile sie bekommen hat. Für `main()` gibt es zusätzlich
Durchläufe mit echten Dateien in einem Testordner.
"""
import json
import random

import pytest


import analyzer
import pfade
from analyse_regeln import inhalt_hash

ZEIT = "2026-10-16T12:00:00+00:00"


class FakeKI:
    """Liefert für jedes Profil eine Bewertung (fest oder per Funktion) und
    merkt sich, wen sie bewertet hat."""

    def __init__(self, bewertung=None, gkv=True, plaetze="unklar", notiz="KI"):
        self.gefragt = []
        self._bewertung = bewertung or (lambda p: {"GKV_akzeptiert": gkv, "Freie_Plaetze": plaetze, "Notiz": notiz})

    def __call__(self, profil):
        self.gefragt.append(profil["profil_url"])
        return self._bewertung(profil)


def keine_ki(profil):
    raise AssertionError(f"KI darf nicht gefragt werden: {profil.get('profil_url')}")


def profil(url="u1", **extra):
    p = {"profil_url": url, "name": f"Dipl.-Psych. {url}",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
         "persoenliches_profil": "Eigener Text, damit die KI gefragt wird.",
         "email": f"{url}@praxis.example", "gkv_art": "kassensitz"}
    p.update(extra)
    return p


def lauf(profile, ergebnisse=(), skips=(), ki=keine_ki, **optionen):
    gespeichert = []
    e, s, statistik = analyzer.analysiere(
        list(profile), list(ergebnisse), list(skips), ki=ki, zeit=lambda: ZEIT,
        zufall=random.Random(1), zwischenspeichern=lambda e, s: gespeichert.append((list(e), list(s))),
        **optionen)
    return e, s, statistik, gespeichert


# ---------- Ergebnis eines neuen Profils ----------

def test_neues_profil_wird_bewertet_und_vollstaendig_gespeichert():
    ki = FakeKI(plaetze=True, notiz="passt")
    p = profil()
    ergebnisse, skips, statistik, gespeichert = lauf([p], ki=ki)
    assert ki.gefragt == ["u1"]
    [e] = ergebnisse
    assert e["Notiz"] == "passt" and e["Freie_Plaetze"] is True
    assert e["email"] == "u1@praxis.example"                 # Originaldaten bleiben
    assert e["inhalt_hash"] == inhalt_hash(p) and e["analysiert_am"] == ZEIT
    assert analyzer.REFERENZ_NAME in e["Email_generiert"]
    assert e["anrede"] and e["therapieform"]
    assert skips == [] and statistik["ki"] == 1
    assert gespeichert, "nach einem bezahlten KI-Aufruf muss sofort gespeichert werden"


def test_boese_ki_antwort_kann_kontaktdaten_nicht_ueberschreiben():
    """Durchgängig geprüft: eine Antwort mit fremder E-Mail läuft durch
    dieselbe Prüfung wie im Betrieb (analyse_ki.pruefe_bewertung) und
    ändert die Kontaktdaten der Praxis nicht."""
    import analyse_ki
    ki = FakeKI(bewertung=lambda p: analyse_ki.pruefe_bewertung(
        {"GKV_akzeptiert": True, "email": "angreifer@evil.example", "name": "Dr. Fake"}))
    [e], *_ = lauf([profil()], ki=ki)
    assert e["email"] == "u1@praxis.example" and e["name"] == "Dipl.-Psych. u1"


# ---------- Wer wird überhaupt bewertet ----------

def test_unveraendertes_profil_wird_nicht_erneut_bewertet():
    p = profil()
    alt = {**p, "Notiz": "alt", "inhalt_hash": inhalt_hash(p)}
    ergebnisse, _, statistik, _ = lauf([p], ergebnisse=[alt])
    assert [e["Notiz"] for e in ergebnisse] == ["alt"]
    assert statistik["gruende"] == {"unveraendert": 1}


def test_geaendertes_profil_wird_neu_bewertet_und_ersetzt_an_seiner_stelle():
    alt_a, b = profil("a"), profil("b")
    vorher = [{**alt_a, "Notiz": "alt", "inhalt_hash": inhalt_hash(alt_a)},
              {**b, "Notiz": "b", "inhalt_hash": inhalt_hash(b)}]
    neu_a = profil("a", persoenliches_profil="Jetzt Warteliste 12 Monate.")
    ki = FakeKI(notiz="neu")
    ergebnisse, *_ = lauf([neu_a, b], ergebnisse=vorher, ki=ki)
    assert ki.gefragt == ["a"]
    assert [e["Notiz"] for e in ergebnisse] == ["neu", "b"]   # Reihenfolge stabil, kein Duplikat
    assert ergebnisse[0]["persoenliches_profil"].startswith("Jetzt")


def test_fehlgeschlagene_neubewertung_behaelt_altes_ergebnis():
    alt = profil()
    vorher = [{**alt, "Notiz": "alt", "inhalt_hash": inhalt_hash(alt)}]
    ergebnisse, _, statistik, _ = lauf([profil(persoenliches_profil="geändert")], ergebnisse=vorher,
                                       ki=FakeKI(bewertung=lambda p: None))
    assert [e["Notiz"] for e in ergebnisse] == ["alt"]
    assert statistik["fehlgeschlagen"] == 1


def test_alte_ergebnisse_ohne_hash_nur_mit_schalter_neu():
    vorher = [{**profil(), "Notiz": "alt ohne hash"}]
    ergebnisse, *_ = lauf([profil(persoenliches_profil="neu")], ergebnisse=vorher)
    assert ergebnisse == vorher and "inhalt_hash" not in ergebnisse[0]
    ergebnisse, *_ = lauf([profil()], ergebnisse=vorher, ki=FakeKI(notiz="neu dank Schalter"), alte_neu=True)
    assert [e["Notiz"] for e in ergebnisse] == ["neu dank Schalter"]


def test_doppelte_url_im_rohdatensatz_wird_nur_einmal_bewertet():
    ki = FakeKI()
    ergebnisse, *_ = lauf([profil(), profil(name="Doppelt")], ki=ki)
    assert ki.gefragt == ["u1"] and len(ergebnisse) == 1


def test_profil_ohne_angaben_wartet_und_landet_nirgends():
    leer = {"profil_url": "leer", "name": "Leer", "abrechnungsarten": [], "therapieangebot": []}
    ergebnisse, skips, statistik, _ = lauf([leer])
    assert ergebnisse == [] and skips == []
    assert statistik["gruende"] == {"wartet auf Angaben": 1}


def test_registerprofil_ohne_text_wird_ohne_ki_bewertet():
    register = profil("reg", persoenliches_profil="")
    ki = FakeKI()
    ergebnisse, _, statistik, gespeichert = lauf([register, profil("txt")], ki=ki)
    assert ki.gefragt == ["txt"]
    reg = next(e for e in ergebnisse if e["profil_url"] == "reg")
    assert reg["GKV_akzeptiert"] is True and reg["Freie_Plaetze"] == "unklar"
    assert reg["inhalt_hash"] and reg["Email_generiert"]
    assert statistik["ohne_ki"] == 1 and statistik["ki"] == 1


# ---------- Privatpraxen und Skip-Liste ----------

def test_privatpraxis_kommt_in_die_skip_liste():
    privat = profil("privat", gkv_art="privat", abrechnungsarten=["Private Krankenversicherung"])
    kasse = profil("kasse")
    ergebnisse, skips, statistik, gespeichert = lauf([privat, kasse], ki=FakeKI(gkv=False))
    assert [e["profil_url"] for e in ergebnisse] == ["kasse"]       # KI-Absage allein reicht nicht
    assert [s["profil_url"] for s in skips] == ["privat"]
    assert skips[0]["inhalt_hash"] == inhalt_hash(privat) and skips[0]["analysiert_am"] == ZEIT
    assert statistik["privat"] == 1
    assert any(s for _, s in gespeichert), "Skip-Entscheidung muss sofort gespeichert werden"


def test_skip_liste_verhindert_erneute_bewertung():
    privat = profil("privat", gkv_art="privat")
    skip = {"profil_url": "privat", "inhalt_hash": inhalt_hash(privat)}
    ergebnisse, skips, *_ = lauf([privat], skips=[skip])
    assert ergebnisse == [] and skips == [skip]


def test_ehemalige_privatpraxis_mit_neuem_inhalt_kommt_zurueck():
    alt = profil("p", gkv_art="privat", abrechnungsarten=["Private Krankenversicherung"])
    skip = {"profil_url": "p", "inhalt_hash": inhalt_hash(alt)}
    ergebnisse, skips, *_ = lauf([profil("p")], skips=[skip], ki=FakeKI(notiz="jetzt Kasse"))
    assert [e["Notiz"] for e in ergebnisse] == ["jetzt Kasse"]
    assert skips == []


def test_bisheriges_ergebnis_wird_durch_skip_ersetzt():
    alt = profil()
    vorher = [{**alt, "inhalt_hash": inhalt_hash(alt)}]
    neu = profil(gkv_art="privat", abrechnungsarten=["Selbstzahler"])
    ergebnisse, skips, *_ = lauf([neu], ergebnisse=vorher, ki=FakeKI(gkv=False))
    assert ergebnisse == []
    assert [s["inhalt_hash"] for s in skips] == [inhalt_hash(neu)]


# ---------- --ohne-ki ----------

def test_ohne_ki_ruft_nie_die_ki_auf_und_bewertet_per_regel():
    eins = profil("1", persoenliches_profil="Derzeit keine freien Plätze.")
    privat = profil("2", gkv_art="privat", abrechnungsarten=["Selbstzahler"], persoenliches_profil="Nur Selbstzahler.")
    ergebnisse, skips, *_ = lauf([eins, privat], ohne_ki_lauf=True)
    assert [(e["profil_url"], e["Freie_Plaetze"]) for e in ergebnisse] == [("1", False)]
    assert [s["profil_url"] for s in skips] == ["2"]


def test_ohne_ki_speichert_nur_alle_200_profile():
    profile = [profil(str(i)) for i in range(401)]
    *_, gespeichert = lauf(profile, ohne_ki_lauf=True)
    assert len(gespeichert) == 2   # nach Profil 200 und 400


# ---------- Hilfsfunktionen ----------

def test_setze_ergebnis_ersetzt_und_entfernt_duplikate():
    alt = [{"profil_url": "a", "v": 1}, {"profil_url": "b"}, {"profil_url": "a", "v": 2}]
    assert analyzer.setze_ergebnis(alt, {"profil_url": "a", "v": 3}) == [{"profil_url": "a", "v": 3}, {"profil_url": "b"}]
    assert analyzer.setze_ergebnis([], {"profil_url": "c"}) == [{"profil_url": "c"}]


def test_schalter_aus_umgebung_und_kommandozeile(monkeypatch):
    monkeypatch.delenv("OHNE_KI", raising=False)
    monkeypatch.delenv("NEU_ANALYSE_ALT", raising=False)
    assert analyzer.ohne_ki_modus(["--ohne-ki"]) and not analyzer.ohne_ki_modus([])
    assert analyzer.alte_neu_analysieren(["--neu-analyse-alt"]) and not analyzer.alte_neu_analysieren([])
    monkeypatch.setenv("OHNE_KI", "1")
    monkeypatch.setenv("NEU_ANALYSE_ALT", "0")
    assert analyzer.ohne_ki_modus([]) and not analyzer.alte_neu_analysieren([])


# ---------- main(): echte Dateien ----------

@pytest.fixture
def dateien(tmp_path, monkeypatch):
    pfadnamen = {"RESULTS_RAW": "roh.json", "RESULTS_ANALYZED": "ergebnis.json",
                 "AUSGESCHLOSSEN_LOG": "ausgeschlossen.json",
                 "MANUELL_AUSGESCHLOSSEN": "excluded.json", "UEBERSPRUNGEN_LOG": "skip.json"}
    for name, datei in pfadnamen.items():
        monkeypatch.setattr(pfade, name, tmp_path / datei)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def schreibe(name, daten):
        getattr(pfade, name).write_text(json.dumps(daten), encoding="utf-8")

    def lies(name):
        return json.loads(getattr(pfade, name).read_text(encoding="utf-8"))
    return schreibe, lies


def _roh(url, **extra):
    p = profil(url, **extra)
    del p["gkv_art"]   # setzt der Filter selbst
    return p


def test_main_filtert_bewertet_und_schreibt_alle_dateien(dateien):
    schreibe, lies = dateien
    kind = _roh("kind", therapieangebot=["Einzeltherapie: Kinder und Jugendliche"],
                name="Kinder- und Jugendlichenpsychotherapeutin Kind")
    schreibe("RESULTS_RAW", [_roh("ok"), kind])
    ergebnis = analyzer.main([], ki=FakeKI())
    assert [e["profil_url"] for e in ergebnis] == ["ok"]
    assert [e["profil_url"] for e in lies("RESULTS_ANALYZED")] == ["ok"]
    assert [e["profil_url"] for e in lies("AUSGESCHLOSSEN_LOG")] == ["kind"]
    assert lies("UEBERSPRUNGEN_LOG") == []


def test_main_verlangt_kassenzulassung_fuer_heilpraktiker(dateien):
    """Regel 3 aus filters.py gilt im Analyzer immer: Heilpraktiker ohne
    Approbation können keine Kasse abrechnen und fliegen raus."""
    schreibe, lies = dateien
    hp = _roh("hp", name="Heilpraktikerin für Psychotherapie Muster")
    schreibe("RESULTS_RAW", [hp])
    assert analyzer.main([], ki=keine_ki) == []
    assert [e["profil_url"] for e in lies("AUSGESCHLOSSEN_LOG")] == ["hp"]


def test_main_beachtet_von_hand_ausgeblendete_praxen(dateien):
    """excluded.json: weder bewertet noch in der App, auch ein altes
    Ergebnis und ein alter Skip-Eintrag fliegen raus."""
    schreibe, lies = dateien
    schreibe("RESULTS_RAW", [_roh("weg"), _roh("bleibt")])
    schreibe("MANUELL_AUSGESCHLOSSEN", [{"profil_url": "weg"}, {"name": "ohne url"}])
    schreibe("RESULTS_ANALYZED", [{"profil_url": "weg", "Notiz": "alt"}])
    schreibe("UEBERSPRUNGEN_LOG", [{"profil_url": "weg"}])
    ki = FakeKI()
    ergebnis = analyzer.main([], ki=ki)
    assert ki.gefragt == ["bleibt"]
    assert [e["profil_url"] for e in ergebnis] == ["bleibt"]
    assert lies("UEBERSPRUNGEN_LOG") == []


def test_main_entfernt_ergebnisse_die_der_filter_jetzt_ausschliesst(dateien):
    """Eine zweite, ungültige Fassung derselben URL (kommt nach Merges vor)
    darf das gültige Profil nicht verschwinden lassen."""
    schreibe, _ = dateien
    gueltig = _roh("u")
    ungueltig = _roh("u", therapieangebot=["Gruppentherapie: Erwachsene"])
    schreibe("RESULTS_RAW", [gueltig, ungueltig])
    schreibe("RESULTS_ANALYZED", [{"profil_url": "u", "Notiz": "alt"}])
    ergebnis = analyzer.main([], ki=FakeKI(notiz="neu"))
    assert [e["Notiz"] for e in ergebnis] == ["neu"]


def test_main_ohne_schluessel_bricht_ab(dateien, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(SystemExit):
        analyzer.main([], ki=FakeKI())


def test_main_ohne_ki_braucht_keinen_schluessel(dateien, monkeypatch):
    schreibe, _ = dateien
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    schreibe("RESULTS_RAW", [_roh("a", persoenliches_profil="Freie Plätze vorhanden.")])
    [e] = analyzer.main(["--ohne-ki"], ki=keine_ki)
    assert e["Freie_Plaetze"] is True


def test_main_ohne_rohdaten(dateien):
    assert analyzer.main([], ki=keine_ki) == []
