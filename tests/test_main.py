"""Tests fuer main.py: der lokale HTTP-Server, der die Web-Oberflaeche
ausliefert und Sende-Anfragen entgegennimmt. Fokus: der Path-Traversal-Fix
(K1), die Email-Validierung (M6), der CSRF-Schutz (_origin_ok), die
Body-Groessenbegrenzung (_lies_body) und die Fehlerausgabe -- alles
Regressionstests fuer echte, im Audit nachgewiesene Sicherheitsluecken."""
import http.server
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-fuer-pytest")

import main


def _handler(headers=None, body=b""):
    """Baut eine AppRequestHandler-Instanz OHNE Netzwerk/Socket.

    object.__new__ umgeht __init__ (das sonst sofort einen Request von einem
    echten Socket lesen wuerde); gesetzt wird nur, was die getesteten
    Methoden tatsaechlich brauchen."""
    h = object.__new__(main.AppRequestHandler)
    h.headers = headers or {}
    h.rfile = io.BytesIO(body)
    h.antworten = []
    h._json_response = lambda data, status=200: h.antworten.append((status, data))
    return h


# ---------- ist_erlaubter_pfad (Path Traversal, Audit-Befund K1) ----------

def test_pfad_frontend_datei_erlaubt():
    assert main.ist_erlaubter_pfad("/frontend/index.html") is True


def test_pfad_ergebnis_dateien_erlaubt():
    assert main.ist_erlaubter_pfad("/results_analyzed.json") is True
    assert main.ist_erlaubter_pfad("/results_raw.json") is True


def test_pfad_traversal_mit_dotdot_wird_abgelehnt():
    assert main.ist_erlaubter_pfad("/frontend/../.env") is False


def test_pfad_traversal_url_kodiert_wird_abgelehnt():
    """Das war die tatsaechliche Luecke (Befund K1): main.py prüfte die
    Whitelist auf dem ROHEN Pfad, aber Python/der SimpleHTTPRequestHandler
    dekodiert %2e%2e SPÄTER zu '..' -- die Prüfung wurde damit umgangen und
    main.py servierte .env/credentials.json/token.json aus."""
    assert main.ist_erlaubter_pfad("/frontend/%2e%2e/.env") is False
    assert main.ist_erlaubter_pfad("/frontend/..%2f.env") is False


def test_pfad_direkter_zugriff_auf_env_wird_abgelehnt():
    assert main.ist_erlaubter_pfad("/.env") is False
    assert main.ist_erlaubter_pfad("/credentials.json") is False
    assert main.ist_erlaubter_pfad("/token.json") is False


def test_pfad_mit_query_string_wird_korrekt_geprueft():
    assert main.ist_erlaubter_pfad("/frontend/index.html?x=1") is True
    assert main.ist_erlaubter_pfad("/frontend/%2e%2e/.env?x=1") is False


# ---------- EMAIL_MUSTER (Header-Injection/Massen-Empfaenger, Befund M6) ----------

def test_email_muster_akzeptiert_gueltige_adresse():
    assert main.EMAIL_MUSTER.fullmatch("praxis@example.de")


def test_email_muster_lehnt_mehrfachempfaenger_ab():
    """'a@b.de, opfer@x.de' ist eine legale Kopfzeile fuer Mehrfachversand
    -- in main._handle_send wird zusaetzlich explizit auf ein Komma
    geprueft (nicht nur das Regex-fullmatch), das hier dokumentiert wird."""
    to = "a@b.de, opfer@x.de"
    assert not main.EMAIL_MUSTER.fullmatch(to) or "," in to


def test_email_muster_lehnt_header_injection_ab():
    boesartig = "a@b.de\r\nBcc: opfer@x.de"
    assert main.EMAIL_MUSTER.fullmatch(boesartig) is None


def test_email_muster_lehnt_leer_und_muell_ab():
    assert main.EMAIL_MUSTER.fullmatch("") is None
    assert main.EMAIL_MUSTER.fullmatch("keine-email") is None


# ---------- _load_sent_log / _save_sent_log (Roundtrip, Befund H1) ----------

def test_sent_log_roundtrip(tmp_path, monkeypatch):
    datei = tmp_path / "sent_log.json"
    monkeypatch.setattr(main, "SENT_LOG_FILE", datei)
    eintraege = [{"profil_url": "u1", "email": "a@b.de", "name": "Ärztin Müller"}]
    main._save_sent_log(eintraege)
    geladen = main._load_sent_log()
    assert geladen == eintraege
    assert "Ärztin" in datei.read_text(encoding="utf-8")  # ensure_ascii=False


def test_sent_log_fehlende_datei_gibt_leere_liste(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SENT_LOG_FILE", tmp_path / "gibt-es-nicht.json")
    assert main._load_sent_log() == []


# ---------- _origin_ok (CSRF/DNS-Rebinding, Audit-Befund T2) ----------
#
# Ohne diese Pruefung kann jede beliebige im Browser geoeffnete Webseite per
# fetch() Emails ueber das angemeldete Gmail-Konto verschicken oder die
# Therapeutendaten auslesen, solange der lokale Server laeuft.

def test_origin_ok_erlaubt_eigenes_frontend():
    h = _handler({"Host": f"localhost:{main.PORT}", "Origin": f"http://localhost:{main.PORT}"})
    assert h._origin_ok() is True
    h = _handler({"Host": f"127.0.0.1:{main.PORT}", "Origin": f"http://127.0.0.1:{main.PORT}"})
    assert h._origin_ok() is True


def test_origin_ok_lehnt_fremden_origin_ab():
    h = _handler({"Host": f"localhost:{main.PORT}", "Origin": "https://evil.example"})
    assert h._origin_ok() is False


def test_origin_ok_erlaubt_fehlenden_origin():
    """Kein Origin-Header heisst: kein Cross-Site-fetch aus einem Browser
    (z.B. curl oder ein Aufruf der App selbst). Browser setzen den Header
    bei fetch()/XHR immer, deshalb ist das kein Umgehungsweg."""
    h = _handler({"Host": f"localhost:{main.PORT}"})
    assert h._origin_ok() is True


def test_origin_ok_lehnt_fremden_host_header_ab():
    """DNS-Rebinding: ein Angreifer laesst seine Domain auf 127.0.0.1
    zeigen. Der Browser schickt dann Host: angreifer.example mit -- der
    Request kommt zwar am lokalen Server an, gehoert aber nicht dazu."""
    h = _handler({"Host": "angreifer.example", "Origin": f"http://localhost:{main.PORT}"})
    assert h._origin_ok() is False
    h = _handler({"Host": "angreifer.example"})
    assert h._origin_ok() is False


# ---------- _lies_body (Groessenbegrenzung, Audit-Befund T2) ----------

def test_lies_body_akzeptiert_gueltigen_json_body():
    daten = b'{"profil_url": "u1"}'
    h = _handler({"Content-Length": str(len(daten))}, body=daten)
    assert h._lies_body() == {"profil_url": "u1"}


def test_lies_body_lehnt_leeren_body_ab():
    h = _handler({"Content-Length": "0"})
    with pytest.raises(ValueError):
        h._lies_body()


def test_lies_body_lehnt_negative_content_length_ab():
    h = _handler({"Content-Length": "-1"})
    with pytest.raises(ValueError):
        h._lies_body()


def test_lies_body_lehnt_zu_grossen_body_ab():
    """Ohne Obergrenze blockiert ein vorgetaeuschter Riesen-Body den
    single-threaded Server, bis der Client fertig sendet (oder nie)."""
    h = _handler({"Content-Length": str(main.MAX_BODY_BYTES + 1)})
    with pytest.raises(ValueError):
        h._lies_body()


def test_lies_body_lehnt_nicht_numerische_content_length_ab():
    h = _handler({"Content-Length": "abc"})
    with pytest.raises(ValueError):
        h._lies_body()


def test_lies_body_wirft_bei_kaputtem_json_nur_valueerror():
    """Wichtig fuer die Fehlerausgabe: alle Fehler aus _lies_body sind
    ValueError mit selbst formuliertem Text, damit _fehler_antwort sie
    gefahrlos an den Client zurueckgeben kann."""
    daten = b'{kaputt'
    h = _handler({"Content-Length": str(len(daten))}, body=daten)
    with pytest.raises(ValueError) as info:
        h._lies_body()
    assert "JSON" in str(info.value)


# ---------- _fehler_antwort (Audit-Befund S5) ----------

def test_fehler_antwort_verraet_keine_exception_details():
    """Vorher ging str(e) jeder Exception an den Client -- inklusive
    absoluter Dateipfade und Gmail-API-Antworten."""
    h = _handler()
    h._fehler_antwort(RuntimeError("/home/marcel/geheim/token.json ist kaputt"))
    status, daten = h.antworten[0]
    assert status == 500
    assert daten["ok"] is False
    assert daten["error"] == main.GENERISCHER_FEHLER
    assert "token.json" not in daten["error"]
    assert "/home/marcel" not in daten["error"]


def test_fehler_antwort_gibt_eigene_validierungsmeldung_weiter():
    """Eigene ValueError-Texte sind selbst formuliert und helfen beim
    Bedienen -- die duerfen (mit Status 400) sichtbar bleiben."""
    h = _handler()
    h._fehler_antwort(ValueError("Ungültige Empfänger-Email"))
    status, daten = h.antworten[0]
    assert status == 400
    assert daten["error"] == "Ungültige Empfänger-Email"


# ---------- Socket-Timeout (Audit-Befund S6) ----------

def test_handler_hat_request_timeout():
    assert main.REQUEST_TIMEOUT > 0
    assert main.AppRequestHandler.timeout == main.REQUEST_TIMEOUT


def test_setup_setzt_socket_timeout(monkeypatch):
    """Ohne settimeout kann ein Client, der die Verbindung oeffnet und dann
    schweigt, den single-threaded Server dauerhaft einfrieren."""
    gesetzt = []

    class FakeConnection:
        def settimeout(self, wert):
            gesetzt.append(wert)

    def fake_setup(self):
        self.connection = FakeConnection()

    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "setup", fake_setup)
    h = object.__new__(main.AppRequestHandler)
    h.setup()
    assert gesetzt == [main.REQUEST_TIMEOUT]


# ---------- _load_excluded / _handle_restore (Audit-Befund B5) ----------

def test_load_excluded_ignoriert_strukturell_falsches_json(tmp_path, monkeypatch):
    """excluded.json wird von Hand bearbeitbar in data/ gehalten. Eine Liste
    von Strings statt von Objekten liess frueher jeden e["profil_url"] mit
    TypeError auflaufen und den Endpunkt auf 500 gehen."""
    datei = tmp_path / "excluded.json"
    datei.write_text(json.dumps(["nur-ein-string", {"profil_url": "u1"}, None, 42]),
                     encoding="utf-8")
    monkeypatch.setattr(main, "EXCLUDED_FILE", datei)
    assert main._load_excluded() == [{"profil_url": "u1"}]


def test_load_excluded_bei_objekt_statt_liste(tmp_path, monkeypatch):
    datei = tmp_path / "excluded.json"
    datei.write_text('{"profil_url": "u1"}', encoding="utf-8")
    monkeypatch.setattr(main, "EXCLUDED_FILE", datei)
    assert main._load_excluded() == []


def test_restore_uebersteht_eintrag_ohne_profil_url(tmp_path, monkeypatch):
    """Regression zu B5: e["profil_url"] warf KeyError, sobald ein Eintrag
    das Feld nicht hatte -- Wiederherstellen war dann komplett kaputt."""
    datei = tmp_path / "excluded.json"
    datei.write_text(json.dumps([{"name": "ohne url"}, {"profil_url": "u1"}]),
                     encoding="utf-8")
    monkeypatch.setattr(main, "EXCLUDED_FILE", datei)
    koerper = json.dumps({"profil_url": "u1"}).encode()
    h = _handler({"Content-Length": str(len(koerper))}, body=koerper)
    h._handle_restore()
    assert h.antworten == [(200, {"ok": True})]
    assert json.loads(datei.read_text(encoding="utf-8")) == [{"name": "ohne url"}]


def test_exclude_uebersteht_eintrag_ohne_profil_url(tmp_path, monkeypatch):
    datei = tmp_path / "excluded.json"
    datei.write_text(json.dumps([{"name": "ohne url"}]), encoding="utf-8")
    monkeypatch.setattr(main, "EXCLUDED_FILE", datei)
    koerper = json.dumps({"profil_url": "u2", "name": "Neu"}).encode()
    h = _handler({"Content-Length": str(len(koerper))}, body=koerper)
    h._handle_exclude()
    assert h.antworten == [(200, {"ok": True})]
    gespeichert = json.loads(datei.read_text(encoding="utf-8"))
    assert [e.get("profil_url") for e in gespeichert] == [None, "u2"]


def test_exclude_ohne_profil_url_meldet_fehler_mit_status_400(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "EXCLUDED_FILE", tmp_path / "excluded.json")
    koerper = json.dumps({"name": "ohne url"}).encode()
    h = _handler({"Content-Length": str(len(koerper))}, body=koerper)
    h._handle_exclude()
    status, daten = h.antworten[0]
    assert status == 400
    assert daten["ok"] is False


# ---------- _pruefe_api_key (Audit-Befund B4) ----------

def test_pruefe_api_key_bricht_ohne_key_ab(monkeypatch):
    """Der Check muss VOR dem Scraper laufen: sonst laeuft der stundenlange
    Scrape durch und erst analyzer.main() beendet den Prozess mit exit(1)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as info:
        main._pruefe_api_key()
    assert info.value.code == 1


def test_pruefe_api_key_bricht_bei_platzhalter_ab(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platzhalter")
    with pytest.raises(SystemExit):
        main._pruefe_api_key()


def test_pruefe_api_key_laesst_echten_key_durch(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-echt")
    main._pruefe_api_key()  # darf nicht werfen
