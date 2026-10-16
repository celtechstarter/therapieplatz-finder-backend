"""Tests für email_suche.py: fehlende E-Mail-Adressen ergänzen.

Browser und DNS sind Attrappen (siehe attrappen.py), es geht nichts ins Netz.
"""
import asyncio
import json

import email_suche as suche
import pytest
from attrappen import FakePage, FakePlaywright


async def _keine_pause(*a, **k):
    return None


# ---------- saubere_email ----------

@pytest.mark.parametrize("adresse", [
    "praxis@example-praxis.de",
    "praxis@beispiel.info",                         # .info ist eine echte Endung
    "kontakt@wixpressberatung-praxis.de",           # nur exakte Endungen sind gesperrt
])
def test_echte_adressen_bleiben(adresse):
    assert suche.saubere_email(adresse) == adresse


@pytest.mark.parametrize("roh,erwartet", [
    ("praxis@example-praxis.de.", "praxis@example-praxis.de"),
    ("praxis@example-praxis.de)", "praxis@example-praxis.de"),
    ("  praxis%40example-praxis.de ", "praxis@example-praxis.de"),   # URL-kodiert
])
def test_satzzeichen_und_kodierung_werden_bereinigt(roh, erwartet):
    assert suche.saubere_email(roh) == erwartet


@pytest.mark.parametrize("adresse", [
    "605a7baede844d278b89dc95ae0a9123@sentry-next.wixpress.com",   # Tracking, als Subdomain
    "noreply@praxis.de", "ihre-mail@praxis.de",                     # Platzhalter vor dem @
    "info@example.com", "max.mustermann@beispiel.de",               # Platzhalter-Domains
    "kunden@microsoft.com", "jemand@amazon.de", "kontakt@outlook.com",
    "info@baby-vornamen.de", "kontakt@gala.de", "general@crazygames.com",
    "logo@2x.png", "icon@3x.svg",                                   # Bilddateien
    "kein-email", "",
])
def test_unechte_adressen_werden_verworfen(adresse):
    assert suche.saubere_email(adresse) is None


# ---------- email_und_website_aus_text ----------

def test_text_mit_email_und_website():
    assert suche.email_und_website_aus_text(
        "Kontakt: info@praxis-muster.de, https://praxis-muster.de/kontakt") == (
        "info@praxis-muster.de", "https://praxis-muster.de/kontakt")


def test_www_bekommt_https_davor():
    assert suche.email_und_website_aus_text("Mehr unter www.praxis-schmidt.de")[1] == "https://www.praxis-schmidt.de"


def test_karten_und_therapie_de_links_sind_keine_website():
    """Fehler, der beim Umbau aufgefallen ist: Früher wurde der erste
    beliebige Link im Text zur "Website", auch ein Kartenlink."""
    text = ("Karte: https://www.google.com/maps/search/?api=1 Profil: https://www.therapie.de/profil/x/ "
            "Praxis: https://praxis-echt.de")
    assert suche.email_und_website_aus_text(text)[1] == "https://praxis-echt.de"


def test_gesperrte_adresse_wird_uebersprungen_die_naechste_genommen():
    assert suche.email_und_website_aus_text("noreply@praxis.de oder info@praxis-muster.de")[0] == "info@praxis-muster.de"


def test_leerer_text():
    assert suche.email_und_website_aus_text("") == (None, None)


# ---------- ergaenze_aus_text (Stufe 1, ohne Netz) ----------

def test_stufe_eins_ergaenzt_nur_was_fehlt():
    profile = [
        {"email": "noreply@example.com", "volltext": "Mail: praxis-a@praxis-a.de"},   # ungültig -> ersetzt
        {"volltext": "Website: www.praxis-b.de"},                                     # nur Website
        {"email": "c@praxis-c.de", "website": "https://alt.de", "volltext": "neu@x-praxis.de https://neu.de"},
    ]
    assert suche.ergaenze_aus_text(profile) == (1, 1)
    assert profile[0]["email"] == "praxis-a@praxis-a.de"
    assert profile[1]["website"] == "https://www.praxis-b.de" and not profile[1].get("email")
    assert profile[2]["email"] == "c@praxis-c.de" and profile[2]["website"] == "https://alt.de"


def test_nur_profile_ohne_email_mit_website_brauchen_die_websuche():
    profile = [{"email": "a@b-praxis.de", "website": "https://x.de"}, {"website": "https://y.de"}, {}]
    assert suche.braucht_websuche(profile) == [{"website": "https://y.de"}]


# ---------- Suche auf der Website ----------

def test_mailto_link_hat_vorrang_vor_dem_seitentext(fake_dns):
    page = FakePage({"https://praxis-beispiel.de/": {
        "mailto": ["mailto:noreply@praxis.de", "mailto:info@praxis-beispiel.de?subject=Hallo"],
        "html": "text@praxis-beispiel.de"}})
    assert asyncio.run(suche.email_auf_website(page, "https://praxis-beispiel.de/")) == "info@praxis-beispiel.de"


def test_email_steht_erst_auf_der_kontaktseite(fake_dns):
    page = FakePage({
        "https://praxis-beispiel.de/": {"html": "Willkommen", "unterseiten": [
            "http://127.0.0.1/kontakt",                  # intern: wird nie besucht
            "https://praxis-beispiel.de/laedt-nicht",
            "https://praxis-beispiel.de/kontakt"]},
        "https://praxis-beispiel.de/laedt-nicht": {"fehler": True},
        "https://praxis-beispiel.de/kontakt": {"html": "Schreiben Sie an info@praxis-beispiel.de"},
    })
    pausen = []

    async def pause(s):
        pausen.append(s)
    assert asyncio.run(suche.email_auf_website(page, "https://praxis-beispiel.de/", pause=pause)) == "info@praxis-beispiel.de"
    assert "http://127.0.0.1/kontakt" not in page.besucht
    assert len(pausen) == 2 and all(1.0 <= p <= 2.0 for p in pausen)   # Pause vor jeder Unterseite


def test_weiterleitung_ins_interne_netz_wird_nicht_gelesen(fake_dns):
    page = FakePage({"https://praxis-beispiel.de/": {"weiterleitung": "http://127.0.0.1:8080/",
                                                     "html": "info@praxis-beispiel.de"}})
    assert asyncio.run(suche.email_auf_website(page, "https://praxis-beispiel.de/")) is None


@pytest.mark.parametrize("seiten,url", [
    ({"https://praxis-beispiel.de/": {"fehler": True}}, "https://praxis-beispiel.de/"),
    ({}, "http://127.0.0.1/"),
])
def test_unerreichbare_oder_interne_website_ergibt_none(fake_dns, seiten, url):
    page = FakePage(seiten)
    assert asyncio.run(suche.email_auf_website(page, url)) is None
    assert "http://127.0.0.1/" not in page.besucht


def test_keine_email_auf_website_und_unterseiten(fake_dns):
    page = FakePage({"https://praxis-beispiel.de/": {"html": "nichts", "unterseiten": ["https://praxis-beispiel.de/kontakt"]},
                     "https://praxis-beispiel.de/kontakt": {"html": "auch nichts"}})
    assert asyncio.run(suche.email_auf_website(page, "https://praxis-beispiel.de/", pause=_keine_pause)) is None


# ---------- ergaenze_emails: Gesamtablauf ----------

def _lauf(tmp_path, monkeypatch, profile, seiten, schliessen_fehler=False):
    datei = tmp_path / "roh.json"
    datei.write_text(json.dumps(profile), encoding="utf-8")
    fake = FakePlaywright(FakePage(seiten), schliessen_fehler=schliessen_fehler)
    monkeypatch.setattr(suche, "async_playwright", fake)
    asyncio.run(suche.ergaenze_emails(datei, pause=_keine_pause))
    return json.loads(datei.read_text(encoding="utf-8")), fake


def test_gesamtablauf_besucht_nur_die_eigenen_praxis_websites(tmp_path, monkeypatch, fake_dns):
    """Stufe 1 füllt aus dem Text, Stufe 2 besucht genau die Website aus dem
    Profil, keine Suchmaschine und nichts anderes."""
    profile = [{"name": "A", "volltext": "Mail: praxis-a@praxis-a.de"},
               {"name": "B", "volltext": "Website: www.praxis-b.de"},
               {"name": "C", "email": "c@praxis-c.de", "website": "https://praxis-c.de"}]
    ergebnis, fake = _lauf(tmp_path, monkeypatch, profile,
                           {"https://www.praxis-b.de": {"html": "kontakt@praxis-b.de"}})
    assert [p.get("email") for p in ergebnis] == ["praxis-a@praxis-a.de", "kontakt@praxis-b.de", "c@praxis-c.de"]
    assert fake.page.besucht == ["https://www.praxis-b.de"]
    assert fake.geschlossen


def test_gesamtablauf_schuetzt_vor_der_ersten_navigation(tmp_path, monkeypatch, fake_dns):
    ergebnis, fake = _lauf(tmp_path, monkeypatch, [{"name": "B", "website": "https://praxis-b.de/"}],
                           {"https://praxis-b.de/": {"html": "kontakt@praxis-b.de"}})
    assert fake.protokoll[:2] == [("route", "**/*"), ("new_page",)]
    assert fake.page.besucht == ["https://praxis-b.de/"]
    assert ergebnis[0]["email"] == "kontakt@praxis-b.de"
    assert fake.start_optionen == {"headless": True}


def test_gesamtablauf_speichert_auch_wenn_der_browser_haengt(tmp_path, monkeypatch, fake_dns):
    ergebnis, _ = _lauf(tmp_path, monkeypatch, [{"name": "B", "website": "https://praxis-b.de/"}],
                        {"https://praxis-b.de/": {"html": "kontakt@praxis-b.de"}}, schliessen_fehler=True)
    assert ergebnis[0]["email"] == "kontakt@praxis-b.de"


def test_gesamtablauf_ohne_websites_startet_keinen_browser(tmp_path, monkeypatch):
    datei = tmp_path / "roh.json"
    datei.write_text(json.dumps([{"email": "a@praxis-a.de"}]), encoding="utf-8")
    monkeypatch.setattr(suche, "async_playwright", lambda: pytest.fail("kein Browser erwartet"))
    asyncio.run(suche.ergaenze_emails(datei))
    assert json.loads(datei.read_text(encoding="utf-8")) == [{"email": "a@praxis-a.de"}]


def test_gesamtablauf_fehlende_datei(tmp_path, capsys):
    asyncio.run(suche.ergaenze_emails(tmp_path / "fehlt.json"))
    assert "nicht gefunden" in capsys.readouterr().out
    assert not (tmp_path / "fehlt.json").exists()


def test_websuche_zaehlt_treffer_und_speichert_alle_fuenf_websites(tmp_path, monkeypatch, fake_dns):
    seiten = {f"https://praxis-beispiel.de/{i}": {"html": f"info{i}@praxis-beispiel.de" if i % 2 else "nichts"}
              for i in range(6)}
    profile = [{"name": str(i), "website": f"https://praxis-beispiel.de/{i}"} for i in range(6)]
    fake = FakePlaywright(FakePage(seiten))
    monkeypatch.setattr(suche, "async_playwright", fake)
    gespeichert = []
    monkeypatch.setattr(suche, "json_atomar_schreiben", lambda datei, daten: gespeichert.append(datei))
    gefunden = asyncio.run(suche.ergaenze_von_websites(profile, profile, "ziel.json", pause=_keine_pause))
    assert gefunden == 3
    assert [p.get("email") for p in profile] == [None, "info1@praxis-beispiel.de", None,
                                                 "info3@praxis-beispiel.de", None, "info5@praxis-beispiel.de"]
    assert gespeichert == ["ziel.json", "ziel.json"]   # nach der 5. Website und am Ende
