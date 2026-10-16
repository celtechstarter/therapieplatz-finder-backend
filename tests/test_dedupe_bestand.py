"""Tests fuer backend/dedupe_bestand.py (Aufraeumen der 88 Alt-Dubletten,
siehe Modul-Docstring dort fuer den Hintergrund)."""

import json

import dedupe_bestand
import pytest
from dedupe_bestand import entscheide, wende_an


def _basis(profil_url, name, adresse, **kwargs):
    e = {
        "profil_url": profil_url,
        "name": name,
        "adresse": adresse,
        "email": "",
        "behandlungsschwerpunkte": [],
        "persoenliches_profil": "",
        "volltext": "",
        "freie_plaetze": "",
    }
    e.update(kwargs)
    return e


def test_keine_dubletten_ohne_gemeinsamen_schluessel():
    a = _basis("https://x/1", "Anna Beispiel", "Beispielstr 1, Dortmund")
    b = _basis("https://x/2", "Peter Muster", "Kaiserstr 5, Dortmund")
    assert entscheide([a, b], set()) == []


def test_reichster_eintrag_gewinnt_ohne_sent_log():
    arm = _basis("https://x/arm", "Herr Markus Muster", "Musterweg 9, Dortmund", email="")
    reich = _basis(
        "https://x/reich", "Dipl.-Psych. Markus Muster", "Musterweg 9, Dortmund",
        email="markus@example.de", behandlungsschwerpunkte=["Depression"],
    )
    entscheidungen = entscheide([arm, reich], set())
    assert len(entscheidungen) == 1
    assert entscheidungen[0]["primary_url"] == "https://x/reich"
    assert entscheidungen[0]["entfernte_urls"] == ["https://x/arm"]


def test_bereits_versendeter_eintrag_bleibt_primary_auch_wenn_aermer():
    versendet = _basis("https://x/versendet", "Anna Beispiel", "Beispielstr 1, Dortmund", email="a@x.de")
    reicher_aber_nicht_versendet = _basis(
        "https://x/reicher", "Frau Anna Beispiel", "Beispielstr 1, Dortmund",
        email="a@x.de", behandlungsschwerpunkte=["Angst", "Depression", "Trauer"],
    )
    entscheidungen = entscheide(
        [versendet, reicher_aber_nicht_versendet], gesendete_urls={"https://x/versendet"}
    )
    assert entscheidungen[0]["primary_url"] == "https://x/versendet"


def test_email_konflikt_wird_erkannt_und_nicht_stillschweigend_aufgeloest():
    a = _basis("https://x/a", "Herr Max Muster", "Testplatz 1, Dortmund", email="a@praxis.de")
    b = _basis("https://x/b", "Max Muster", "Testplatz 1, Dortmund", email="b@praxis.de")
    entscheidungen = entscheide([a, b], set())
    assert entscheidungen[0]["email_konflikt"] is not None
    gewaehlt, alternativen = entscheidungen[0]["email_konflikt"]
    assert alternativen  # die jeweils andere Email landet als Alternative


def test_email_kein_konflikt_wenn_nur_einer_email_hat():
    a = _basis("https://x/a", "Herr Max Muster", "Testplatz 1, Dortmund", email="")
    b = _basis("https://x/b", "Max Muster", "Testplatz 1, Dortmund", email="b@praxis.de")
    entscheidungen = entscheide([a, b], set())
    assert entscheidungen[0]["email_konflikt"] is None


def test_wende_an_entfernt_dubletten_und_fuellt_fehlende_felder_auf():
    # "mit_email" gewinnt (Email zaehlt am meisten in der Score-Funktion),
    # bekommt aber die Schwerpunkte des verworfenen Duplikats aufgefuellt,
    # weil es selbst keine hatte.
    mit_email = _basis(
        "https://x/mit-email", "Herr Markus Muster", "Musterweg 9, Dortmund",
        email="markus@example.de",
    )
    mit_schwerpunkten = _basis(
        "https://x/mit-schwerpunkten", "Dipl.-Psych. Markus Muster", "Musterweg 9, Dortmund",
        email="", behandlungsschwerpunkte=["Depression"],
    )
    entscheidungen = entscheide([mit_email, mit_schwerpunkten], set())
    ergebnis = wende_an([mit_email, mit_schwerpunkten], entscheidungen)

    assert len(ergebnis) == 1
    uebrig = ergebnis[0]
    assert uebrig["profil_url"] == "https://x/mit-email"
    assert uebrig["email"] == "markus@example.de"
    # fehlende Schwerpunkte wurden aus dem entfernten Duplikat aufgefuellt:
    assert uebrig["behandlungsschwerpunkte"] == ["Depression"]


def test_wende_an_setzt_warnhinweis_bei_email_konflikt():
    a = _basis("https://x/a", "Herr Max Muster", "Testplatz 1, Dortmund", email="a@praxis.de")
    b = _basis("https://x/b", "Max Muster", "Testplatz 1, Dortmund", email="b@praxis.de")
    entscheidungen = entscheide([a, b], set())
    ergebnis = wende_an([a, b], entscheidungen)

    assert len(ergebnis) == 1
    warnungen = ergebnis[0].get("filter_warnungen") or []
    assert any("abweichende Email" in w for w in warnungen)


def test_erkennt_dublette_ueber_telefon_trotz_abweichender_adresse():
    # Nutzer-Meldung 23.9.2026: zwei komplett unterschiedliche
    # Adressen im System, aber identische Telefonnummer (nur unterschiedlich
    # geschrieben) UND identische Email -- der reine Adress-Schluessel haette
    # das nicht erkannt.
    a = _basis(
        "https://x/quelle-a", "Dipl.-Psych. Erika Beispiel", "Testplatz 1, 44135 Dortmund",
        telefon="+49(231)999901", email="erika.beispiel@example.de",
    )
    b = _basis(
        "https://x/quelle-b", "Erika Beispiel", "Musterweg 2, 44135 Dortmund",
        telefon="0231 999901", email="erika.beispiel@example.de",
    )
    entscheidungen = entscheide([a, b], set())
    assert len(entscheidungen) == 1
    assert sorted(entscheidungen[0]["entfernte_urls"] + [entscheidungen[0]["primary_url"]]) == [
        "https://x/quelle-a", "https://x/quelle-b",
    ]


def test_telefon_gleich_aber_name_unterschiedlich_bleibt_getrennt():
    # Zwei verschiedene Personen in derselben Praxis teilen sich die
    # Sammel-Telefonnummer der Rezeption -- das darf NICHT als Dublette
    # gelten, weil die Namen nicht uebereinstimmen.
    a = _basis("https://x/a", "Anna Beispiel", "Testplatz 1, Dortmund", telefon="0231 999901")
    b = _basis("https://x/b", "Peter Muster", "Testplatz 1, Dortmund", telefon="0231 999901")
    assert entscheide([a, b], set()) == []


def test_wende_an_ist_konsistent_zwischen_raw_und_analysiert():
    # Dieselbe Entscheidung (getroffen auf den "analysierten" Daten) muss
    # auf einer zweiten Liste (z.B. results_raw.json mit denselben URLs,
    # aber weniger Feldern) dieselbe URL behalten.
    arm_analysiert = _basis("https://x/arm", "Herr Markus Muster", "Musterweg 9, Dortmund")
    reich_analysiert = _basis(
        "https://x/reich", "Dipl.-Psych. Markus Muster", "Musterweg 9, Dortmund",
        email="markus@example.de",
    )
    entscheidungen = entscheide([arm_analysiert, reich_analysiert], set())

    arm_raw = {"profil_url": "https://x/arm", "name": "Herr Markus Muster", "adresse": "Musterweg 9, Dortmund"}
    reich_raw = {"profil_url": "https://x/reich", "name": "Dipl.-Psych. Markus Muster", "adresse": "Musterweg 9, Dortmund"}
    ergebnis_raw = wende_an([arm_raw, reich_raw], entscheidungen)

    assert len(ergebnis_raw) == 1
    assert ergebnis_raw[0]["profil_url"] == "https://x/reich"


# ---------- Durchlauf 2: Dubletten nur in den Rohdaten (4.10.2026) ----------



def test_analysierter_eintrag_gewinnt_auch_gegen_reicheren_rohdaten_eintrag():
    analysiert = _basis("u-app", "Frau Lena Beispiel", "Am Testwall 10, 44137 Dortmund")
    reicher = _basis("u-roh", "Dipl.-Psych. Lena Beispiel", "Am Testwall 10, 44137 Dortmund",
                     email="lena@praxis-beispiel.de", persoenliches_profil="x" * 500)
    e = entscheide([reicher, analysiert], set(), analysierte_urls={"u-app"})
    assert e[0]["primary_url"] == "u-app"
    assert e[0]["entfernte_urls"] == ["u-roh"]


def test_angeschrieben_schlaegt_analysiert():
    a = _basis("u-gesendet", "Lena Beispiel", "Am Testwall 10, 44137 Dortmund")
    b = _basis("u-app", "Lena Beispiel", "Am Testwall 10, 44137 Dortmund")
    e = entscheide([a, b], {"u-gesendet"}, analysierte_urls={"u-app"})
    assert e[0]["primary_url"] == "u-gesendet"


def test_main_fuehrt_dubletten_nur_in_rohdaten_zusammen(tmp_path, monkeypatch):
    raw_datei, an_datei = tmp_path / "raw.json", tmp_path / "an.json"
    app = _basis("u-app", "Frau Lena Beispiel", "Am Testwall 10, 44137 Dortmund")
    register = _basis("u-register", "Dipl.-Psych. Lena Beispiel", "Am Testwall 10, 44137 Dortmund",
                      abrechnungsarten=["Gesetzliche Krankenversicherung"])
    zwei_roh_a = _basis("u-a", "Max Muster", "Weg 1, 44135 Dortmund")
    zwei_roh_b = _basis("u-b", "Max Muster", "Weg 1, 44135 Dortmund", email="max@praxis-muster.de")
    anders = _basis("u-anders", "Anke Muster", "Weg 1, 44135 Dortmund")
    raw_datei.write_text(json.dumps([app, register, zwei_roh_a, zwei_roh_b, anders]), encoding="utf-8")
    an_datei.write_text(json.dumps([dict(app, GKV_akzeptiert=True)]), encoding="utf-8")
    monkeypatch.setattr(dedupe_bestand, "RESULTS_RAW", raw_datei)
    monkeypatch.setattr(dedupe_bestand, "RESULTS_ANALYZED", an_datei)
    monkeypatch.setattr(dedupe_bestand, "SENT_LOG", tmp_path / "sent.json")

    dedupe_bestand.main()

    roh = {e["profil_url"]: e for e in json.loads(raw_datei.read_text())}
    assert set(roh) == {"u-app", "u-b", "u-anders"}
    # Die Kassen-Bestaetigung aus dem Register landet beim App-Eintrag.
    assert roh["u-app"]["abrechnungsarten"] == ["Gesetzliche Krankenversicherung"]
    assert [a["profil_url"] for a in json.loads(an_datei.read_text())] == ["u-app"]


def test_main_ohne_dubletten_schreibt_nichts(tmp_path, monkeypatch, capsys):
    raw_datei = tmp_path / "raw.json"
    raw_datei.write_text(json.dumps([_basis("u1", "A B", "Weg 1, 44135 Dortmund")]), encoding="utf-8")
    vorher = raw_datei.stat().st_mtime_ns
    monkeypatch.setattr(dedupe_bestand, "RESULTS_RAW", raw_datei)
    monkeypatch.setattr(dedupe_bestand, "RESULTS_ANALYZED", tmp_path / "an.json")
    monkeypatch.setattr(dedupe_bestand, "SENT_LOG", tmp_path / "sent.json")
    dedupe_bestand.main()
    assert "nichts zu tun" in capsys.readouterr().out
    assert raw_datei.stat().st_mtime_ns == vorher


def test_main_entfernt_im_rohdaten_durchlauf_nie_einen_app_eintrag(tmp_path, monkeypatch):
    """Zwei App-Eintraege, die nur ueber die Rohdaten (hier: gleiche Email)
    als dieselbe Person erkennbar sind: beide bleiben stehen, nur der reine
    Rohdaten-Eintrag wird zusammengefuehrt."""
    raw_datei, an_datei = tmp_path / "raw.json", tmp_path / "an.json"
    app1 = _basis("u-app1", "Dr. Kai Beispiel", "Weg 1, 44135 Dortmund", email="kai@praxis.de")
    app2 = _basis("u-app2", "Herr Dr. Kai Beispiel", "Weg 1a, 44135 Dortmund", email="kai@praxis.de")
    roh = _basis("u-roh", "Kai Beispiel", "Weg 1, 44135 Dortmund")
    raw_datei.write_text(json.dumps([app1, app2, roh]), encoding="utf-8")
    # Die analysierten Kopien haben keine Email -> Durchlauf 1 erkennt nichts.
    an_datei.write_text(json.dumps([dict(app1, email=""), dict(app2, email="")]), encoding="utf-8")
    monkeypatch.setattr(dedupe_bestand, "RESULTS_RAW", raw_datei)
    monkeypatch.setattr(dedupe_bestand, "RESULTS_ANALYZED", an_datei)
    monkeypatch.setattr(dedupe_bestand, "SENT_LOG", tmp_path / "sent.json")

    dedupe_bestand.main()

    assert {e["profil_url"] for e in json.loads(raw_datei.read_text())} == {"u-app1", "u-app2"}
    assert len(json.loads(an_datei.read_text())) == 2


# ---------- Zusammenführen im Detail ----------

def test_vorhandene_werte_des_primary_werden_nie_ueberschrieben():
    primary = _basis("https://x/p", "Anna Beispiel", "Beispielstr 1, Dortmund",
                     email="a@praxis.de", telefon="0231 1", website="")
    andere = _basis("https://x/a", "Frau Anna Beispiel", "Beispielstr 1, Dortmund",
                    email="", telefon="0231 2", website="https://anna-praxis.de",
                    behandlungsschwerpunkte=None, abrechnungsarten=["Selbstzahler"])
    [ergebnis] = wende_an([primary, andere], entscheide([primary, andere], set()))
    assert ergebnis["telefon"] == "0231 1"                     # bleibt
    assert ergebnis["website"] == "https://anna-praxis.de"     # war leer -> aufgefüllt
    assert ergebnis["abrechnungsarten"] == ["Selbstzahler"]    # Liste vereinigt
    assert ergebnis["behandlungsschwerpunkte"] == []           # None in der Dublette stört nicht


def test_gleiche_email_verbindet_trotz_anderer_adresse_und_telefon():
    a = _basis("https://x/a", "Anna Beispiel", "Beispielstr 1, Dortmund", email="Praxis@Beispiel-Anna.de", telefon="0231 1")
    b = _basis("https://x/b", "Dipl.-Psych. Anna Beispiel", "Ganz woanders 9, Unna", email="praxis@beispiel-anna.de ",
               telefon="02303 2")
    [entscheidung] = entscheide([a, b], set())
    assert sorted([entscheidung["primary_url"], *entscheidung["entfernte_urls"]]) == ["https://x/a", "https://x/b"]
    assert entscheidung["email_konflikt"] is None   # gleiche Adresse, nur andere Schreibweise


def test_gleiche_email_bei_anderem_namen_verbindet_nicht():
    a = _basis("https://x/a", "Anna Beispiel", "A-Str 1, Dortmund", email="team@praxis.de")
    b = _basis("https://x/b", "Peter Muster", "B-Str 2, Dortmund", email="team@praxis.de")
    assert entscheide([a, b], set()) == []


def test_konflikt_nennt_nur_die_wirklich_anderen_adressen():
    primary = _basis("https://x/p", "Anna Beispiel", "Beispielstr 1, Dortmund", email="ANNA@praxis.de",
                     volltext="x" * 500)
    b = _basis("https://x/b", "Anna Beispiel", "Beispielstr 1, Dortmund", email="anna@andere.de")
    [e] = entscheide([primary, b], set())
    assert e["primary_url"] == "https://x/p"
    assert e["email_konflikt"] == ("anna@praxis.de", ["anna@andere.de"])


def test_warnhinweis_bleibt_einmalig_und_alte_warnungen_bleiben_erhalten():
    primary = _basis("https://x/p", "Anna Beispiel", "Beispielstr 1, Dortmund", email="a@eins.de",
                     filter_warnungen=["alte Warnung"], volltext="lang" * 100)
    b = _basis("https://x/b", "Anna Beispiel", "Beispielstr 1, Dortmund", email="a@zwei.de")
    entscheidungen = entscheide([primary, b], set())
    einmal = wende_an([dict(primary), dict(b)], entscheidungen)
    zweimal = wende_an([dict(einmal[0]), dict(b)], entscheidungen)
    warnungen = zweimal[0]["filter_warnungen"]
    assert warnungen[0] == "alte Warnung"
    assert len(warnungen) == 2 and "a@zwei.de" in warnungen[1]


@pytest.mark.parametrize("reicher", [
    {"volltext": "x" * 50},
    {"persoenliches_profil": "x" * 50},
    {"behandlungsschwerpunkte": ["Depression", "Angst"]},
    {"freie_plaetze": "Wartezeit 3 Monate"},
    {"email": "a@praxis.de"},
])
def test_reicherer_eintrag_gewinnt(reicher):
    arm = _basis("https://x/arm", "Anna Beispiel", "Beispielstr 1, Dortmund")
    reich = _basis("https://x/reich", "Anna Beispiel", "Beispielstr 1, Dortmund", **reicher)
    for reihenfolge in ([arm, reich], [reich, arm]):
        assert entscheide(reihenfolge, set())[0]["primary_url"] == "https://x/reich"
