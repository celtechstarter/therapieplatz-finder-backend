"""Tests fuer analyzer.py: Parsing/Validierung der KI-Antwort, Prompt-Aufbau
und -- mit gemocktem API-Client -- analyze_therapeut() sowie der
Resume-Ablauf in main(). Das ist der Teil, der gegen Prompt-Injection und
abgeschnittene/kaputte Modellantworten absichert (Audit-Befunde K3, M7)."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-fuer-pytest")

import analyzer
import pfade


# ---------- parse_analyse_antwort ----------

def test_parse_reines_json():
    d = analyzer.parse_analyse_antwort('{"GKV_akzeptiert": true, "Email_generiert": "x"}')
    assert d == {"GKV_akzeptiert": True, "Email_generiert": "x"}


def test_parse_json_in_codeblock():
    raw = '```json\n{"GKV_akzeptiert": "unklar", "Email_generiert": "x"}\n```'
    d = analyzer.parse_analyse_antwort(raw)
    assert d["GKV_akzeptiert"] == "unklar"


def test_parse_abgeschnittene_antwort_gibt_none_statt_absturz():
    """Regression zum Audit-Befund M7: die alte Implementierung
    (raw.split('```')[1]) warf IndexError, wenn die Antwort mitten in
    einem Codeblock abgeschnitten wurde (z.B. max_tokens erreicht) -- der
    wahrscheinlichste Fehlerfall bei einer vollstaendigen Email+Notiz."""
    raw = '```json\n{"GKV_akzeptiert": true, "Email_gener'
    assert analyzer.parse_analyse_antwort(raw) is None


def test_parse_text_drumherum_wird_ignoriert():
    raw = 'Gerne, hier ist die Analyse:\n{"GKV_akzeptiert": false, "Email_generiert": "x"}\nViel Erfolg!'
    d = analyzer.parse_analyse_antwort(raw)
    assert d["GKV_akzeptiert"] is False


def test_parse_leere_antwort():
    assert analyzer.parse_analyse_antwort("") is None
    assert analyzer.parse_analyse_antwort(None) is None


def test_parse_kaputtes_json_gibt_none():
    assert analyzer.parse_analyse_antwort('{"GKV_akzeptiert": true,,,}') is None


# ---------- validiere_analyse ----------

def test_validiere_vollstaendige_antwort_bleibt_unveraendert():
    d = {"GKV_akzeptiert": "unklar", "Freie_Plaetze": True, "Email_generiert": "x", "Notiz": "y"}
    assert analyzer.validiere_analyse(dict(d)) == d


def test_validiere_fehlendes_pflichtfeld_gibt_none():
    assert analyzer.validiere_analyse({"Freie_Plaetze": True}) is None  # GKV_akzeptiert fehlt


def test_validiere_ohne_email_generiert_ist_gueltig():
    # Seit der Umstellung auf email_vorlagen.py (siehe dortigen Docstring)
    # schreibt die KI die Email nicht mehr selbst, Email_generiert ist daher
    # kein Pflichtfeld der KI-Antwort mehr -- main() setzt es separat lokal.
    assert analyzer.validiere_analyse({"GKV_akzeptiert": True}) is not None


def test_validiere_unzulaessiger_gkv_wert_gibt_none():
    d = {"GKV_akzeptiert": "vielleicht", "Email_generiert": "x"}
    assert analyzer.validiere_analyse(d) is None


def test_validiere_unzulaessiger_freie_plaetze_wert_wird_auf_unklar_korrigiert():
    d = {"GKV_akzeptiert": True, "Email_generiert": "x", "Freie_Plaetze": "vielleicht"}
    ergebnis = analyzer.validiere_analyse(d)
    assert ergebnis["Freie_Plaetze"] == "unklar"


def test_validiere_kein_dict_gibt_none():
    assert analyzer.validiere_analyse("kein dict") is None
    assert analyzer.validiere_analyse(None) is None
    assert analyzer.validiere_analyse([1, 2, 3]) is None


# ---------- Whitelist gegen Prompt Injection (Kernstück von K3) ----------

def test_erlaubte_analyse_felder_enthaelt_kein_email_oder_name():
    """Das ist die eigentliche Absicherung gegen K3 (Prompt Injection ueber
    gescrapten Fremdtext, der versucht die Empfaenger-Adresse oder den
    Namen zu ueberschreiben). analyze_therapeut() filtert die Modellantwort
    am Ende explizit auf ERLAUBTE_ANALYSE_FELDER -- dieser Test dokumentiert
    und schuetzt genau diese Whitelist."""
    assert "email" not in analyzer.ERLAUBTE_ANALYSE_FELDER
    assert "name" not in analyzer.ERLAUBTE_ANALYSE_FELDER
    assert "profil_url" not in analyzer.ERLAUBTE_ANALYSE_FELDER
    assert analyzer.ERLAUBTE_ANALYSE_FELDER == {
        "GKV_akzeptiert", "Freie_Plaetze", "Notiz"
    }


def test_simulierte_prompt_injection_wird_durch_whitelist_neutralisiert():
    """Simuliert, was passieren wuerde, wenn ein praepariertes Profil das
    Modell dazu bringt, zusaetzliche Felder wie 'email' auszugeben. Der
    Merge in analyzer.main() ist {**therapeut, **analysis} -- wenn
    'analysis' hier bereits gefiltert ist (wie es analyze_therapeut() tut),
    kann kein zusaetzliches Feld die Originaldaten ueberschreiben."""
    therapeut = {"name": "Dr. Echt", "email": "echt@praxis.de", "profil_url": "u1"}
    boesartige_modellantwort = {
        "GKV_akzeptiert": True,
        "Email_generiert": "Text",
        "email": "angreifer@evil.example",   # Injection-Versuch
        "name": "Dr. Fake",                   # Injection-Versuch
    }
    gefiltert = {k: v for k, v in boesartige_modellantwort.items() if k in analyzer.ERLAUBTE_ANALYSE_FELDER}
    combined = {**therapeut, **gefiltert}
    assert combined["email"] == "echt@praxis.de"
    assert combined["name"] == "Dr. Echt"


# ---------- build_prompt ----------

def test_build_prompt_enthaelt_namen_und_feldliste():
    therapeut = {"name": "Dr. Test", "volltext": "kurzer Text"}
    prompt = analyzer.build_prompt(therapeut)
    assert "Dr. Test" in prompt
    assert "GKV_akzeptiert" in prompt


def test_build_prompt_kuerzt_volltext_auf_1500_zeichen():
    therapeut = {"name": "X", "volltext": "a" * 10000}
    prompt = analyzer.build_prompt(therapeut)
    # Der gekuerzte Auszug (1500 * 'a') muss enthalten sein, der volle
    # Text (10000 * 'a') nicht mehr im volltext_auszug-Feld.
    assert "a" * 1500 in prompt
    assert "a" * 1501 not in prompt


def test_build_prompt_uebersteht_fehlende_felder():
    prompt = analyzer.build_prompt({})
    assert "GKV_akzeptiert" in prompt


# ---------- analyze_therapeut() mit gemocktem Client (Audit-Befund T1) ----------
#
# Die Whitelist-Filterung, die Retry-Schleife und die max_tokens-Behandlung
# wurden bisher nur "nachgebaut" getestet. Hier wird die echte Funktion
# aufgerufen, damit ein spaeterer Umbau von analyze_therapeut() diese
# Absicherungen nicht unbemerkt verlieren kann.

def _antwort(text, stop_reason="end_turn"):
    """Baut ein Objekt, das sich wie eine anthropic-Messages-Antwort verhaelt."""
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(text=text)])


def _mock_client(monkeypatch, *antworten):
    """Haengt einen Fake-Client in analyzer.get_client() ein. Jede Antwort aus
    `antworten` wird der Reihe nach zurueckgegeben; eine Exception-Instanz
    wird stattdessen geworfen (fuer Fehler-/Retry-Faelle)."""
    client = MagicMock()
    client.messages.create.side_effect = list(antworten)
    monkeypatch.setattr(analyzer, "get_client", lambda: client)
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)  # keine echten Wartezeiten
    return client


def test_analyze_therapeut_liefert_nur_whitelist_felder(monkeypatch):
    """Kernabsicherung gegen Prompt Injection: selbst wenn das Modell
    zusaetzliche Felder ausgibt (weil ein praeparierter Profiltext es dazu
    verleitet hat), duerfen nur ERLAUBTE_ANALYSE_FELDER zurueckkommen --
    sonst wuerde der Merge in main() z.B. die Empfaenger-Email ueberschreiben."""
    client = _mock_client(monkeypatch, _antwort(json.dumps({
        "GKV_akzeptiert": True,
        "Freie_Plaetze": "unklar",
        "Email_generiert": "Guten Tag ...",
        "Notiz": "passt",
        "email": "angreifer@evil.example",
        "name": "Dr. Fake",
        "profil_url": "https://evil.example/",
    })))
    ergebnis = analyzer.analyze_therapeut({"name": "Dr. Echt", "email": "echt@praxis.de"})
    assert set(ergebnis) <= analyzer.ERLAUBTE_ANALYSE_FELDER
    assert "email" not in ergebnis
    assert "name" not in ergebnis
    assert ergebnis["GKV_akzeptiert"] is True
    assert client.messages.create.call_count == 1


def test_analyze_therapeut_versucht_es_nach_api_fehler_erneut(monkeypatch):
    client = _mock_client(
        monkeypatch,
        RuntimeError("API kurz nicht erreichbar"),
        _antwort('{"GKV_akzeptiert": "unklar", "Email_generiert": "Text"}'),
    )
    ergebnis = analyzer.analyze_therapeut({"name": "Dr. Test"})
    assert ergebnis["GKV_akzeptiert"] == "unklar"
    assert client.messages.create.call_count == 2


def test_analyze_therapeut_behandelt_max_tokens_als_fehlversuch(monkeypatch):
    """stop_reason == 'max_tokens' heisst: die Antwort ist abgeschnitten.
    Sie darf NICHT als Ergebnis durchgehen (die generierte Email waere
    mittendrin abgebrochen), sondern muss einen neuen Versuch ausloesen."""
    client = _mock_client(
        monkeypatch,
        _antwort('{"GKV_akzeptiert": true, "Notiz": "eine sehr lange Begruen',
                 stop_reason="max_tokens"),
        _antwort('{"GKV_akzeptiert": true, "Notiz": "vollstaendig"}'),
    )
    ergebnis = analyzer.analyze_therapeut({"name": "Dr. Test"})
    assert ergebnis["Notiz"] == "vollstaendig"
    assert client.messages.create.call_count == 2


def test_analyze_therapeut_gibt_none_nach_drei_fehlversuchen(monkeypatch):
    client = _mock_client(
        monkeypatch,
        RuntimeError("Fehler 1"), RuntimeError("Fehler 2"), RuntimeError("Fehler 3"),
    )
    assert analyzer.analyze_therapeut({"name": "Dr. Test"}) is None
    assert client.messages.create.call_count == 3


def test_analyze_therapeut_gibt_none_bei_dauerhaft_ungueltiger_antwort(monkeypatch):
    client = _mock_client(
        monkeypatch,
        _antwort("kein JSON"), _antwort("immer noch kein JSON"), _antwort("{}"),
    )
    assert analyzer.analyze_therapeut({"name": "Dr. Test"}) is None
    assert client.messages.create.call_count == 3


# ---------- main(): Resume-Reihenfolge (Audit-Befund B11) ----------

def test_main_analysiert_wieder_zulaessiges_profil_erneut(tmp_path, monkeypatch):
    """Regression zu B11: fertig_urls wurde frueher VOR dem Entfernen der
    inzwischen ausgefilterten Profile aus `results` berechnet. Ein Profil,
    dessen URL in raus_urls landet (hier durch einen zweiten, ungueltigen
    Datensatz mit derselben profil_url -- kommt nach Merges vor), flog damit
    aus results heraus, galt aber weiterhin als "schon fertig" und wurde nie
    neu analysiert: es verschwand still aus der Endliste."""
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    url = "https://www.therapie.de/profil/doppelt/"
    eingabe.write_text(json.dumps([
        # gueltiger Datensatz -> landet in `behalten`
        {"profil_url": url, "name": "Dipl.-Psych. Doppelt",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
         "persoenliches_profil": "Profiltext, damit die KI gefragt wird."},
        # zweiter Datensatz mit DERSELBEN URL, der ausgefiltert wird
        {"profil_url": url, "name": "Dipl.-Psych. Doppelt",
         "therapieangebot": ["Gruppentherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"]},
    ]), encoding="utf-8")
    # vorheriger Analyse-Stand: enthaelt genau dieses Profil
    ausgabe.write_text(json.dumps([{"profil_url": url, "name": "Dipl.-Psych. Doppelt",
                                    "GKV_akzeptiert": True, "Email_generiert": "alt"}]),
                       encoding="utf-8")

    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", tmp_path / "uebersprungen.json")
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: {
        "GKV_akzeptiert": True, "Freie_Plaetze": "unklar",
        "Notiz": "neu analysiert",
    })

    ergebnis = analyzer.main()
    # Email_generiert kommt nicht mehr von der (hier gemockten) KI, sondern
    # wird von main() lokal aus email_vorlagen.py gebaut -- "Notiz" bleibt
    # deshalb der richtige Marker fuer "wurde dieses Profil neu analysiert".
    assert [r["Notiz"] for r in ergebnis] == ["neu analysiert"]
    assert ergebnis[0]["Email_generiert"] != "alt"
    assert analyzer.REFERENZ_NAME in ergebnis[0]["Email_generiert"]


def test_main_ueberspringt_bereits_analysierte_profile(tmp_path, monkeypatch):
    """Gegenprobe zum Test darueber: ein weiterhin gueltiges, bereits
    analysiertes Profil darf NICHT erneut an die (kostenpflichtige) API
    geschickt werden."""
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    url = "https://www.therapie.de/profil/schon-fertig/"
    eingabe.write_text(json.dumps([
        {"profil_url": url, "name": "Dipl.-Psych. Fertig",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"]},
    ]), encoding="utf-8")
    ausgabe.write_text(json.dumps([{"profil_url": url, "name": "Dipl.-Psych. Fertig",
                                    "GKV_akzeptiert": True, "Email_generiert": "alt"}]),
                       encoding="utf-8")

    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", tmp_path / "uebersprungen.json")
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)

    def _darf_nicht_aufgerufen_werden(t):
        raise AssertionError("Profil wurde erneut zur KI-Analyse geschickt")

    monkeypatch.setattr(analyzer, "analyze_therapeut", _darf_nicht_aufgerufen_werden)

    ergebnis = analyzer.main()
    assert [r["Email_generiert"] for r in ergebnis] == ["alt"]


def test_main_ueberspringt_nur_privatpraxen_wenn_beide_quellen_zustimmen(tmp_path, monkeypatch):
    """Dokumentiert die tatsaechliche Regel (Audit-Befund K1): uebersprungen
    wird nur, wenn die KI GKV_akzeptiert == False sagt UND filters.py den
    Eintrag als gkv_art == 'privat' eingestuft hat. Eine KI-Absage allein
    darf einen Eintrag mit Kassen-Abrechnungsart nicht aus der Liste werfen."""
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    eingabe.write_text(json.dumps([
        {"profil_url": "u-privat", "name": "Dipl.-Psych. Privat",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Private Krankenversicherung"]},
        {"profil_url": "u-kasse", "name": "Dipl.-Psych. Kasse",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"]},
    ]), encoding="utf-8")

    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    uebersprungen_log = tmp_path / "uebersprungen.json"
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", uebersprungen_log)
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    # Die KI sagt bei BEIDEN "keine GKV":
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: {
        "GKV_akzeptiert": False, "Email_generiert": "Text", "Notiz": "n",
    })

    ergebnis = analyzer.main()
    # Nur die Privatpraxis faellt raus, der Kassensitz bleibt trotz KI-Absage.
    assert [r["profil_url"] for r in ergebnis] == ["u-kasse"]
    # Regression zu B12: die uebersprungene Privatpraxis muss persistiert
    # worden sein, sonst wird sie beim naechsten Resume-Lauf erneut per
    # KI-Call bewertet.
    persistiert = json.loads(uebersprungen_log.read_text(encoding="utf-8"))
    assert [u["profil_url"] for u in persistiert] == ["u-privat"]


def test_main_uebersprungenes_profil_wird_bei_naechstem_lauf_nicht_erneut_analysiert(tmp_path, monkeypatch):
    """Regression zu B12: ohne persistente Skip-Liste wuerde ein Profil, das
    wegen 'nur Privat/Selbstzahler' uebersprungen wurde, bei jedem
    Resume-Lauf erneut ganz am Anfang der Liste per KI-Call neu bewertet --
    bei einem laengeren zusammenhaengenden Block aus Privatpraxen kaeme der
    Batch dadurch nie ueber diesen Block hinaus, egal wie oft er neu
    gestartet wird."""
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    eingabe.write_text(json.dumps([
        {"profil_url": "u-privat", "name": "Dipl.-Psych. Privat",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Private Krankenversicherung"]},
    ]), encoding="utf-8")

    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", tmp_path / "uebersprungen.json")
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: {
        "GKV_akzeptiert": False, "Email_generiert": "Text", "Notiz": "n",
    })

    # Erster Lauf: Profil wird bewertet und uebersprungen.
    analyzer.main()

    # Zweiter (resumeter) Lauf: die KI darf NICHT erneut aufgerufen werden.
    def _darf_nicht_aufgerufen_werden(t):
        raise AssertionError("Bereits uebersprungenes Profil wurde erneut zur KI-Analyse geschickt")

    monkeypatch.setattr(analyzer, "analyze_therapeut", _darf_nicht_aufgerufen_werden)
    ergebnis = analyzer.main()
    assert ergebnis == []


# ---------- Aktualitaet: Inhalts-Hash beim Resume (Review #11) ----------
#
# Frueher wurde ein bereits analysiertes Profil allein anhand der profil_url
# dauerhaft uebersprungen -- auch wenn sich der Profilinhalt nach einem neuen
# Scrape geaendert hatte (z.B. neue Abrechnungsarten, "keine freien Plaetze").

def _roh_profil(url="https://www.therapie.de/profil/hash/", **extra):
    p = {"profil_url": url, "name": "Dipl.-Psych. Hash",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
         "persoenliches_profil": "Freie Plaetze ab sofort.",
         "volltext": "Profiltext\n123 Seitenaufrufe seit 01.01.2020\n"}
    p.update(extra)
    return p


def _main_umgebung(tmp_path, monkeypatch, roh, vorher=None, skip=None):
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    eingabe.write_text(json.dumps(roh), encoding="utf-8")
    if vorher is not None:
        ausgabe.write_text(json.dumps(vorher), encoding="utf-8")
    skip_log = tmp_path / "uebersprungen.json"
    if skip is not None:
        skip_log.write_text(json.dumps(skip), encoding="utf-8")
    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", skip_log)
    monkeypatch.delenv("NEU_ANALYSE_ALT", raising=False)
    monkeypatch.setattr(analyzer.sys, "argv", ["analyzer.py"])
    return ausgabe, skip_log


def _ki(notiz, gkv=True):
    return _antwort(json.dumps({"GKV_akzeptiert": gkv, "Freie_Plaetze": "unklar", "Notiz": notiz}))


def test_inhalt_hash_ignoriert_seitenaufrufe_leerraum_und_metadaten():
    a = _roh_profil()
    b = _roh_profil(volltext="Profiltext\n  99999 Seitenaufrufe seit 01.01.2020  \n",
                    scraped_at="2026-09-26", quelle="x", gkv_art="kassensitz",
                    filter_warnungen=["w"])
    assert analyzer.inhalt_hash(a) == analyzer.inhalt_hash(b)
    assert analyzer.inhalt_hash(a) == analyzer.inhalt_hash({**a, "email": None, "website": ""})


def test_inhalt_hash_aendert_sich_bei_inhaltlicher_aenderung():
    a = _roh_profil()
    assert analyzer.inhalt_hash(a) != analyzer.inhalt_hash(
        _roh_profil(persoenliches_profil="Derzeit keine freien Plaetze."))
    assert analyzer.inhalt_hash(a) != analyzer.inhalt_hash(
        _roh_profil(abrechnungsarten=["Private Krankenversicherung"]))


def test_main_speichert_hash_und_zeitpunkt(tmp_path, monkeypatch):
    roh = _roh_profil()
    ausgabe, _ = _main_umgebung(tmp_path, monkeypatch, [roh])
    _mock_client(monkeypatch, _ki("erste Analyse"))
    ergebnis = analyzer.main()
    assert ergebnis[0]["inhalt_hash"] == analyzer.inhalt_hash(roh)
    assert ergebnis[0]["analysiert_am"].endswith("+00:00")
    gespeichert = json.loads(ausgabe.read_text(encoding="utf-8"))
    assert gespeichert[0]["inhalt_hash"] == analyzer.inhalt_hash(roh)


def test_main_gleiche_url_gleicher_inhalt_wird_uebersprungen(tmp_path, monkeypatch):
    roh = _roh_profil()
    vorher = [{**roh, "GKV_akzeptiert": True, "Notiz": "alt",
               "inhalt_hash": analyzer.inhalt_hash(roh), "analysiert_am": "2026-09-01T00:00:00+00:00"}]
    # Nur der Seitenaufruf-Zaehler hat sich geaendert -> gilt als unveraendert.
    neu = _roh_profil(volltext="Profiltext\n124 Seitenaufrufe seit 01.01.2020\n")
    _main_umgebung(tmp_path, monkeypatch, [neu], vorher=vorher)
    client = _mock_client(monkeypatch)  # keine Antworten: jeder Aufruf waere ein Fehler
    ergebnis = analyzer.main()
    assert client.messages.create.call_count == 0
    assert [r["Notiz"] for r in ergebnis] == ["alt"]


def test_main_gleiche_url_geaenderter_inhalt_wird_neu_analysiert_und_ersetzt(tmp_path, monkeypatch):
    alt_roh = _roh_profil()
    anderes = _roh_profil(url="u-anderes", name="Dipl.-Psych. Andere")
    vorher = [
        {**alt_roh, "GKV_akzeptiert": True, "Notiz": "alt",
         "inhalt_hash": analyzer.inhalt_hash(alt_roh), "analysiert_am": "2026-09-01T00:00:00+00:00"},
        {**anderes, "GKV_akzeptiert": True, "Notiz": "anderes",
         "inhalt_hash": analyzer.inhalt_hash(anderes), "analysiert_am": "2026-09-01T00:00:00+00:00"},
    ]
    neu = _roh_profil(persoenliches_profil="Derzeit keine freien Plaetze, Warteliste 12 Monate.")
    ausgabe, _ = _main_umgebung(tmp_path, monkeypatch, [neu, anderes], vorher=vorher)
    client = _mock_client(monkeypatch, _ki("neu analysiert"))
    ergebnis = analyzer.main()
    assert client.messages.create.call_count == 1
    # altes Ergebnis ersetzt (gleiche Position), kein Duplikat
    assert [r["Notiz"] for r in ergebnis] == ["neu analysiert", "anderes"]
    assert ergebnis[0]["inhalt_hash"] == analyzer.inhalt_hash(neu)
    assert ergebnis[0]["analysiert_am"] != "2026-09-01T00:00:00+00:00"
    assert ergebnis[0]["persoenliches_profil"].startswith("Derzeit keine")
    assert len(json.loads(ausgabe.read_text(encoding="utf-8"))) == 2


def test_main_fehlgeschlagene_neuanalyse_behaelt_altes_ergebnis(tmp_path, monkeypatch):
    alt_roh = _roh_profil()
    vorher = [{**alt_roh, "GKV_akzeptiert": True, "Notiz": "alt",
               "inhalt_hash": analyzer.inhalt_hash(alt_roh)}]
    neu = _roh_profil(persoenliches_profil="geaendert")
    _main_umgebung(tmp_path, monkeypatch, [neu], vorher=vorher)
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: None)
    ergebnis = analyzer.main()
    assert [r["Notiz"] for r in ergebnis] == ["alt"]


def test_main_alte_ergebnisse_ohne_hash_werden_standardmaessig_nicht_neu_analysiert(tmp_path, monkeypatch):
    roh = _roh_profil(persoenliches_profil="inzwischen geaendert")
    vorher = [{**_roh_profil(), "GKV_akzeptiert": True, "Notiz": "alt ohne hash"}]
    _main_umgebung(tmp_path, monkeypatch, [roh], vorher=vorher)
    client = _mock_client(monkeypatch)
    ergebnis = analyzer.main()
    assert client.messages.create.call_count == 0
    assert [r["Notiz"] for r in ergebnis] == ["alt ohne hash"]
    assert "inhalt_hash" not in ergebnis[0]  # kein nachtraeglich erfundener Hash


def test_main_alte_ergebnisse_ohne_hash_mit_schalter_neu_analysiert(tmp_path, monkeypatch):
    roh = _roh_profil()
    vorher = [{**roh, "GKV_akzeptiert": True, "Notiz": "alt ohne hash"}]
    _main_umgebung(tmp_path, monkeypatch, [roh], vorher=vorher)
    monkeypatch.setenv("NEU_ANALYSE_ALT", "1")
    _mock_client(monkeypatch, _ki("neu dank Schalter"))
    ergebnis = analyzer.main()
    assert [r["Notiz"] for r in ergebnis] == ["neu dank Schalter"]
    assert ergebnis[0]["inhalt_hash"] == analyzer.inhalt_hash(roh)


def test_alte_neu_analysieren_erkennt_env_und_kommandozeile(monkeypatch):
    monkeypatch.delenv("NEU_ANALYSE_ALT", raising=False)
    assert analyzer.alte_neu_analysieren([]) is False
    assert analyzer.alte_neu_analysieren(["--neu-analyse-alt"]) is True
    monkeypatch.setenv("NEU_ANALYSE_ALT", "1")
    assert analyzer.alte_neu_analysieren([]) is True
    monkeypatch.setenv("NEU_ANALYSE_ALT", "0")
    assert analyzer.alte_neu_analysieren([]) is False


def test_main_uebersprungene_privatpraxis_mit_geaendertem_inhalt_wird_neu_bewertet(tmp_path, monkeypatch):
    """Auch die Skip-Liste (nur Privat) haengt jetzt am Inhalts-Hash: nimmt
    eine Privatpraxis spaeter Kassenpatienten, muss sie wieder in die Liste."""
    alt_roh = _roh_profil(abrechnungsarten=["Private Krankenversicherung"])
    skip = [{"profil_url": alt_roh["profil_url"], "name": alt_roh["name"], "grund": "x",
             "inhalt_hash": analyzer.inhalt_hash(alt_roh)}]
    neu = _roh_profil()  # jetzt mit GKV
    _, skip_log = _main_umgebung(tmp_path, monkeypatch, [neu], skip=skip)
    _mock_client(monkeypatch, _ki("jetzt Kasse"))
    ergebnis = analyzer.main()
    assert [r["Notiz"] for r in ergebnis] == ["jetzt Kasse"]
    assert json.loads(skip_log.read_text(encoding="utf-8")) == []


def test_main_uebersprungene_privatpraxis_mit_gleichem_inhalt_bleibt_uebersprungen(tmp_path, monkeypatch):
    roh = _roh_profil(abrechnungsarten=["Private Krankenversicherung"])
    skip = [{"profil_url": roh["profil_url"], "name": roh["name"], "grund": "x",
             "inhalt_hash": analyzer.inhalt_hash(roh)}]
    _main_umgebung(tmp_path, monkeypatch, [roh], skip=skip)
    client = _mock_client(monkeypatch)
    assert analyzer.main() == []
    assert client.messages.create.call_count == 0


def test_main_geaendertes_profil_jetzt_privat_ersetzt_altes_ergebnis_durch_skip(tmp_path, monkeypatch):
    alt_roh = _roh_profil()
    vorher = [{**alt_roh, "GKV_akzeptiert": True, "Notiz": "alt",
               "inhalt_hash": analyzer.inhalt_hash(alt_roh)}]
    neu = _roh_profil(abrechnungsarten=["Private Krankenversicherung"])
    _, skip_log = _main_umgebung(tmp_path, monkeypatch, [neu], vorher=vorher)
    _mock_client(monkeypatch, _ki("nur privat", gkv=False))
    assert analyzer.main() == []
    skip = json.loads(skip_log.read_text(encoding="utf-8"))
    assert [u["inhalt_hash"] for u in skip] == [analyzer.inhalt_hash(neu)]


# ---------- Profile ohne verwertbare Angaben (3.10.2026) ----------

def test_zu_wenig_angaben_nur_grunddaten():
    assert analyzer.zu_wenig_angaben({"name": "A", "adresse": "x", "email": "a@b.de",
                                      "volltext": "Registereintrag ohne Angaben"})


@pytest.mark.parametrize("feld,wert", [
    ("abrechnungsarten", ["Gesetzliche Krankenversicherung"]),
    ("therapieangebot", ["Einzeltherapie: Erwachsene"]),
    ("behandlungsschwerpunkte", ["Depression"]),
    ("persoenliches_profil", "Ich arbeite mit Erwachsenen."),
])
def test_zu_wenig_angaben_eine_angabe_reicht(feld, wert):
    assert not analyzer.zu_wenig_angaben({"name": "A", feld: wert})


def test_main_schickt_profil_ohne_angaben_nicht_zur_ki_und_merkt_es_nicht_dauerhaft(tmp_path, monkeypatch):
    eingabe = tmp_path / "results_raw.json"
    ausgabe = tmp_path / "results_analyzed.json"
    skip = tmp_path / "uebersprungen.json"
    leer = {"profil_url": "https://register.example/leer", "name": "Dipl.-Psych. Leer",
            "adresse": "Musterstr. 1, 44135 Dortmund", "abrechnungsarten": [], "therapieangebot": []}
    voll = {"profil_url": "https://register.example/voll", "name": "Dipl.-Psych. Voll",
            "therapieangebot": ["Einzeltherapie: Erwachsene"],
            "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
            "persoenliches_profil": "Ich arbeite mit Erwachsenen."}
    eingabe.write_text(json.dumps([leer, voll]), encoding="utf-8")

    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", skip)
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    gefragt = []
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: gefragt.append(t["profil_url"]) or {
        "GKV_akzeptiert": True, "Freie_Plaetze": "unklar", "Notiz": "ok"})

    ergebnis = analyzer.main()
    assert gefragt == ["https://register.example/voll"]
    assert [r["profil_url"] for r in ergebnis] == ["https://register.example/voll"]
    assert "register.example/leer" not in (skip.read_text() if skip.exists() else "")

    # Spaeter bestaetigt eine andere Quelle den Kassensitz -> jetzt kommt es
    # in die Liste (ohne KI, siehe analyse_ohne_ki(): kein eigener Text).
    leer["abrechnungsarten"] = ["Gesetzliche Krankenversicherung"]
    eingabe.write_text(json.dumps([leer, voll]), encoding="utf-8")
    gefragt.clear()
    ergebnis = analyzer.main()
    assert gefragt == []
    assert "https://register.example/leer" in [r["profil_url"] for r in ergebnis]


# ---------- Ergebnis ohne KI bei reinen Registerdaten (4.10.2026) ----------

def test_analyse_ohne_ki_bei_kassensitz_ohne_text():
    t = {"name": "A", "abrechnungsarten": ["Gesetzliche Krankenversicherung", "Selbstzahler"],
         "therapieangebot": ["Einzeltherapie: Erwachsene"], "persoenliches_profil": "", "freie_plaetze": ""}
    e = analyzer.analyse_ohne_ki(t)
    assert e["GKV_akzeptiert"] is True and e["Freie_Plaetze"] == "unklar"
    assert set(e) == analyzer.ERLAUBTE_ANALYSE_FELDER


@pytest.mark.parametrize("t", [
    {"abrechnungsarten": ["Gesetzliche Krankenversicherung"], "persoenliches_profil": "Ich nehme neue Patienten."},
    {"abrechnungsarten": ["Gesetzliche Krankenversicherung"], "freie_plaetze": "Wartezeit ca. 3 Monate"},
    {"abrechnungsarten": ["Private Krankenversicherung", "Selbstzahler"]},
    {"abrechnungsarten": []},
])
def test_analyse_ohne_ki_nur_wenn_die_ki_nichts_beitragen_kann(t):
    assert analyzer.analyse_ohne_ki(t) is None


def test_main_ruft_ki_nur_fuer_profile_mit_text_auf(tmp_path, monkeypatch):
    eingabe, ausgabe = tmp_path / "results_raw.json", tmp_path / "results_analyzed.json"
    register = {"profil_url": "https://register.example/1", "name": "Dipl.-Psych. Register",
                "therapieangebot": ["Einzeltherapie: Erwachsene"],
                "abrechnungsarten": ["Gesetzliche Krankenversicherung"]}
    mit_text = dict(register, profil_url="https://profil.example/2", name="Dipl.-Psych. Text",
                    persoenliches_profil="Derzeit keine freien Plätze.")
    eingabe.write_text(json.dumps([register, mit_text]), encoding="utf-8")
    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", tmp_path / "uebersprungen.json")
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    gefragt = []
    monkeypatch.setattr(analyzer, "analyze_therapeut", lambda t: gefragt.append(t["name"]) or {
        "GKV_akzeptiert": True, "Freie_Plaetze": False, "Notiz": "KI"})

    ergebnis = {r["name"]: r for r in analyzer.main()}
    assert gefragt == ["Dipl.-Psych. Text"]
    assert ergebnis["Dipl.-Psych. Register"]["Freie_Plaetze"] == "unklar"
    assert ergebnis["Dipl.-Psych. Register"]["inhalt_hash"]          # wie ein normales Ergebnis
    assert ergebnis["Dipl.-Psych. Register"]["Email_generiert"]
    # Gespeichert ist am Ende alles, auch ohne Zwischenspeichern.
    assert len(json.loads(ausgabe.read_text())) == 2


# ---------- --ohne-ki: Regeln statt KI, garantiert kostenlos (4.10.2026) ----------

@pytest.mark.parametrize("text,erwartet", [
    ("Derzeit keine freien Therapieplätze.", False),
    ("Aktuell Aufnahmestopp, bitte keine Anfragen.", False),
    ("Ich nehme leider keine neuen Patienten auf.", False),
    ("Zur Zeit leider ausgebucht.", False),
    ("Freie Therapieplätze vorhanden!", True),
    ("Ich habe aktuell wieder freie Plätze.", True),
    ("Ich nehme gerne neue Patientinnen und Patienten auf.", True),
    ("Schwerpunkt Depression und Angst.", "unklar"),
    # Verneinung gewinnt, wenn beides im Text steht
    ("Freie Plätze vorhanden ab 2027, derzeit keine freien Plätze.", False),
])
def test_regel_erkennt_freie_plaetze(text, erwartet):
    assert analyzer.analyse_per_regel({"persoenliches_profil": text})["Freie_Plaetze"] == erwartet


def test_regel_kasse():
    regel = analyzer.analyse_per_regel
    assert regel({"abrechnungsarten": ["Gesetzliche Krankenversicherung"]})["GKV_akzeptiert"] is True
    assert regel({"persoenliches_profil": "Gesetzlich Versicherte sind willkommen."})["GKV_akzeptiert"] is True
    assert regel({"gkv_art": "privat", "abrechnungsarten": ["Selbstzahler"]})["GKV_akzeptiert"] is False
    assert regel({"gkv_art": "kostenerstattung"})["GKV_akzeptiert"] == "unklar"
    assert set(regel({})) == analyzer.ERLAUBTE_ANALYSE_FELDER


def test_ohne_ki_modus_schalter(monkeypatch):
    monkeypatch.delenv("OHNE_KI", raising=False)
    assert analyzer.ohne_ki_modus(["--ohne-ki"])
    assert not analyzer.ohne_ki_modus([])
    monkeypatch.setenv("OHNE_KI", "1")
    assert analyzer.ohne_ki_modus([])


def test_main_ohne_ki_ruft_nie_die_api_auf_und_braucht_keinen_key(tmp_path, monkeypatch):
    eingabe, ausgabe = tmp_path / "results_raw.json", tmp_path / "results_analyzed.json"
    eingabe.write_text(json.dumps([
        {"profil_url": "https://p.example/1", "name": "Dipl.-Psych. Eins",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Gesetzliche Krankenversicherung"],
         "persoenliches_profil": "Derzeit keine freien Plätze."},
        {"profil_url": "https://p.example/2", "name": "Dipl.-Psych. Privat",
         "therapieangebot": ["Einzeltherapie: Erwachsene"],
         "abrechnungsarten": ["Selbstzahler"], "persoenliches_profil": "Nur Selbstzahler."},
    ]), encoding="utf-8")
    monkeypatch.setattr(analyzer, "INPUT_FILE", str(eingabe))
    monkeypatch.setattr(analyzer, "OUTPUT_FILE", str(ausgabe))
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", tmp_path / "ausgeschlossen.json")
    monkeypatch.setattr(pfade, "MANUELL_AUSGESCHLOSSEN", tmp_path / "excluded.json")
    monkeypatch.setattr(pfade, "UEBERSPRUNGEN_LOG", tmp_path / "uebersprungen.json")
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["analyzer.py", "--ohne-ki"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def verboten(t):
        raise AssertionError("API-Aufruf im --ohne-ki-Modus")
    monkeypatch.setattr(analyzer, "analyze_therapeut", verboten)

    ergebnis = analyzer.main()
    assert [(r["name"], r["Freie_Plaetze"]) for r in ergebnis] == [("Dipl.-Psych. Eins", False)]
    assert "p.example/2" in (tmp_path / "uebersprungen.json").read_text()
