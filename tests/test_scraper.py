"""Tests für scraper.py (therapie.de).

Die meisten Tests nutzen Browser-Attrappen (attrappen.py). Das Auslesen
einer Profilseite (`lies_profil`) wird mit einem echten, lokalen Chromium
geprüft, ohne Internet: das HTML wird direkt in die Seite geladen, jede
Netzwerkanfrage abgebrochen. Ohne installiertes Chromium werden diese
Tests übersprungen (in der CI ist es installiert).
"""
import asyncio
import json

import pytest

import scraper
from attrappen import FakePage, FakePlaywright


# ---------- oeffne_seite: Sperren erkennen ----------

@pytest.mark.parametrize("status", [403, 429])
def test_sperre_am_statuscode(status):
    with pytest.raises(scraper.BanVerdacht):
        asyncio.run(scraper.oeffne_seite(FakePage({"https://x.de/": {"status": status}}), "https://x.de/"))


@pytest.mark.parametrize("text", ["Bitte bestätigen: Ich bin kein Roboter", "Our systems detected unusual traffic",
                                  "<h1>Access Denied</h1>"])
def test_sperre_am_seiteninhalt(text):
    with pytest.raises(scraper.BanVerdacht):
        asyncio.run(scraper.oeffne_seite(FakePage({"https://x.de/": {"html": text}}), "https://x.de/"))


def test_normale_seite():
    assert asyncio.run(scraper.oeffne_seite(FakePage(), "https://x.de/")).status == 200


# ---------- Suchergebnisse ----------

def test_alle_profil_urls_ueber_mehrere_seiten_und_orte(keine_pausen):
    dortmund, unna = scraper.such_url("Dortmund"), scraper.such_url("Unna")
    seite2 = dortmund + "&page=2"
    page = FakePage({
        dortmund: {"links": ["https://www.therapie.de/profil/a/", "https://www.therapie.de/profil/a/info/"],
                   "weiter": "/therapeutensuche/ergebnisse/?ort=Dortmund&page=2"},   # relativer Link
        seite2: {"links": ["https://www.therapie.de/profil/b/"], "weiter": dortmund},   # verweist zurück
        unna: {"links": ["https://www.therapie.de/profil/b/", "https://www.therapie.de/profil/c/"]},
    })
    urls = asyncio.run(scraper.alle_profil_urls(page, ["Dortmund", "Unna"]))
    assert urls == ["https://www.therapie.de/profil/a/", "https://www.therapie.de/profil/b/",
                    "https://www.therapie.de/profil/c/"]                 # ohne /info/, ohne Doppelte
    assert page.besucht == [dortmund, seite2, unna]                      # Kreis erkannt


def test_kein_weiter_link_beendet_den_ort(keine_pausen):
    page = FakePage({scraper.such_url("Dortmund"): {"links": ["https://www.therapie.de/profil/a/"]}})
    assert asyncio.run(scraper.alle_profil_urls(page, ["Dortmund"])) == ["https://www.therapie.de/profil/a/"]
    assert page.besucht == [scraper.such_url("Dortmund")]


def test_absoluter_weiter_link_bleibt_wie_er_ist():
    page = FakePage({"u": {"weiter": "https://www.therapie.de/seite2"}})
    page.url = "u"
    assert asyncio.run(scraper.naechste_suchseite(page)) == "https://www.therapie.de/seite2"


def test_leere_suchseite():
    assert asyncio.run(scraper.profil_links(FakePage({"leer": {"links": []}}), "leer")) == []


def test_such_url_kodiert_umlaute():
    assert scraper.such_url("Bönen").endswith("?ort=B%C3%B6nen")


# ---------- Text-Auswertung ----------

def test_freie_plaetze_nur_die_zeile_unter_der_ueberschrift():
    text = "Einzeltherapie: Erwachsene\nFreie Plätze / Wartezeiten\nWartezeit über zwölf Monate.\nMitgliedschaften"
    assert scraper.freie_plaetze_aus_text(text) == "Wartezeit über zwölf Monate"
    assert scraper.freie_plaetze_aus_text("Freie Plätze / Wartezeiten\nFreie Plätze vorhanden.\n") == "freie Plätze"
    assert scraper.freie_plaetze_aus_text("ohne den Abschnitt") == ""
    assert scraper.freie_plaetze_aus_text(None) == ""


def test_aufnahmestopp_mit_zitat():
    gefunden, zitat = scraper.finde_aufnahmestopp(
        "Willkommen. Wir nehmen derzeit keine neuen Patienten auf. Bitte später anfragen.")
    assert gefunden and zitat == "Wir nehmen derzeit keine neuen Patienten auf."


def test_aufnahmestopp_am_textanfang_und_ohne_satzende():
    assert scraper.finde_aufnahmestopp("Aufnahmestopp bis Sommer") == (True, "Aufnahmestopp bis Sommer")


def test_aufnahmestopp_zitat_bleibt_zeichengenau():
    text = "İstanbul-Praxis. Derzeit Aufnahmestopp für Erwachsene.\nKontakt"
    gefunden, zitat = scraper.finde_aufnahmestopp(text)
    assert gefunden and zitat == "Derzeit Aufnahmestopp für Erwachsene." and zitat in text


def test_kein_aufnahmestopp():
    assert scraper.finde_aufnahmestopp("Freie Plätze vorhanden.") == (False, "")


def test_bekannte_urls_ignoriert_kaputte_eintraege():
    assert scraper.bekannte_urls([{"profil_url": "u1"}, {"name": "ohne url"}, "kein dict", {"profil_url": ""}]) == {"u1"}


# ---------- Gesamtlauf ----------

@pytest.fixture
def lauf(tmp_path, monkeypatch, keine_pausen):
    datei = tmp_path / "roh.json"
    fake = FakePlaywright()
    monkeypatch.setattr(scraper, "async_playwright", fake)

    def starte(urls, profil_fn, vorher=None, neu=False):
        if vorher is not None:
            datei.write_text(json.dumps(vorher), encoding="utf-8")

        async def alle(page, orte=None):
            return urls

        async def laden(page, url):
            return profil_fn(url)
        monkeypatch.setattr(scraper, "alle_profil_urls", alle)
        monkeypatch.setattr(scraper, "profil_laden", laden)
        return asyncio.run(scraper.main(neu=neu, datei=datei))
    starte.datei, starte.fake = datei, fake
    return starte


def test_lauf_ueberspringt_bekannte_profile_und_speichert(lauf):
    geholt = []
    ergebnis = lauf(["u1", "u2", "u3"], lambda u: geholt.append(u) or (None if u == "u3" else {"profil_url": u}),
                    vorher=[{"profil_url": "u1", "name": "Alt"}])
    assert geholt == ["u2", "u3"]
    assert [p["profil_url"] for p in ergebnis] == ["u1", "u2"]
    assert json.loads(lauf.datei.read_text()) == ergebnis
    assert lauf.fake.geschlossen


def test_lauf_neu_ignoriert_alten_stand(lauf):
    assert lauf(["u1"], lambda u: {"profil_url": u, "name": "frisch"}, vorher=[{"profil_url": "u1"}], neu=True) == [
        {"profil_url": "u1", "name": "frisch"}]


def test_lauf_speichert_alle_fuenf_profile(lauf, monkeypatch):
    gespeichert = []
    monkeypatch.setattr(scraper, "json_atomar_schreiben", lambda d, p: gespeichert.append(len(p)))
    lauf([f"u{i}" for i in range(11)], lambda u: {"profil_url": u})
    assert gespeichert == [5, 10, 11]   # nach 5, nach 10 und am Ende


def test_lauf_stoppt_bei_sperre_und_behaelt_fortschritt(lauf, capsys):
    def profil(u):
        if u == "u2":
            raise scraper.BanVerdacht("HTTP 429")
        return {"profil_url": u}
    assert lauf(["u1", "u2", "u3"], profil) == [{"profil_url": "u1"}]
    assert json.loads(lauf.datei.read_text()) == [{"profil_url": "u1"}]
    assert "STOPP" in capsys.readouterr().out
    assert lauf.fake.geschlossen


def test_lauf_speichert_auch_bei_abbruch_und_haengendem_browser(lauf):
    lauf.fake.schliessen_fehler = True

    def profil(u):
        if u == "u2":
            raise KeyboardInterrupt
        return {"profil_url": u}
    with pytest.raises(KeyboardInterrupt):
        lauf(["u1", "u2"], profil)
    assert json.loads(lauf.datei.read_text()) == [{"profil_url": "u1"}]


def test_browser_gibt_sich_als_automatisiert_zu_erkennen(lauf):
    """Keine Tricks gegen Bot-Erkennung (entfernt 5.10.2026): keine
    Start-Argumente wie --disable-blink-features und keine eingeschleusten
    Skripte, die navigator.webdriver verstecken."""
    lauf(["u1"], lambda u: {"profil_url": u})
    assert lauf.fake.start_optionen == {"headless": True}
    assert not [e for e in lauf.fake.protokoll if e[0] == "init_script"]
    assert lauf.fake.kontext_optionen == {"user_agent": scraper.USER_AGENT, "locale": "de-DE"}


def test_lauf_setzt_standardmaessig_fort(lauf, monkeypatch):
    """Ohne --neu bleibt der bisherige Stand erhalten (Fortsetzen)."""
    lauf.datei.write_text(json.dumps([{"profil_url": "alt"}]), encoding="utf-8")

    async def alle(page, orte=None):
        return ["alt"]
    monkeypatch.setattr(scraper, "alle_profil_urls", alle)
    assert asyncio.run(scraper.main(datei=lauf.datei)) == [{"profil_url": "alt"}]


def test_profil_laden_liefert_das_ausgelesene_profil(monkeypatch):
    async def lies(page, url):
        return {"profil_url": url, "name": "X"}
    monkeypatch.setattr(scraper, "lies_profil", lies)
    page = FakePage({"u": {"links": ["profilblock"]}})   # wait_for_selector findet etwas
    assert asyncio.run(scraper.profil_laden(page, "u")) == {"profil_url": "u", "name": "X"}


def test_profil_laden_bei_ladefehler_none_bei_sperre_abbruch():
    page = FakePage({"kaputt": {"fehler": True}, "gesperrt": {"status": 429}})
    assert asyncio.run(scraper.profil_laden(page, "kaputt")) is None
    with pytest.raises(scraper.BanVerdacht):
        asyncio.run(scraper.profil_laden(page, "gesperrt"))


# ---------- lies_profil mit echtem (lokalem) Chromium ----------

PROFIL = """<html><body><h1>Dipl.-Psych. Erika Beispiel</h1>
<div class="therapist-details">Erika Beispiel<br>Psychologische Psychotherapeutin
 <span itemprop="streetAddress">Musterweg 1</span> <span itemprop="postalCode">59174</span>
 <span itemprop="addressLocality">Kamen</span> <span itemprop="telephone">02307 123</span>
 <a href="https://www.therapie.de/profil/x/">therapie.de</a>
 <a href="https://www.google.com/maps/search/?api=1">Karte</a>
 <a href="https://praxis-beispiel.de">Website</a>
 <a href="mailto:praxis@beispiel-kamen.de?subject=Anfrage">Mail</a></div>
<div class="therapist-details"><div id="abrechnungsverfahren">Kassenleistung, Selbstzahler</div>
 <h4>Behandlungs-Schwerpunkte</h4><ul><li>Depression</li><li>Angst</li></ul>
 <h4>Therapie-Angebot</h4><ul><li>Einzeltherapie: Erwachsene</li></ul>
 <h4>Freie Plätze / Wartezeiten</h4>
Wartezeit über drei Monate.</div>
<div class="therapist-details"><h4>Persönliches Profil</h4><p>Ich nehme derzeit keine neuen Patienten auf.</p></div>
</body></html>"""

OHNE_MIKRODATEN = """<html><body><h1>Praxis Muster</h1>
<div class="therapist-details">Praxis Muster<br>Psychotherapeutin<br>Teststraße 5<br>44135 Dortmund<br>2. OG<br>0231 999</div>
<div class="therapist-details"><div id="abrechnungsverfahren"></div></div></body></html>"""


def _lies(html):
    async def lauf():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                kontext = await browser.new_context(java_script_enabled=False)
                await kontext.route("**/*", lambda route: route.abort())
                page = await kontext.new_page()
                screenshots = []
                page.screenshot = lambda **k: screenshots.append(k)   # Spion: darf nie gerufen werden
                await page.set_content(html)
                return await scraper.lies_profil(page, "https://www.therapie.de/profil/beispiel/"), screenshots
            finally:
                await browser.close()
    try:
        return asyncio.run(lauf())
    except Exception as fehler:
        pytest.skip(f"Chromium nicht verfügbar: {fehler}")


def test_lies_profil_liest_alle_felder():
    profil, screenshots = _lies(PROFIL)
    assert profil["name"] == "Dipl.-Psych. Erika Beispiel"
    assert profil["adresse"] == "Musterweg 1, 59174 Kamen" and profil["plz"] == "59174"
    assert profil["telefon"] == "02307 123"
    assert profil["email"] == "praxis@beispiel-kamen.de"                # ohne ?subject
    assert profil["website"] == "https://praxis-beispiel.de"           # kein therapie.de-/Kartenlink
    assert profil["abrechnungsarten"] == ["Kassenleistung", "Selbstzahler"]
    assert profil["behandlungsschwerpunkte"] == ["Depression", "Angst"]
    assert profil["therapieangebot"] == ["Einzeltherapie: Erwachsene"]
    assert profil["therapieverfahren"] == []
    assert profil["freie_plaetze"] == "Wartezeit über drei Monate"
    assert profil["aufnahmestopp"] is True
    assert profil["persoenliches_profil"] == "Ich nehme derzeit keine neuen Patienten auf."
    assert "Musterweg 1" in profil["volltext"]
    assert screenshots == []                                           # keine Bilder von Profilen


def test_lies_profil_ohne_mikrodaten_und_ohne_freitext():
    profil, _ = _lies(OHNE_MIKRODATEN)
    assert profil["adresse"] == "Teststraße 5 | 44135 Dortmund | 2. OG"   # Zeilen 3 bis 5 der Karte
    assert profil["email"] == "" and profil["website"] == ""
    assert profil["abrechnungsarten"] == []
    assert profil["persoenliches_profil"] == ""                          # weniger als drei Blöcke
    assert profil["aufnahmestopp"] is False and profil["aufnahmestopp_zitat"] == ""
