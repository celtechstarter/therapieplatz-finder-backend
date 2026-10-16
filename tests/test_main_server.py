"""Tests fuer den lokalen Vorschau-Server und den Ablauf von backend/main.py.

Anders als test_main.py (einzelne Handler-Methoden mit Attrappen) startet
dieser Test den ECHTEN http.server auf einem freien Port und schickt echte
HTTP-Anfragen. Damit sind die Wege abgedeckt, die eine Nutzerin in der
lokalen Vorschau wirklich ausloest: Liste laden, Praxis ausblenden/wieder
einblenden, Email senden (Gmail ist durch eine Attrappe ersetzt, es geht
nichts raus) und die Schutzregeln (fremder Origin, Doppelversand, kaputte
Eingaben). Alle Dateien liegen in einem Temp-Ordner.
"""
import http.client
import http.server
import json
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import main  # noqa: E402

EIGENER_ORIGIN = next(iter(main.ERLAUBTE_ORIGINS))


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SENT_LOG_FILE", tmp_path / "sent_log.json")
    monkeypatch.setattr(main, "EXCLUDED_FILE", tmp_path / "excluded.json")
    monkeypatch.setattr(main.pfade, "RESULTS_ANALYZED", tmp_path / "results_analyzed.json")
    monkeypatch.setattr(main.pfade, "RESULTS_RAW", tmp_path / "results_raw.json")
    (tmp_path / "results_analyzed.json").write_text(json.dumps([{"name": "Praxis A"}]), encoding="utf-8")

    gesendet = []
    attrappe = types.ModuleType("mailer")
    attrappe.send_email = lambda an, betreff, text: gesendet.append((an, betreff, text))
    monkeypatch.setitem(sys.modules, "mailer", attrappe)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), main.AppRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield {"port": httpd.server_address[1], "gesendet": gesendet, "tmp": tmp_path}
    httpd.shutdown()
    httpd.server_close()


def _anfrage(server, methode, pfad, body=None, origin=EIGENER_ORIGIN, host="localhost"):
    verbindung = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    kopf = {"Host": f"{host}:{server['port']}"}
    if origin:
        kopf["Origin"] = origin
    daten = None
    if body is not None:
        daten = body if isinstance(body, bytes) else json.dumps(body).encode()
        kopf["Content-Type"] = "application/json"
        kopf["Content-Length"] = str(len(daten))
    verbindung.request(methode, pfad, body=daten, headers=kopf)
    antwort = verbindung.getresponse()
    inhalt = antwort.read()
    verbindung.close()
    try:
        inhalt = json.loads(inhalt)
    except ValueError:
        pass
    return antwort.status, dict(antwort.getheaders()), inhalt


# ---------- GET ----------

def test_get_liefert_analysierte_ergebnisse(server):
    status, kopf, inhalt = _anfrage(server, "GET", "/results_analyzed.json")
    assert status == 200
    assert inhalt == [{"name": "Praxis A"}]
    assert kopf["Access-Control-Allow-Origin"] == EIGENER_ORIGIN


def test_get_rohdaten_fehlende_datei_gibt_leere_liste(server):
    assert _anfrage(server, "GET", "/results_raw.json")[2] == []


def test_get_startseite_leitet_zur_vorschau_um(server):
    status, kopf, _ = _anfrage(server, "GET", "/")
    assert status == 302
    assert kopf["Location"] == "/frontend/index.html"


def test_get_fremde_datei_wird_verweigert(server):
    status, _, inhalt = _anfrage(server, "GET", "/../.env")
    assert status == 403
    assert b"verweigert" in inhalt


def test_fremder_origin_bekommt_keinen_cors_header(server):
    _, kopf, _ = _anfrage(server, "GET", "/sent-log", origin="https://boese.example")
    assert "Access-Control-Allow-Origin" not in kopf


def test_options_antwortet_ok(server):
    assert _anfrage(server, "OPTIONS", "/send")[0] == 200


# ---------- Ausblenden / wieder einblenden ----------

def test_ausblenden_und_wiederherstellen(server):
    eintrag = {"profil_url": "https://quelle.de/a", "name": "Praxis A"}
    assert _anfrage(server, "POST", "/exclude", eintrag)[2] == {"ok": True}
    assert _anfrage(server, "POST", "/exclude", eintrag)[2] == {"ok": True}  # doppelt = kein Duplikat
    liste = _anfrage(server, "GET", "/excluded")[2]
    assert [e["profil_url"] for e in liste] == ["https://quelle.de/a"]

    assert _anfrage(server, "POST", "/restore", {"profil_url": "https://quelle.de/a"})[2] == {"ok": True}
    assert _anfrage(server, "GET", "/excluded")[2] == []


def test_ausblenden_ohne_profil_url_ist_400(server):
    status, _, inhalt = _anfrage(server, "POST", "/exclude", {"name": "ohne URL"})
    assert status == 400
    assert inhalt["error"] == "profil_url fehlt"


def test_restore_mit_kaputtem_body_ist_400(server):
    status, _, inhalt = _anfrage(server, "POST", "/restore", b"{kein json")
    assert status == 400
    assert inhalt["error"] == "Ungültiger JSON-Body"


# ---------- Senden ----------

def test_senden_schreibt_log_und_blockt_doppelversand(server):
    anfrage = {"to": "praxis@example-praxis.de", "subject": "Anfrage\r\nBcc: x@y.de",
               "body": "Hallo", "profil_url": "https://quelle.de/a", "name": "Praxis A"}
    status, _, inhalt = _anfrage(server, "POST", "/send", anfrage)
    assert status == 200 and inhalt["ok"] is True
    an, betreff, text = server["gesendet"][0]
    assert an == "praxis@example-praxis.de"
    assert "\r" not in betreff and "\n" not in betreff   # keine Header-Injection
    assert _anfrage(server, "GET", "/sent-log")[2][0]["profil_url"] == "https://quelle.de/a"

    status, _, inhalt = _anfrage(server, "POST", "/send", anfrage)
    assert status == 409 and "Bereits am" in inhalt["error"]
    assert len(server["gesendet"]) == 1

    anfrage["force"] = True
    assert _anfrage(server, "POST", "/send", anfrage)[0] == 200
    assert len(server["gesendet"]) == 2


def test_senden_ohne_betreff_nimmt_standardbetreff(server):
    _anfrage(server, "POST", "/send", {"to": "b@example-praxis.de", "body": "x"})
    assert server["gesendet"][0][1] == "Anfrage Therapieplatz"


def test_senden_an_mehrere_empfaenger_wird_abgelehnt(server):
    status, _, inhalt = _anfrage(server, "POST", "/send", {"to": "a@x.de,b@y.de", "body": "x"})
    assert status == 400 and inhalt["error"] == "Ungültige Empfänger-Email"
    assert server["gesendet"] == []


def test_gmail_fehler_verraet_keine_details(server, monkeypatch):
    def kaputt(*a):
        raise RuntimeError("interne Google-Kennung 12345")
    monkeypatch.setattr(sys.modules["mailer"], "send_email", kaputt)
    status, _, inhalt = _anfrage(server, "POST", "/send", {"to": "c@example-praxis.de", "body": "x"})
    assert status == 500
    assert "12345" not in json.dumps(inhalt)


def test_post_mit_fremdem_origin_wird_abgelehnt(server):
    status, _, inhalt = _anfrage(server, "POST", "/send", {"to": "a@x.de"}, origin="https://boese.example")
    assert status == 403 and inhalt["error"] == "Ungültiger Origin"
    assert server["gesendet"] == []


def test_post_mit_fremdem_host_wird_abgelehnt(server):
    assert _anfrage(server, "POST", "/exclude", {"profil_url": "x"}, host="boese.example")[0] == 403


def test_post_unbekannter_pfad_ist_404(server):
    assert _anfrage(server, "POST", "/gibt-es-nicht", {"a": 1})[0] == 404


# ---------- Statistik ----------

def test_statistik_zaehlt_kontaktierte_und_offene(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main.pfade, "RESULTS_RAW", tmp_path / "raw.json")
    monkeypatch.setattr(main.pfade, "RESULTS_ANALYZED", tmp_path / "analysiert.json")
    monkeypatch.setattr(main, "SENT_LOG_FILE", tmp_path / "sent.json")
    (tmp_path / "raw.json").write_text(json.dumps([{}, {}, {}]))
    (tmp_path / "analysiert.json").write_text(json.dumps([
        {"profil_url": "a", "email": "a@x.de"}, {"profil_url": "b", "email": "b@x.de"}, {"profil_url": "c"}]))
    (tmp_path / "sent.json").write_text(json.dumps([
        {"profil_url": "a", "name": "Praxis A", "email": "a@x.de", "timestamp": "2026-10-01T10:00:00"}]))
    main._print_stats()
    aus = capsys.readouterr().out
    assert "Gescrapte Profile:              3" in aus
    assert "Bereits kontaktiert:            1" in aus
    assert "Noch offen (mit Email):         1" in aus
    assert "Keine Email (nicht kontaktierbar): 1" in aus
    assert "2026-10-01  Praxis A  <a@x.de>" in aus


# ---------- main(): Ablauf je nach Schalter ----------

@pytest.fixture
def ablauf(monkeypatch):
    """Ersetzt alles, was main() nach aussen tut (Scraper, Analyzer, Server,
    Browser), durch Protokoll-Eintraege."""
    protokoll = []
    scraper = types.ModuleType("scraper")

    async def scraper_main():
        protokoll.append("scraper")

    async def enrich_emails():
        protokoll.append("emails")

    scraper.main, scraper.enrich_emails = scraper_main, enrich_emails
    analyzer = types.ModuleType("analyzer")
    analyzer.main = lambda: protokoll.append("analyzer")
    monkeypatch.setitem(sys.modules, "scraper", scraper)
    monkeypatch.setitem(sys.modules, "analyzer", analyzer)
    monkeypatch.setattr(main, "start_server", lambda: protokoll.append("server"))
    monkeypatch.setattr(main.webbrowser, "open", lambda url: protokoll.append("browser"))
    monkeypatch.setattr(main, "_print_stats", lambda: protokoll.append("stats"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def starte(*schalter):
        monkeypatch.setattr(sys, "argv", ["main.py", *schalter])
        main.main()
        return protokoll
    starte.protokoll = protokoll
    return starte


def test_main_kompletter_lauf(ablauf):
    assert ablauf() == ["scraper", "analyzer", "server", "browser"]


def test_main_nur_analyse(ablauf):
    assert ablauf("--skip-scraper") == ["analyzer", "server", "browser"]


def test_main_nur_scrapen_braucht_keinen_key(ablauf, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert ablauf("--skip-analyzer") == ["scraper", "server", "browser"]


def test_main_nur_emails(ablauf):
    assert ablauf("--only-emails") == ["emails"]


def test_main_nur_statistik(ablauf):
    assert ablauf("--stats") == ["stats"]


@pytest.mark.parametrize("wert", ["", "platzhalter"])
def test_main_ohne_api_key_bricht_vor_dem_scraper_ab(ablauf, monkeypatch, wert):
    monkeypatch.setenv("ANTHROPIC_API_KEY", wert)
    with pytest.raises(SystemExit):
        ablauf()
    assert ablauf.protokoll == []   # Scraper ist gar nicht erst gestartet
