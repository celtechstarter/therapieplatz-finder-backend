import os
import re
import stat
import base64
from email.mime.text import MIMEText
from email.errors import HeaderParseError

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import pfade

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = str(pfade.CREDENTIALS_FILE)
TOKEN_FILE = str(pfade.TOKEN_FILE)
EMAIL_SUBJECT = "Anfrage Therapieplatz"

# Zweite Verteidigungslinie gegen ungueltige/manipulierte Empfaenger (die
# erste ist die Pruefung in main.py, aber send_email() kann auch direkt aus
# anderen Skripten aufgerufen werden).
EMAIL_MUSTER = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_service = None  # modulweiter Cache, siehe get_gmail_service()


def _token_schreiben(creds):
    """Schreibt token.json (Gmail-Refresh-Token, faktisch ein Dauerzugriff auf
    das Postfach) mit Rechten 0600.

    os.open(..., O_CREAT, 0o600) statt open()+chmod: bei der alten Reihenfolge
    existierte die Datei zwischen open() und chmod() kurz mit den
    Standardrechten des Systems (haeufig 0644, auf Mehrbenutzer-Systemen also
    fuer alle lesbar). Genau in diesem Fenster steht das Token bereits
    vollstaendig drin. Mit dem Modus direkt beim Anlegen gibt es dieses
    Fenster nicht mehr."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(TOKEN_FILE, flags, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    with os.fdopen(fd, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    try:
        # Falls die Datei schon vorher (mit weiteren Rechten) existierte:
        # O_CREAT setzt den Modus nur bei NEU angelegten Dateien.
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # unter Windows ohne Wirkung, aber harmlos


def get_gmail_service(force_login=False):
    """Baut den Gmail-Service EINMAL und cached ihn modulweit. Wichtig: bei
    ungueltigem/abgelaufenem Refresh-Token (z.B. weil die Google-App im
    Status 'Testing' ist -- Refresh-Tokens verfallen dann nach 7 Tagen) gab
    es bisher KEINEN Weg zurueck zur interaktiven Anmeldung, weil der
    else-Zweig durch die Bedingung ausgeschlossen war. Jetzt: RefreshError
    faengt das ab und startet den Login-Flow neu."""
    global _service
    if _service is not None and not force_login:
        return _service

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.expired and creds.refresh_token and not force_login:
        try:
            creds.refresh(Request())
        except RefreshError:
            print("Gmail-Anmeldung ist abgelaufen oder wurde widerrufen – bitte neu anmelden.")
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)

    # Immer schreiben: die Datei ist entweder neu, wurde per Refresh
    # aktualisiert oder stammt aus einem frischen Login -- in allen Faellen
    # gehoert der aktuelle Stand auf die Platte. (Vorher stand hier ein
    # if/else, dessen beide Zweige exakt dasselbe taten.)
    _token_schreiben(creds)

    _service = build("gmail", "v1", credentials=creds)
    return _service


def send_email(to_email, subject, body):
    """Sendet eine Email via Gmail API."""
    to_email = (to_email or "").strip()
    if not EMAIL_MUSTER.fullmatch(to_email) or "," in to_email:
        raise ValueError(f"Ungültige Empfänger-Adresse: {to_email!r}")

    service = get_gmail_service()

    message = MIMEText(body, "plain", "utf-8")
    # \r/\n aus Betreff/Empfänger entfernen: verhindert Header-Injection.
    # (email.mime.text wirft bei eingebetteten Newlines im Header ohnehin
    # HeaderParseError, das hier ist eine zweite, explizite Absicherung.)
    message["to"] = "".join(ch for ch in to_email if ch not in "\r\n")
    message["subject"] = "".join(ch for ch in str(subject) if ch not in "\r\n")[:200]

    try:
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    except HeaderParseError as e:
        raise ValueError(f"Ungültiger Betreff/Empfänger: {e}")

    result = service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()

    return result


if __name__ == "__main__":
    # Test
    print("Gmail-Authentifizierung testen...")
    service = get_gmail_service()
    print("Authentifizierung erfolgreich!")
