"""Tests fuer die reinen (netzwerkfreien) Hilfsfunktionen in scraper.py.
Die Navigations-Absicherung (SSRF nach Redirect) wird mit einer Fake-Page
getestet, es faehrt also weiterhin kein echter Browser hoch."""
import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pfade
import scraper


# ---------- keine Bing-Suche mehr ----------

def test_keine_automatische_bing_suche_mehr():
    """Die Bing-Namenssuche (find_emails_google, entfernt 16.10.2026) hat
    Suchergebnisse automatisiert ausgelesen -- das erlauben Bings
    Nutzungsbedingungen nicht -- und lieferte haeufig falsche Emails."""
    assert not hasattr(scraper, "find_emails_google")
    assert "bing.com/search" not in Path(scraper.__file__).read_text(encoding="utf-8")


# ---------- _clean_email / _EMAIL_*_BLACKLIST ----------

def test_clean_email_akzeptiert_normale_adresse():
    assert scraper._clean_email("praxis@example-praxis.de") == "praxis@example-praxis.de"


def test_clean_email_lehnt_sentry_subdomain_ab():
    """Regression zum Audit-Befund K4: der Live-Datenbestand enthielt
    '...@sentry-next.wixpress.com' (Telemetrie-Adresse aus einem
    eingebetteten Analytics-Skript), weil die alte Blacklist nur
    '@wixpress.com' direkt hinter dem @ erkannte, nicht als Domain-Endung."""
    assert scraper._clean_email("605a7baede844d278b89dc95ae0a9123@sentry-next.wixpress.com") is None


def test_clean_email_lehnt_generische_platzhalter_ab():
    assert scraper._clean_email("noreply@praxis.de") is None
    assert scraper._clean_email("info@example.com") is None


def test_clean_email_lehnt_grosse_fremde_plattformen_ab():
    """Regression (12.8.2026): eine Bing-Suche fuer eine echte Therapeutin
    landete faelschlich auf einer Microsoft-Seite, von der
    'kunden@microsoft.com' extrahiert wurde. Ohne diese Sperre waere das
    ungeprueft als Kontakt-Email gespeichert worden."""
    assert scraper._clean_email("kunden@microsoft.com") is None
    assert scraper._clean_email("support@apple.com") is None
    assert scraper._clean_email("jemand@amazon.de") is None
    assert scraper._clean_email("kontakt@outlook.com") is None


def test_clean_email_lehnt_themenfremde_treffer_ab():
    """Regression (26.8.2026, Marcel gemeldet): drei Live-Eintraege hatten
    offensichtlich falsche Emails, die eine Bing-Suche fuer den jeweiligen
    Vor-/Nachnamen faelschlich auf themenfremden, aber fuer den Namen hoch
    rankenden Seiten fand (siehe _EMAIL_DOMAIN_BLACKLIST-Kommentar). Eine
    Vornamen-Bedeutungsseite tauchte dabei bei 11 verschiedenen
    Therapeuten mit unterschiedlichen Vornamen als 'Email' auf."""
    assert scraper._clean_email("info@baby-vornamen.de") is None
    assert scraper._clean_email("kontakt@gala.de") is None
    assert scraper._clean_email("u002f@tvmovie.de") is None
    assert scraper._clean_email("general@crazygames.com") is None
    assert scraper._clean_email("support@mamenza.com") is None
    assert scraper._clean_email("info@website.com") is None
    assert scraper._clean_email("max.mustermann@beispiel.de") is None
    assert scraper._clean_email("max.mustermann@beispiel.com") is None


def test_clean_email_lehnt_retina_bilddateinamen_ab():
    """Regression (12.8.2026): 'chosen-sprite@2x.png' aus einem echten
    Live-Testlauf erfuellte EMAIL_REGEX vollstaendig (.png sieht wie eine
    TLD aus) und waere ohne diese Sperre als Kontakt-Email gespeichert
    worden."""
    assert scraper._clean_email("logo@2x.png") is None
    assert scraper._clean_email("chosen-sprite@2x.png") is None
    assert scraper._clean_email("icon@3x.svg") is None
    # echte .info/.io-Domains bleiben erlaubt (keine Dateiendung):
    assert scraper._clean_email("praxis@beispiel.info") == "praxis@beispiel.info"


def test_is_directory_blockt_grosse_fremde_plattformen():
    assert scraper._is_directory("https://support.microsoft.com/de-de/kontakt") is True
    assert scraper._is_directory("https://www.amazon.de/hilfe") is True
    # echte Praxis-Website bleibt erlaubt:
    assert scraper._is_directory("https://www.psychotherapie-mueller-dortmund.de") is False


def test_is_directory_blockt_themenfremde_namenstreffer():
    """Regression (26.8.2026): verhindert, dass die Email-Suche diese
    Seiten ueberhaupt erst als 'Praxis-Website' besucht (siehe
    test_clean_email_lehnt_themenfremde_treffer_ab fuer die zugehoerigen
    Live-Faelle)."""
    assert scraper._is_directory("https://www.baby-vornamen.de/vorname/irgendwer") is True
    assert scraper._is_directory("https://www.gala.de/promis/irgendwer.html") is True
    assert scraper._is_directory("https://www.tvmovie.de/irgendwas") is True
    assert scraper._is_directory("https://www.crazygames.com/game/irgendwas") is True
    assert scraper._is_directory("https://www.mamenza.com/de") is True
    assert scraper._is_directory("https://www.website.com") is True


def test_clean_email_akzeptiert_echte_domain_mit_aehnlichem_namen():
    """Darf NICHT durch die verschärfte Blacklist mit-ausgeschlossen werden
    -- nur exakte Endungen sind gesperrt, keine Teilstrings irgendwo in der
    Domain."""
    assert scraper._clean_email("kontakt@wixpressberatung-praxis.de") == "kontakt@wixpressberatung-praxis.de"


def test_clean_email_lehnt_ungueltiges_format_ab():
    assert scraper._clean_email("kein-email") is None
    assert scraper._clean_email("") is None


def test_clean_email_trimmt_trailing_satzzeichen():
    assert scraper._clean_email("praxis@example-praxis.de.") == "praxis@example-praxis.de"
    assert scraper._clean_email("praxis@example-praxis.de)") == "praxis@example-praxis.de"


# ---------- extract_from_text ----------

def test_extract_from_text_findet_email_und_https_website():
    email, website = scraper.extract_from_text("Kontakt: info@praxis-mueller.de, https://praxis-mueller.de/kontakt")
    assert email == "info@praxis-mueller.de"
    assert website == "https://praxis-mueller.de/kontakt"


def test_extract_from_text_ergaenzt_https_bei_www():
    _, website = scraper.extract_from_text("Mehr unter www.praxis-schmidt.de")
    assert website == "https://www.praxis-schmidt.de"


def test_extract_from_text_leerer_text_liefert_none_none():
    assert scraper.extract_from_text("") == (None, None)


def test_extract_from_text_ignoriert_blacklisted_email():
    email, _ = scraper.extract_from_text("Analytics: xyz@sentry-next.wixpress.com Kontakt: keine weitere Mail hier.")
    assert email is None


# ---------- _is_directory ----------

def test_is_directory_erkennt_bekannte_verzeichnisse():
    assert scraper._is_directory("https://www.jameda.de/irgendwer") is True
    assert scraper._is_directory("https://sub.therapie.de/irgendwas") is True


def test_is_directory_erkennt_echte_praxis_domain_nicht_als_verzeichnis():
    assert scraper._is_directory("https://praxis-mueller-dortmund.de") is False


def test_is_directory_uebersteht_ungueltige_url():
    assert scraper._is_directory("das-ist-keine-url") is False
    assert scraper._is_directory("") is False


# ---------- keine Profil-Screenshots ----------

def test_scraper_macht_keine_profil_screenshots():
    """Seit 16.10.2026 werden keine Screenshots der Profilseiten mehr
    gespeichert (Fotos + Kontaktdaten fremder Praxen ohne Not). Der Test
    verhindert, dass die Funktion still zurueckkommt."""
    quelltext = Path(scraper.__file__).read_text(encoding="utf-8")
    assert "page.screenshot" not in quelltext
    assert not hasattr(scraper, "SCREENSHOT_DIR")
    assert not hasattr(scraper.pfade, "EVIDENCE_DIR")


# ---------- _finde_aufnahmestopp ----------

def test_aufnahmestopp_erkennt_formulierung_und_zitat():
    gefunden, zitat = scraper._finde_aufnahmestopp("Aktuell freie Kapazitäten. Wir nehmen derzeit keine neuen Patienten auf. Bitte später wieder anfragen.")
    assert gefunden is True
    assert "keine neuen Patienten" in zitat or "nehmen derzeit keine" in zitat.lower()


def test_aufnahmestopp_negativfall():
    gefunden, zitat = scraper._finde_aufnahmestopp("Freie Plätze vorhanden, bitte melden.")
    assert gefunden is False
    assert zitat == ""


def test_aufnahmestopp_treffer_am_textanfang():
    """Regression zu einem Off-by-one (kandidaten-Filter mit '> 0' statt
    '>= 0'): ein Treffer direkt am Textanfang, ohne vorangehendes Trennzeichen
    bei Index 0, durfte das Zitat nicht kaputt schneiden."""
    gefunden, zitat = scraper._finde_aufnahmestopp("Aufnahmestopp bis auf Weiteres.")
    assert gefunden is True
    assert zitat.startswith("Aufnahmestopp")


def test_aufnahmestopp_zitat_ist_zeichengenau_bei_mehrbyte_zeichen():
    """Regression zum Audit-Befund N3: .lower() ist nicht laengenerhaltend
    (z.B. 'İ' -> 2 Zeichen), was bei einer Positions-Uebernahme von einer
    Lowercase-Kopie auf das Original zu verschobenen/verfaelschten Zitaten
    fuehren konnte. Der Fix sucht direkt (case-insensitive) im Original."""
    text = "Praxis İnfo. Wir nehmen aktuell keine neuen Patienten auf, danke."
    gefunden, zitat = scraper._finde_aufnahmestopp(text)
    assert gefunden is True
    # Das Zitat darf nur echte Textteile aus dem Original enthalten,
    # keine durch Index-Drift eingestreuten falschen Zeichen.
    assert zitat in text


# ---------- _ist_oeffentliche_http_url (SSRF-Schutz) ----------

def test_ssrf_schutz_lehnt_localhost_ab():
    assert scraper._ist_oeffentliche_http_url("http://localhost:8080/frontend/../.env") is False


def test_ssrf_schutz_lehnt_private_ip_ab():
    assert scraper._ist_oeffentliche_http_url("http://127.0.0.1/") is False
    assert scraper._ist_oeffentliche_http_url("http://192.168.1.1/") is False


def test_ssrf_schutz_lehnt_nicht_http_schema_ab():
    assert scraper._ist_oeffentliche_http_url("file:///etc/passwd") is False
    assert scraper._ist_oeffentliche_http_url("javascript:alert(1)") is False


def test_ssrf_schutz_lehnt_unaufloesbaren_host_ab():
    assert scraper._ist_oeffentliche_http_url("http://dieser-host-existiert-ganz-sicher-nicht.invalid/") is False


def test_ssrf_schutz_erlaubt_bekannte_oeffentliche_domain():
    assert scraper._ist_oeffentliche_http_url("https://www.google.com") is True


# ---------- SSRF-Schutz NACH der Navigation (Audit-Befund S4) ----------
#
# Die Pruefung vor page.goto() sichert nur die ANGEFRAGTE Adresse ab. Ein
# Server kann per 301/302 auf http://127.0.0.1:8080/ weiterleiten und die
# Pruefung damit umgehen -- der Scraper wuerde dann den lokalen Server
# auslesen.

class _FakePage:
    """Minimaler Ersatz fuer eine Playwright-Page: merkt sich die 'erreichte'
    URL (inklusive optionaler Weiterleitung) und zaehlt, ob der Seiteninhalt
    ueberhaupt gelesen wurde."""

    def __init__(self, weiterleitungen=None, html=""):
        self.url = ""
        self.weiterleitungen = weiterleitungen or {}
        self.html = html
        self.inhalt_gelesen = 0

    async def goto(self, url, **kwargs):
        self.url = self.weiterleitungen.get(url, url)
        return None

    async def evaluate(self, script, *args):
        self.inhalt_gelesen += 1
        return []

    async def content(self):
        self.inhalt_gelesen += 1
        return self.html


def test_nach_navigation_erlaubt_oeffentliche_zieladresse():
    page = _FakePage()
    page.url = "https://www.google.com/"
    assert scraper._nach_navigation_erlaubt(page) is True


def test_nach_navigation_blockt_weiterleitung_auf_localhost():
    page = _FakePage()
    page.url = "http://127.0.0.1:8080/frontend/index.html"
    assert scraper._nach_navigation_erlaubt(page) is False


def test_find_email_on_website_bricht_bei_redirect_auf_localhost_ab():
    """Die angefragte URL ist oeffentlich und besteht die Vorpruefung; erst
    die Weiterleitung fuehrt ins lokale Netz. Der Seiteninhalt darf danach
    gar nicht mehr gelesen werden."""
    page = _FakePage(
        weiterleitungen={"https://www.google.com/": "http://127.0.0.1:8080/"},
        html="Kontakt: praxis@example-praxis.de",
    )
    ergebnis = asyncio.run(scraper.find_email_on_website(page, "https://www.google.com/"))
    assert ergebnis is None
    assert page.inhalt_gelesen == 0


def test_find_email_on_website_liest_seite_ohne_weiterleitung_normal():
    page = _FakePage(html="Kontakt: praxis@example-praxis.de")
    ergebnis = asyncio.run(scraper.find_email_on_website(page, "https://www.google.com/"))
    assert ergebnis == "praxis@example-praxis.de"


# ---------- Resume-Hilfen: _lade_ergebnisse / _bekannte_urls / _speichere_ergebnisse ----------

def test_bekannte_urls_uebersteht_eintrag_ohne_profil_url():
    """Regression zu B6: das frueher genutzte r["profil_url"] warf KeyError
    und brach den kompletten Lauf ab, bevor ueberhaupt etwas gescrapt wurde."""
    results = [{"profil_url": "u1"}, {"name": "ohne url"}, {"profil_url": ""}, "kein dict"]
    assert scraper._bekannte_urls(results) == {"u1"}


def test_lade_ergebnisse_bei_kaputter_datei_gibt_leere_liste(tmp_path, monkeypatch):
    """json_sicher_laden statt nacktem json.load: eine abgeschnittene
    results_raw.json (Absturz mitten im Schreiben) darf den Scraper nicht
    mit JSONDecodeError beenden."""
    datei = tmp_path / "results_raw.json"
    datei.write_text('[{"profil_url": "u1"', encoding="utf-8")  # abgeschnitten
    monkeypatch.setattr(scraper, "OUTPUT_FILE", str(datei))
    assert scraper._lade_ergebnisse() == []


def test_lade_ergebnisse_bei_fehlender_datei_gibt_leere_liste(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "OUTPUT_FILE", str(tmp_path / "gibt-es-nicht.json"))
    assert scraper._lade_ergebnisse() == []


def test_speichere_ergebnisse_schreibt_atomar(tmp_path, monkeypatch):
    """Audit-Befund S1: die ~1 MB grosse Ergebnisdatei wird ueber eine
    temporaere Datei + os.replace geschrieben, damit ein Abbruch mitten im
    Schreiben nicht den kompletten Scraping-Fortschritt zerstoert."""
    ziel = tmp_path / "unterordner" / "results_raw.json"
    monkeypatch.setattr(scraper, "OUTPUT_FILE", str(ziel))
    scraper._speichere_ergebnisse([{"profil_url": "u1", "name": "Ärztin Müller"}])
    gespeichert = json.loads(ziel.read_text(encoding="utf-8"))
    assert gespeichert[0]["name"] == "Ärztin Müller"   # ensure_ascii=False
    assert list(ziel.parent.glob("*.tmp")) == []       # keine Reste


def test_speichere_ergebnisse_laesst_alten_stand_bei_fehler_unangetastet(tmp_path, monkeypatch):
    ziel = tmp_path / "results_raw.json"
    ziel.write_text('[{"profil_url": "alt"}]', encoding="utf-8")
    monkeypatch.setattr(scraper, "OUTPUT_FILE", str(ziel))

    class NichtSerialisierbar:
        pass

    with pytest.raises(TypeError):
        scraper._speichere_ergebnisse([NichtSerialisierbar()])
    assert json.loads(ziel.read_text(encoding="utf-8")) == [{"profil_url": "alt"}]
    assert list(ziel.parent.glob("*.tmp")) == []


# ---------- SSRF-Schutz VOR jedem Request per Route-Interception (Review #13) ----------
#
# Die Nachpruefung nach page.goto() kommt zu spaet (der Request an die
# interne Adresse ist dann schon passiert) und deckt Subressourcen
# (Bilder, Skripte, iframes) gar nicht ab. ssrf_route_handler() prueft
# deshalb JEDEN Request, bevor der Browser ihn absendet. Kein echtes Netz:
# DNS wird per monkeypatch von socket.getaddrinfo simuliert.


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.aktion = None

    async def continue_(self):
        self.aktion = "continue"

    async def abort(self, error_code=None):
        self.aktion = "abort"


_FAKE_DNS = {
    "praxis-beispiel.de": "93.184.216.34",
    "cdn.praxis-beispiel.de": "93.184.216.35",
    "intern-rebind.example": "10.0.0.7",
    "localhost": "127.0.0.1",
}


@pytest.fixture
def fake_dns(monkeypatch):
    aufrufe = []

    def _getaddrinfo(host, port, *args, **kwargs):
        aufrufe.append(host)
        try:
            import ipaddress
            ipaddress.ip_address(host)
            ip = host  # IP-Literale werden direkt "aufgeloest"
        except ValueError:
            if host not in _FAKE_DNS:
                raise socket.gaierror("unbekannter Host")
            ip = _FAKE_DNS[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return aufrufe


def _route_ergebnis(handler, url):
    route = _FakeRoute(url)
    asyncio.run(handler(route))
    return route.aktion


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://localhost/",
    "http://localhost:8080/frontend/index.html",
    "http://192.168.178.1/admin",
    "http://169.254.169.254/latest/meta-data/",   # Cloud-Metadaten
    "http://[::1]/",
    "http://intern-rebind.example/bild.png",       # oeffentlicher Name, interne IP
    "file:///etc/passwd",
    "http://gibt-es-nicht.invalid/",
])
def test_route_handler_blockt_nicht_oeffentliche_ziele(fake_dns, url):
    assert _route_ergebnis(scraper.ssrf_route_handler(), url) == "abort"


@pytest.mark.parametrize("url", [
    "https://praxis-beispiel.de/",
    "https://cdn.praxis-beispiel.de/logo.png",
    "http://93.184.216.34/impressum",
])
def test_route_handler_laesst_oeffentliche_ziele_durch(fake_dns, url):
    assert _route_ergebnis(scraper.ssrf_route_handler(), url) == "continue"


def test_route_handler_prueft_auch_redirect_ziel_und_subressourcen(fake_dns):
    """Playwright ruft den Handler pro Request auf -- also auch fuer das
    Ziel einer 302-Weiterleitung und fuer jedes Bild/Skript der Seite. Hier
    als Folge von Requests derselben Seite simuliert."""
    handler = scraper.ssrf_route_handler()
    folge = [
        ("https://praxis-beispiel.de/", "continue"),              # Startseite
        ("http://127.0.0.1:8080/", "abort"),                      # 302-Ziel
        ("https://cdn.praxis-beispiel.de/app.js", "continue"),    # Skript
        ("http://10.0.0.5/tracking.gif", "abort"),                # Bild
    ]
    for url, erwartet in folge:
        assert _route_ergebnis(handler, url) == erwartet, url


def test_route_handler_cached_dns_pro_host(fake_dns):
    handler = scraper.ssrf_route_handler()
    for pfad in ("a.png", "b.png", "c.js"):
        assert _route_ergebnis(handler, f"https://praxis-beispiel.de/{pfad}") == "continue"
    assert fake_dns.count("praxis-beispiel.de") == 1


def test_route_handler_akzeptiert_auch_zwei_argumente(fake_dns):
    """Playwright uebergibt je nach Signatur (route) oder (route, request)."""
    handler = scraper.ssrf_route_handler()
    route = _FakeRoute("https://praxis-beispiel.de/")
    asyncio.run(handler(route, _FakeRequest("http://127.0.0.1/")))
    assert route.aktion == "abort"


def test_route_handler_ueberlebt_fehler_beim_weiterleiten(fake_dns):
    class _KaputteRoute(_FakeRoute):
        async def continue_(self):
            raise RuntimeError("Target page, context or browser has been closed")
    route = _KaputteRoute("https://praxis-beispiel.de/")
    asyncio.run(scraper.ssrf_route_handler()(route))  # darf nicht werfen


def test_ssrf_schutz_einrichten_haengt_handler_fuer_alle_requests_ein():
    class _FakeContext:
        def __init__(self):
            self.routen = []

        async def route(self, muster, handler):
            self.routen.append((muster, handler))

    ctx = _FakeContext()
    asyncio.run(scraper.ssrf_schutz_einrichten(ctx))
    assert len(ctx.routen) == 1
    assert ctx.routen[0][0] == "**/*"
    assert callable(ctx.routen[0][1])


def test_enrich_emails_richtet_ssrf_schutz_vor_der_ersten_navigation_ein(tmp_path, monkeypatch, fake_dns):
    """Integration mit Fake-Playwright: der Route-Handler muss auf dem
    Context haengen, BEVOR die erste Praxis-Website angesteuert wird."""
    ereignisse = []

    class _Page:
        url = ""

        async def goto(self, url, **kwargs):
            ereignisse.append(("goto", url))
            self.url = url

        async def evaluate(self, script, *args):
            return []

        async def content(self):
            return "Kontakt: info@praxis-beispiel.de"

    class _Context:
        async def route(self, muster, handler):
            ereignisse.append(("route", muster))

        async def new_page(self):
            return _Page()

    class _Browser:
        async def new_context(self, **kwargs):
            return _Context()

        async def close(self):
            pass

    class _Chromium:
        async def launch(self, **kwargs):
            return _Browser()

    class _PW:
        chromium = _Chromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _kein_schlaf(*a, **k):
        return None

    monkeypatch.setattr(scraper, "async_playwright", lambda: _PW())
    monkeypatch.setattr(scraper.asyncio, "sleep", _kein_schlaf)
    datei = tmp_path / "roh.json"
    datei.write_text(json.dumps([{"name": "Praxis", "email": "", "volltext": "",
                                  "persoenliches_profil": "",
                                  "website": "https://praxis-beispiel.de/"}]), encoding="utf-8")
    asyncio.run(scraper.enrich_emails(input_file=str(datei)))
    assert ereignisse[0] == ("route", "**/*")
    assert ("goto", "https://praxis-beispiel.de/") in ereignisse
    assert json.loads(datei.read_text(encoding="utf-8"))[0]["email"] == "info@praxis-beispiel.de"


# ---------- freie_plaetze_aus_text / _ist_praxis_website (Befund 30.9.2026) ----------

def test_freie_plaetze_ueberschrift_allein_zaehlt_nicht_als_frei():
    text = "Therapie-Angebot\nEinzeltherapie: Erwachsene\nFreie Plätze / Wartezeiten\nWartezeit über zwölf Monate.\nMitgliedschaften"
    assert scraper.freie_plaetze_aus_text(text) == "Wartezeit über zwölf Monate"


def test_freie_plaetze_vorhanden():
    assert scraper.freie_plaetze_aus_text("Freie Plätze / Wartezeiten\nFreie Plätze vorhanden.\n") == "freie Plätze"


def test_freie_plaetze_ohne_abschnitt_leer():
    assert scraper.freie_plaetze_aus_text("Profil ohne Angaben zu freien Plätzen") == ""


def test_kartenlinks_sind_keine_praxis_website():
    assert not scraper._ist_praxis_website("https://www.google.com/maps/search/?api=1&query=51.4,7.5")
    assert not scraper._ist_praxis_website("https://maps.apple.com/place?q=x")
    assert not scraper._ist_praxis_website("https://www.therapie.de/profil/x/")
    assert scraper._ist_praxis_website("https://www.praxis-beispiel.de")


def test_scraper_umgeht_keine_bot_erkennung():
    """5.10.2026: Tricks gegen Bot-Erkennung wurden entfernt und duerfen nicht
    zurueckkommen (rechtlich heikel, siehe Sicherheitscheck)."""
    quelle = (Path(__file__).resolve().parent.parent / "backend" / "scraper.py").read_text(encoding="utf-8")
    assert "AutomationControlled" not in quelle
    assert "'webdriver'" not in quelle
