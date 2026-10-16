"""Tests fuer den Ablauf von scraper.py: Suchseiten durchblaettern, Resume,
Ban-Stopp, Zwischenspeichern und die Email-Anreicherung.

Es faehrt kein echter Browser hoch und nichts geht ins Netz: Playwright wird
durch kleine Attrappen ersetzt (FakePage/FakePlaywright), die genau das
liefern, was der jeweilige Test braucht. Pausen sind auf 0 gesetzt.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import scraper  # noqa: E402


class _Antwort:
    def __init__(self, status=200):
        self.status = status


class FakePage:
    """Simuliert eine therapie.de-Suchseite bzw. eine Praxis-Website.

    seiten: url -> dict(links=[...], weiter="url"|None, html="...", status=200)
    """

    def __init__(self, seiten=None):
        self.seiten = seiten or {}
        self.url = "about:blank"
        self.besucht = []

    async def goto(self, url, wait_until=None, timeout=None):
        if self.seiten.get(url, {}).get("fehler"):
            raise TimeoutError("laedt nicht")
        self.url = url
        self.besucht.append(url)
        return _Antwort(self.seiten.get(url, {}).get("status", 200))

    async def content(self):
        return self.seiten.get(self.url, {}).get("html", "<html></html>")

    async def wait_for_selector(self, selector, timeout=None):
        if not self.seiten.get(self.url, {}).get("links"):
            raise TimeoutError("keine Trefferliste")

    async def eval_on_selector_all(self, selector, js):
        return self.seiten.get(self.url, {}).get("links", [])

    async def query_selector(self, selector):
        weiter = self.seiten.get(self.url, {}).get("weiter")
        if not weiter:
            return None

        class _Link:
            async def get_attribute(self, name):
                return weiter

        return _Link()

    async def evaluate(self, js, *args):
        # find_email_on_page liest Text/Links, find_email_on_website die
        # Kontakt-Unterseiten. Beides kommt aus der Seitenbeschreibung.
        eintrag = self.seiten.get(self.url, {})
        if "kontakt" in js:
            return eintrag.get("unterseiten", [])
        return eintrag.get("html", "")


@pytest.fixture(autouse=True)
def keine_pausen(monkeypatch):
    async def sofort(*a, **k):
        return None
    monkeypatch.setattr(scraper, "_pause", sofort)
    monkeypatch.setattr(scraper.asyncio, "sleep", sofort)


# ---------- _goto: Ban-Erkennung ----------

@pytest.mark.parametrize("status", [403, 429])
def test_goto_erkennt_sperre_am_statuscode(status):
    page = FakePage({"https://x.de/": {"status": status}})
    with pytest.raises(scraper.BanVerdacht):
        asyncio.run(scraper._goto(page, "https://x.de/"))


def test_goto_erkennt_captcha_seite():
    page = FakePage({"https://x.de/": {"html": "Bitte bestätigen: Ich bin kein Roboter"}})
    with pytest.raises(scraper.BanVerdacht):
        asyncio.run(scraper._goto(page, "https://x.de/"))


def test_goto_normale_seite_ist_ok():
    assert asyncio.run(scraper._goto(FakePage(), "https://x.de/")).status == 200


# ---------- Suchergebnisse durchblaettern ----------

def _such_url(ort):
    return f"{scraper.BASE_URL}/therapeutensuche/ergebnisse/?ort={scraper.quote(ort)}"


def test_alle_profil_urls_ueber_mehrere_seiten_und_orte_ohne_doppelte(monkeypatch):
    monkeypatch.setattr(scraper, "SUCHORTE", ["Dortmund", "Unna"])
    seite2 = _such_url("Dortmund") + "&page=2"
    page = FakePage({
        _such_url("Dortmund"): {"links": ["https://www.therapie.de/profil/a/",
                                          "https://www.therapie.de/profil/a/info/"],
                                "weiter": "/therapeutensuche/ergebnisse/?ort=Dortmund&page=2"},
        seite2: {"links": ["https://www.therapie.de/profil/b/"], "weiter": _such_url("Dortmund")},
        _such_url("Unna"): {"links": ["https://www.therapie.de/profil/b/",
                                      "https://www.therapie.de/profil/c/"]},
    })
    urls = asyncio.run(scraper.get_all_profile_urls(page))
    assert urls == ["https://www.therapie.de/profil/a/", "https://www.therapie.de/profil/b/",
                    "https://www.therapie.de/profil/c/"]
    assert page.besucht.count(_such_url("Dortmund")) == 1   # Kreislauf wird erkannt


def test_leere_suchseite_liefert_keine_links():
    page = FakePage({"https://www.therapie.de/leer": {"links": []}})
    assert asyncio.run(scraper.get_profile_links(page, "https://www.therapie.de/leer")) == []


# ---------- main(): Resume, Speichern, Ban-Stopp ----------

class FakePlaywright:
    """Ersetzt async_playwright(): liefert einen Browser mit FakePage."""

    def __init__(self, page=None, close_fehler=False):
        self.page = page or FakePage()
        self.geschlossen = False
        self.close_fehler = close_fehler

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def chromium(self):
        return self

    async def launch(self, headless=True):
        return self

    async def new_context(self, **k):
        return self

    async def new_page(self):
        return self.page

    async def route(self, muster, handler):
        self.route_gesetzt = True

    async def close(self):
        if self.close_fehler:
            raise RuntimeError("Browser haengt")
        self.geschlossen = True


@pytest.fixture
def lauf(tmp_path, monkeypatch):
    datei = tmp_path / "results_raw.json"
    monkeypatch.setattr(scraper, "OUTPUT_FILE", str(datei))
    fake = FakePlaywright()
    monkeypatch.setattr(scraper, "async_playwright", fake)
    return datei, fake


def test_main_ueberspringt_bekannte_profile_und_speichert(lauf, monkeypatch):
    datei, fake = lauf
    datei.write_text(json.dumps([{"profil_url": "u1", "name": "Alt"}]), encoding="utf-8")

    async def urls(page):
        return ["u1", "u2", "u3"]

    geholt = []

    async def profil(page, url):
        geholt.append(url)
        return None if url == "u3" else {"profil_url": url, "name": "Neu", "aufnahmestopp": True}

    monkeypatch.setattr(scraper, "get_all_profile_urls", urls)
    monkeypatch.setattr(scraper, "extract_profile", profil)
    ergebnis = asyncio.run(scraper.main())

    assert geholt == ["u2", "u3"]
    assert [p["profil_url"] for p in ergebnis] == ["u1", "u2"]
    assert [p["profil_url"] for p in json.loads(datei.read_text())] == ["u1", "u2"]
    assert fake.geschlossen


def test_main_neu_ignoriert_alten_stand(lauf, monkeypatch):
    datei, _ = lauf
    datei.write_text(json.dumps([{"profil_url": "u1"}]), encoding="utf-8")

    async def urls(page):
        return ["u1"]

    async def profil(page, url):
        return {"profil_url": url, "name": "frisch"}

    monkeypatch.setattr(scraper, "get_all_profile_urls", urls)
    monkeypatch.setattr(scraper, "extract_profile", profil)
    assert asyncio.run(scraper.main(neu=True)) == [{"profil_url": "u1", "name": "frisch"}]


def test_main_stoppt_bei_sperre_und_behaelt_fortschritt(lauf, monkeypatch, capsys):
    datei, fake = lauf

    async def urls(page):
        return ["u1", "u2"]

    async def profil(page, url):
        if url == "u2":
            raise scraper.BanVerdacht("HTTP 429")
        return {"profil_url": url}

    monkeypatch.setattr(scraper, "get_all_profile_urls", urls)
    monkeypatch.setattr(scraper, "extract_profile", profil)
    ergebnis = asyncio.run(scraper.main())
    assert ergebnis == [{"profil_url": "u1"}]
    assert json.loads(datei.read_text()) == [{"profil_url": "u1"}]
    assert "STOPP" in capsys.readouterr().out
    assert fake.geschlossen


def test_main_speichert_auch_bei_unerwartetem_fehler(lauf, monkeypatch):
    datei, fake = lauf
    fake.close_fehler = True   # auch ein haengender Browser darf nichts verhindern

    async def urls(page):
        return ["u1", "u2"]

    async def profil(page, url):
        if url == "u2":
            raise KeyboardInterrupt
        return {"profil_url": url}

    monkeypatch.setattr(scraper, "get_all_profile_urls", urls)
    monkeypatch.setattr(scraper, "extract_profile", profil)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(scraper.main())
    assert json.loads(datei.read_text()) == [{"profil_url": "u1"}]


# ---------- enrich_emails(): Stufe 1 (Text) und Stufe 2 (Website) ----------

def test_enrich_emails_fehlende_datei(tmp_path, capsys):
    asyncio.run(scraper.enrich_emails(str(tmp_path / "gibt-es-nicht.json")))
    assert "nicht gefunden" in capsys.readouterr().out


def test_enrich_emails_aus_text_und_website(tmp_path, monkeypatch):
    datei = tmp_path / "raw.json"
    datei.write_text(json.dumps([
        {"name": "A", "email": "noreply@example.com", "volltext": "Mail: praxis-a@example-praxis.de"},
        {"name": "B", "volltext": "Website: www.praxis-b.de"},
        {"name": "C", "email": "c@example-praxis.de"},
    ]), encoding="utf-8")
    besucht = []

    async def website(page, url):
        besucht.append(url)
        return "kontakt@praxis-b.de"

    fake = FakePlaywright()
    monkeypatch.setattr(scraper, "async_playwright", fake)
    monkeypatch.setattr(scraper, "find_email_on_website", website)
    asyncio.run(scraper.enrich_emails(str(datei)))

    profile = json.loads(datei.read_text())
    assert profile[0]["email"] == "praxis-a@example-praxis.de"   # ungueltige ersetzt aus Text
    assert profile[1]["website"] == "https://www.praxis-b.de"
    assert profile[1]["email"] == "kontakt@praxis-b.de"          # von der Website
    assert profile[2]["email"] == "c@example-praxis.de"          # unveraendert
    assert besucht == ["https://www.praxis-b.de"]
    assert fake.route_gesetzt                                    # SSRF-Schutz aktiv
    assert fake.geschlossen


def test_enrich_emails_ohne_websites_startet_keinen_browser(tmp_path, monkeypatch):
    datei = tmp_path / "raw.json"
    datei.write_text(json.dumps([{"name": "A", "email": "a@example-praxis.de"}]), encoding="utf-8")
    monkeypatch.setattr(scraper, "async_playwright", lambda: pytest.fail("kein Browser erwartet"))
    asyncio.run(scraper.enrich_emails(str(datei)))


# ---------- find_email_on_website: Kontakt-Unterseiten ----------

def test_email_steht_erst_auf_der_kontaktseite(monkeypatch):
    monkeypatch.setattr(scraper, "_ist_oeffentliche_http_url", lambda u: "intern" not in u)
    monkeypatch.setattr(scraper, "_nach_navigation_erlaubt", lambda p: True)
    page = FakePage({
        "https://praxis.de/": {"html": "Willkommen", "unterseiten": [
            "http://intern/kontakt", "https://praxis.de/laedt-nicht", "https://praxis.de/kontakt"]},
        "https://praxis.de/laedt-nicht": {"fehler": True},
        "https://praxis.de/kontakt": {"html": "Schreiben Sie an info@praxis-beispiel.de"},
    })
    assert asyncio.run(scraper.find_email_on_website(page, "https://praxis.de/")) == "info@praxis-beispiel.de"
    assert "http://intern/kontakt" not in page.besucht


def test_website_laedt_nicht(monkeypatch):
    monkeypatch.setattr(scraper, "_ist_oeffentliche_http_url", lambda u: True)
    page = FakePage({"https://praxis.de/": {"fehler": True}})
    assert asyncio.run(scraper.find_email_on_website(page, "https://praxis.de/")) is None
