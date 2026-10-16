"""Tests für analyse_ki.py: Anfrage an Claude, Lesen und Prüfen der Antwort.

Der API-Client ist eine kleine Attrappe, die vorgegebene Antworten liefert
und mitschreibt, was gefragt wurde. Es geht nichts ins Netz.
"""
import json
from types import SimpleNamespace

import analyse_ki
import pytest


class _Client:
    """Gibt die Antworten der Reihe nach zurück. Eine Exception in der Liste
    wird stattdessen geworfen (simuliert einen API-Fehler)."""

    def __init__(self, *antworten):
        self._antworten = list(antworten)
        self.anfragen = []
        self.messages = self

    def create(self, **anfrage):
        self.anfragen.append(anfrage)
        antwort = self._antworten.pop(0)
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


def _antwort(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(text=text)])


def _frage(client, profil=None):
    pausen = []
    ergebnis = analyse_ki.frage_ki(profil or {"name": "Dr. Test"}, client=client, warten=pausen.append)
    return ergebnis, pausen


# ---------- lies_ki_antwort ----------

@pytest.mark.parametrize("rohtext,erwartet", [
    ('{"GKV_akzeptiert": true}', {"GKV_akzeptiert": True}),
    ('```json\n{"GKV_akzeptiert": "unklar"}\n```', {"GKV_akzeptiert": "unklar"}),
    ('Gerne:\n{"GKV_akzeptiert": false}\nViel Erfolg!', {"GKV_akzeptiert": False}),
])
def test_liest_json_auch_mit_text_drumherum(rohtext, erwartet):
    assert analyse_ki.lies_ki_antwort(rohtext) == erwartet


@pytest.mark.parametrize("rohtext", [
    '```json\n{"GKV_akzeptiert": true, "Notiz": "abgesch',   # abgeschnitten
    '{"GKV_akzeptiert": true,,,}',                            # kaputt
    "gar kein JSON", "", None,
])
def test_kaputte_antwort_ergibt_none_statt_absturz(rohtext):
    assert analyse_ki.lies_ki_antwort(rohtext) is None


# ---------- pruefe_bewertung ----------

@pytest.mark.parametrize("gkv", [True, False, "unklar"])
@pytest.mark.parametrize("plaetze", [True, False, "unklar"])
def test_alle_erlaubten_werte_bleiben_erhalten(gkv, plaetze):
    d = {"GKV_akzeptiert": gkv, "Freie_Plaetze": plaetze, "Notiz": "y"}
    assert analyse_ki.pruefe_bewertung(dict(d)) == d


@pytest.mark.parametrize("daten", [
    {"Freie_Plaetze": True},                 # Pflichtfeld fehlt
    {"GKV_akzeptiert": "vielleicht"},        # unerlaubter Wert
    {"GKV_akzeptiert": None},
    "kein dict", None, [1, 2],
])
def test_ungueltige_bewertung_ergibt_none(daten):
    assert analyse_ki.pruefe_bewertung(daten) is None


def test_unerlaubter_wert_bei_freien_plaetzen_wird_unklar():
    assert analyse_ki.pruefe_bewertung({"GKV_akzeptiert": True, "Freie_Plaetze": "vielleicht"})["Freie_Plaetze"] == "unklar"


def test_nur_erlaubte_felder_kommen_durch():
    """Schutz gegen Prompt Injection: zusätzliche Felder aus der Antwort
    (etwa eine fremde E-Mail-Adresse) werden verworfen."""
    boese = {"GKV_akzeptiert": True, "Notiz": "ok", "email": "angreifer@evil.example",
             "name": "Dr. Fake", "profil_url": "https://evil.example/", "Email_generiert": "Text"}
    assert analyse_ki.pruefe_bewertung(boese) == {"GKV_akzeptiert": True, "Notiz": "ok"}


def test_erlaubte_felder_enthalten_keine_kontakt_oder_namensfelder():
    assert analyse_ki.ERLAUBTE_FELDER == {"GKV_akzeptiert", "Freie_Plaetze", "Notiz"}


# ---------- baue_prompt ----------

def test_prompt_enthaelt_profil_und_feldliste():
    prompt = analyse_ki.baue_prompt({"name": "Dr. Test", "volltext": "kurz"})
    assert "Dr. Test" in prompt and "GKV_akzeptiert" in prompt and "kurz" in prompt


def test_prompt_kuerzt_volltext():
    prompt = analyse_ki.baue_prompt({"name": "X", "volltext": "a" * 10000})
    assert "a" * analyse_ki.VOLLTEXT_MAX in prompt
    assert "a" * (analyse_ki.VOLLTEXT_MAX + 1) not in prompt


def test_prompt_ohne_felder():
    assert "GKV_akzeptiert" in analyse_ki.baue_prompt({})


# ---------- frage_ki ----------

def test_frage_ki_schickt_prompt_und_liefert_nur_erlaubte_felder():
    client = _Client(_antwort(json.dumps({"GKV_akzeptiert": True, "Freie_Plaetze": "unklar",
                                          "Notiz": "passt", "email": "angreifer@evil.example"})))
    ergebnis, pausen = _frage(client, {"name": "Dr. Echt"})
    assert ergebnis == {"GKV_akzeptiert": True, "Freie_Plaetze": "unklar", "Notiz": "passt"}
    assert pausen == []
    anfrage = client.anfragen[0]
    assert anfrage["model"] == analyse_ki.MODELL
    assert anfrage["system"] == analyse_ki.SYSTEM_PROMPT
    assert "Dr. Echt" in anfrage["messages"][0]["content"]


def test_frage_ki_versucht_es_nach_fehler_erneut_mit_pause():
    client = _Client(RuntimeError("kurz weg"), _antwort('{"GKV_akzeptiert": "unklar"}'))
    ergebnis, pausen = _frage(client)
    assert ergebnis == {"GKV_akzeptiert": "unklar"}
    assert pausen == [5]


def test_abgeschnittene_antwort_zaehlt_als_fehlversuch():
    client = _Client(_antwort('{"GKV_akzeptiert": true}', stop_reason="max_tokens"),
                     _antwort('{"GKV_akzeptiert": true, "Notiz": "vollständig"}'))
    ergebnis, _ = _frage(client)
    assert ergebnis["Notiz"] == "vollständig"
    assert len(client.anfragen) == 2


def test_nach_drei_fehlversuchen_none_mit_wachsenden_pausen():
    client = _Client(RuntimeError("1"), _antwort("kein JSON"), _antwort("{}"))
    ergebnis, pausen = _frage(client)
    assert ergebnis is None
    assert len(client.anfragen) == 3
    assert pausen == [5, 10]   # nach dem letzten Versuch keine Pause mehr
