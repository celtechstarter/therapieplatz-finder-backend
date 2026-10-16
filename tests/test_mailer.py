"""Tests fuer mailer.py -- ohne echte Gmail-API-Aufrufe (get_gmail_service
wird gemockt). Fokus: Empfaenger-Validierung und Header-Injection-Schutz
(Audit-Befund M6), da send_email die zweite Verteidigungslinie hinter
main.py's eigener Pruefung ist (send_email kann auch direkt aus anderen
Skripten aufgerufen werden)."""
import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import mailer


def _fake_service():
    service = MagicMock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "123"}
    return service


def test_send_email_lehnt_ungueltige_adresse_ab():
    with patch.object(mailer, "get_gmail_service") as m:
        try:
            mailer.send_email("keine-email", "Betreff", "Text")
            assert False, "haette ValueError werfen muessen"
        except ValueError:
            pass
        m.assert_not_called()  # Service darf gar nicht erst gebaut werden


def test_send_email_lehnt_mehrfachempfaenger_ab():
    with patch.object(mailer, "get_gmail_service") as m:
        try:
            mailer.send_email("a@b.de, opfer@x.de", "Betreff", "Text")
            assert False, "haette ValueError werfen muessen"
        except ValueError:
            pass
        m.assert_not_called()


def test_send_email_lehnt_header_injection_im_empfaenger_ab():
    with patch.object(mailer, "get_gmail_service") as m:
        boesartig = "a@b.de\r\nBcc: opfer@x.de"
        try:
            mailer.send_email(boesartig, "Betreff", "Text")
            assert False, "haette ValueError werfen muessen"
        except ValueError:
            pass
        m.assert_not_called()


def test_send_email_entfernt_newlines_aus_betreff():
    with patch.object(mailer, "get_gmail_service", return_value=_fake_service()):
        result = mailer.send_email("praxis@example.de", "Anfrage\r\nBcc: opfer@x.de", "Text")
        assert result["id"] == "123"


def test_send_email_gueltige_adresse_funktioniert():
    service = _fake_service()
    with patch.object(mailer, "get_gmail_service", return_value=service):
        result = mailer.send_email("praxis@example-praxis.de", "Anfrage Therapieplatz", "Hallo,\nText mit Umlauten äöü.")
        assert result["id"] == "123"
        service.users.return_value.messages.return_value.send.assert_called_once()


# ---------- _token_schreiben: Rechte 0600 ab dem ersten Byte (Befund S3) ----------

def test_token_wird_direkt_mit_0600_angelegt(tmp_path, monkeypatch):
    """token.json ist faktisch ein Dauerzugriff auf Marcels Postfach. Bei
    open()+chmod() existierte die Datei zwischen beiden Schritten kurz mit
    den Standardrechten (oft 0644) -- und der Token stand da schon drin.
    os.open mit Modus beim Anlegen schliesst dieses Zeitfenster."""
    ziel = tmp_path / "token.json"
    monkeypatch.setattr(mailer, "TOKEN_FILE", str(ziel))
    creds = MagicMock()
    creds.to_json.return_value = '{"refresh_token": "geheim"}'

    aufruf = {}
    echtes_os_open = os.open

    def fake_os_open(pfad, flags, mode=0o777, **kwargs):
        aufruf["flags"] = flags
        aufruf["mode"] = mode
        return echtes_os_open(pfad, flags, mode, **kwargs)

    monkeypatch.setattr(mailer.os, "open", fake_os_open)
    mailer._token_schreiben(creds)

    assert aufruf["mode"] == 0o600
    assert aufruf["flags"] & os.O_CREAT
    assert aufruf["flags"] & os.O_TRUNC
    assert ziel.read_text(encoding="utf-8") == '{"refresh_token": "geheim"}'
    if os.name != "nt":  # unter Windows hat der POSIX-Modus keine Bedeutung
        assert stat.S_IMODE(ziel.stat().st_mode) == 0o600


def test_token_schreiben_ueberschreibt_alten_inhalt_vollstaendig(tmp_path, monkeypatch):
    """O_TRUNC: ein laengerer alter Token darf keine Reste hinterlassen,
    sonst entsteht kaputtes JSON, das beim naechsten Start nicht mehr
    geladen werden kann."""
    ziel = tmp_path / "token.json"
    ziel.write_text("x" * 500, encoding="utf-8")
    monkeypatch.setattr(mailer, "TOKEN_FILE", str(ziel))
    creds = MagicMock()
    creds.to_json.return_value = '{"kurz": 1}'
    mailer._token_schreiben(creds)
    assert ziel.read_text(encoding="utf-8") == '{"kurz": 1}'


# ---------- get_gmail_service schreibt den Token immer (Befund B9) ----------

def test_get_gmail_service_schreibt_token_immer(monkeypatch):
    """Frueher stand hier ein if/else, dessen beide Zweige exakt dasselbe
    taten. Das Verhalten ist gewollt (nach einem Refresh kann sich der Token
    geaendert haben) -- der Test haelt es fest, damit beim Aufraeumen nicht
    versehentlich das Schreiben selbst wegfaellt."""
    monkeypatch.setattr(mailer, "_service", None)
    creds = MagicMock()
    creds.expired = False
    creds.valid = True
    monkeypatch.setattr(mailer.os.path, "exists", lambda p: True)
    monkeypatch.setattr(mailer.Credentials, "from_authorized_user_file",
                        classmethod(lambda cls, *a, **k: creds))
    geschrieben = []
    monkeypatch.setattr(mailer, "_token_schreiben", geschrieben.append)
    monkeypatch.setattr(mailer, "build", lambda *a, **k: "fake-service")

    assert mailer.get_gmail_service() == "fake-service"
    assert geschrieben == [creds]


def test_get_gmail_service_cacht_den_service(monkeypatch):
    monkeypatch.setattr(mailer, "_service", "schon-da")
    monkeypatch.setattr(mailer, "_token_schreiben",
                        lambda c: (_ for _ in ()).throw(AssertionError("darf nicht schreiben")))
    assert mailer.get_gmail_service() == "schon-da"
