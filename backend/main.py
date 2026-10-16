import asyncio
import http.server
import json
import os
import posixpath
import re
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from urllib.parse import unquote

from dotenv import load_dotenv
load_dotenv()

import pfade
from dateihilfen import json_atomar_schreiben, json_sicher_laden

PORT = 8080
BASE_DIR = pfade.FRONTEND_DIR.parent  # = backend/, wird als statisches Wurzelverzeichnis fuer /frontend/ genutzt
SENT_LOG_FILE = pfade.SENT_LOG
EXCLUDED_FILE = pfade.MANUELL_AUSGESCHLOSSEN

# Erlaubte Ursprünge für Requests an diesen lokalen Server. Ohne diese Prüfung
# kann jede im Browser geöffnete fremde Webseite per fetch() Emails über
# dieses Gmail-Konto verschicken (CSRF) oder die Therapeutendatenbank lesen.
ERLAUBTE_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
MAX_BODY_BYTES = 256 * 1024  # 256 KB reichen für alle Requests dieser App
EMAIL_MUSTER = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Sekunden, die ein einzelner Client maximal für seinen Request brauchen darf.
# Der Server ist single-threaded: eine Verbindung, die den Header anfängt und
# dann einfach offen stehen bleibt (Slowloris, oder schlicht ein abgestürzter
# Browser-Tab), würde ihn sonst dauerhaft blockieren – die lokale Oberfläche
# wäre bis zum Neustart tot.
REQUEST_TIMEOUT = 10

# Nach außen sichtbare Fehlermeldung. Details (Exception-Typ, Traceback,
# Dateipfade) gehören nur ins Terminal, nicht in die HTTP-Antwort.
GENERISCHER_FEHLER = "Interner Fehler – Details stehen im Terminal-Fenster."


def ist_erlaubter_pfad(raw_path):
    """Prüft, ob ein angefragter Pfad ausgeliefert werden darf. Kanonisiert
    (Prozent-Dekodierung + normpath) VOR der Prüfung – sonst kann
    /frontend/%2e%2e/.env die Whitelist umgehen (Path Traversal)."""
    pfad = raw_path.split("?")[0].split("#")[0]
    pfad = posixpath.normpath(unquote(pfad))
    if pfad in ("/results_analyzed.json", "/results_raw.json"):
        return True
    if pfad.startswith("/frontend/") and ".." not in pfad.split("/"):
        return True
    return False


def _load_sent_log():
    # json_sicher_laden faengt auch eine kaputte/abgeschnittene Datei ab
    # (z.B. nach einem Absturz mitten im Schreiben) statt den ganzen Server
    # mit einer unbehandelten JSONDecodeError abstuerzen zu lassen.
    return json_sicher_laden(SENT_LOG_FILE, [])


def _save_sent_log(entries):
    json_atomar_schreiben(SENT_LOG_FILE, entries)


def _load_excluded():
    """Manuell ausgeblendete Profile laden.

    isinstance(e, dict)-Filter: die Datei wird von Hand bearbeitbar im
    data/-Ordner gehalten. Steht dort strukturell falsches JSON (z.B. eine
    Liste von Strings statt von Objekten), warf jeder folgende e["profil_url"]
    einen TypeError und der ganze Server-Endpunkt lief auf 500. Kaputte
    Einträge werden jetzt einfach ignoriert."""
    roh = json_sicher_laden(EXCLUDED_FILE, [])
    if not isinstance(roh, list):
        return []
    return [e for e in roh if isinstance(e, dict)]


def _save_excluded(entries):
    json_atomar_schreiben(EXCLUDED_FILE, entries)


class AppRequestHandler(http.server.SimpleHTTPRequestHandler):
    # socketserver.StreamRequestHandler wertet dieses Klassenattribut beim
    # Verbindungsaufbau aus (siehe auch setup() unten).
    timeout = REQUEST_TIMEOUT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def setup(self):
        super().setup()
        # Harte Obergrenze pro Verbindung: ohne Timeout blockiert ein Client,
        # der einen Content-Length ankündigt und dann nichts mehr sendet, den
        # single-threaded Server unbegrenzt (self.rfile.read wartet ewig).
        self.connection.settimeout(REQUEST_TIMEOUT)

    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin in ERLAUBTE_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _origin_ok(self):
        """Schutz gegen CSRF/DNS-Rebinding: Requests, die etwas verändern
        (senden, ausblenden, wiederherstellen), müssen vom eigenen Frontend
        kommen. Ein Origin-Header fehlt bei echten Cross-Site-Attacken nie,
        weil Browser ihn bei fetch()/XHR immer mitschicken."""
        origin = self.headers.get("Origin")
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("localhost", "127.0.0.1"):
            return False
        # Kein Origin-Header heißt: Request kam nicht per Browser-fetch von
        # einer anderen Seite (z.B. direkter Aufruf durch die App selbst
        # via same-origin-Navigation) – das lassen wir zu, alles andere mit
        # falschem Origin nicht.
        return origin is None or origin in ERLAUBTE_ORIGINS

    def do_GET(self):
        if ist_erlaubter_pfad(self.path):
            pfad_ohne_query = self.path.split("?")[0]
            if pfad_ohne_query == "/results_analyzed.json":
                self._json_response(json_sicher_laden(pfade.RESULTS_ANALYZED, []))
                return
            if pfad_ohne_query == "/results_raw.json":
                self._json_response(json_sicher_laden(pfade.RESULTS_RAW, []))
                return
            # /frontend/... -> normale statische Auslieferung aus BASE_DIR
            self.path = posixpath.normpath(unquote(pfad_ohne_query))
            super().do_GET()
            return
        path = self.path.split("?")[0]
        if path == "/sent-log":
            self._json_response(_load_sent_log())
        elif path == "/excluded":
            self._json_response(_load_excluded())
        elif path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/frontend/index.html")
            self.end_headers()
        else:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Zugriff verweigert")

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if not self._origin_ok():
            self._json_response({"ok": False, "error": "Ungültiger Origin"}, status=403)
            return
        if self.path == "/send":
            self._handle_send()
        elif self.path == "/exclude":
            self._handle_exclude()
        elif self.path == "/restore":
            self._handle_restore()
        else:
            self.send_response(404)
            self.end_headers()

    def _lies_body(self):
        """Liest und parst den Request-Body, mit Obergrenze gegen einen
        vorgetäuschten riesigen Content-Length (sonst blockiert read() den
        kompletten – single-threaded – Server unbegrenzt lange).

        Wirft ausschließlich ValueError mit selbst formulierten, gefahrlosen
        Texten – auch für kaputtes JSON. So kann der Aufrufer ValueError-
        Meldungen bedenkenlos an den Client zurückgeben (siehe
        _fehler_antwort), ohne interne Details zu verraten."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("Ungültige Content-Length")
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Anfrage zu groß oder leer")
        rohdaten = self.rfile.read(length)
        try:
            return json.loads(rohdaten)
        except json.JSONDecodeError:
            raise ValueError("Ungültiger JSON-Body")

    def _fehler_antwort(self, exc, status=500):
        """Antwortet dem Client, ohne Exception-Details preiszugeben.

        Vorher ging `str(e)` jeder beliebigen Exception direkt an den Client.
        Das konnte absolute Dateipfade, Modulnamen oder Google-API-interne
        Meldungen (inkl. Teilen der Antwort des Mailservers) in die
        Oberfläche spülen. Jetzt gilt: eigene Validierungsfehler
        (ValueError, alle Texte oben selbst formuliert) sind unbedenklich und
        helfen beim Bedienen; alles andere bekommt eine generische Meldung,
        die Details landen mit vollem Traceback im Terminal."""
        if sys.exc_info()[0] is not None:
            traceback.print_exc()
        if isinstance(exc, ValueError):
            self._json_response({"ok": False, "error": str(exc)}, status=400)
            return
        print(f"  -> Anfrage fehlgeschlagen: {exc.__class__.__name__}", file=sys.stderr)
        self._json_response({"ok": False, "error": GENERISCHER_FEHLER}, status=status)

    def _handle_exclude(self):
        try:
            body = self._lies_body()
            profil_url = body.get("profil_url", "")
            name = body.get("name", "")
            if not profil_url:
                raise ValueError("profil_url fehlt")
            entries = _load_excluded()
            if not any(e.get("profil_url") == profil_url for e in entries):
                entries.append({
                    "profil_url": profil_url,
                    "name": name,
                    "excluded_at": datetime.now().isoformat(timespec="seconds"),
                })
                _save_excluded(entries)
            self._json_response({"ok": True})
        except Exception as e:
            self._fehler_antwort(e)

    def _handle_restore(self):
        try:
            body = self._lies_body()
            profil_url = body.get("profil_url", "")
            # .get() statt e["profil_url"]: ein Eintrag ohne dieses Feld hat
            # den Endpunkt sonst mit KeyError auf 500 laufen lassen.
            entries = [e for e in _load_excluded() if e.get("profil_url") != profil_url]
            _save_excluded(entries)
            self._json_response({"ok": True})
        except Exception as e:
            self._fehler_antwort(e)

    def _handle_send(self):
        try:
            body = self._lies_body()
            to = (body.get("to") or "").strip()
            subject = body.get("subject", "Anfrage Therapieplatz")
            text = body.get("body", "")

            if not to or not EMAIL_MUSTER.fullmatch(to) or "," in to:
                raise ValueError("Ungültige Empfänger-Email")
            # \r/\n in Subject entfernen: verhindert Header-Injection, falls
            # eine künftige Änderung mal einen anderen Mail-Baustein nutzt,
            # der weniger streng validiert als das email-Modul.
            subject = "".join(ch for ch in str(subject) if ch not in "\r\n")[:200]

            # Duplikatschutz: nicht zweimal an dieselbe Praxis senden
            profil_url = body.get("profil_url", "")
            log = _load_sent_log()
            schon = [e for e in log
                     if e.get("email") == to or (profil_url and e.get("profil_url") == profil_url)]
            if schon and not body.get("force"):
                self._json_response({
                    "ok": False,
                    "error": f"Bereits am {schon[0].get('timestamp','?')[:10]} kontaktiert. "
                             f"Zum trotzdem Senden 'force' setzen."
                }, status=409)
                return

            import mailer
            mailer.send_email(to, subject, text)

            entry = {
                "profil_url": profil_url,
                "name": body.get("name", ""),
                "email": to,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "subject": subject,
            }
            log.append(entry)
            _save_sent_log(log)

            self._json_response({"ok": True, "entry": entry})
        except Exception as e:
            # Wichtig gerade hier: die Gmail-API wirft HttpError-Objekte, deren
            # str() den kompletten Antwort-Body inklusive interner Kennungen
            # enthaelt. Der gehoert ins Terminal, nicht in die Oberflaeche.
            self._fehler_antwort(e)

    def _json_response(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # Stille Logs


def _print_stats():
    raw = json_sicher_laden(pfade.RESULTS_RAW, [])
    analyzed = json_sicher_laden(pfade.RESULTS_ANALYZED, [])
    sent_log = _load_sent_log()
    sent_urls = {e.get("profil_url") for e in sent_log if e.get("profil_url")}

    with_email = [t for t in analyzed if t.get("email")]
    contacted = [t for t in analyzed if t.get("profil_url") in sent_urls]
    open_with_email = [t for t in with_email if t.get("profil_url") not in sent_urls]
    no_email = [t for t in analyzed if not t.get("email") and t.get("profil_url") not in sent_urls]

    print("\n=== STATISTIK ===")
    print(f"  Gescrapte Profile:              {len(raw)}")
    print(f"  Relevante Therapeuten:          {len(analyzed)}")
    print(f"  Davon mit Email:                {len(with_email)}")
    print(f"  Bereits kontaktiert:            {len(contacted)}")
    print(f"  Noch offen (mit Email):         {len(open_with_email)}")
    print(f"  Keine Email (nicht kontaktierbar): {len(no_email)}")
    if contacted:
        print("\n  Kontaktiert:")
        for e in sent_log:
            ts = e.get("timestamp", "")[:10]
            print(f"    {ts}  {e.get('name', '?')}  <{e.get('email', '')}>")


def start_server():
    # Nur localhost – niemand im WLAN kann auf den Server zugreifen
    httpd = http.server.HTTPServer(("127.0.0.1", PORT), AppRequestHandler)
    print(f"Server läuft auf http://localhost:{PORT} (nur dieser Rechner)")
    httpd.serve_forever()


async def run_scraper():
    print("\n=== SCHRITT 1: Scraper ===")
    import scraper
    await scraper.main()


def run_analyzer():
    print("\n=== SCHRITT 2: Analyzer ===")
    import analyzer
    analyzer.main()


def _pruefe_api_key():
    """Bricht ab, wenn der ANTHROPIC_API_KEY fehlt.

    Muss VOR dem Scraper laufen: der Scraper braucht den Key selbst nicht,
    laeuft aber je nach Datenmenge stundenlang. Danach ruft main() den
    Analyzer auf, und der beendet bei fehlendem Key den GESAMTEN Prozess mit
    sys.exit(1) – der komplette Scraping-Lauf war dann fuer die Katz. Lieber
    sofort und mit klarer Ansage abbrechen."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key and key != "platzhalter":
        return
    print("FEHLER: ANTHROPIC_API_KEY ist nicht gesetzt.")
    print("Der Analyzer (Schritt 2) braucht ihn zwingend – ohne Key waere der")
    print("stundenlange Scraper-Lauf davor umsonst. Deshalb Abbruch jetzt.")
    print("")
    print("Loesungen:")
    print("  - Key in die Datei .env im Projekt-Root eintragen:")
    print("      ANTHROPIC_API_KEY=sk-ant-...")
    print("  - oder in der aktuellen Shell setzen: export ANTHROPIC_API_KEY=...")
    print("  - oder nur scrapen, ohne KI-Analyse: python main.py --skip-analyzer")
    sys.exit(1)


def main():
    print("=== Therapie-Mailer ===\n")

    if "--stats" in sys.argv:
        _print_stats()
        return

    # Nur Email-Suche auf bereits gescrapten Daten
    if "--only-emails" in sys.argv:
        print("=== MODUS: Nur Email-Suche ===")
        import scraper
        asyncio.run(scraper.enrich_emails())
        return

    # Vor dem Scraper pruefen, nicht danach (siehe _pruefe_api_key).
    # Mit --skip-analyzer wird der Key nicht gebraucht.
    if "--skip-analyzer" not in sys.argv:
        _pruefe_api_key()

    if "--skip-scraper" not in sys.argv:
        asyncio.run(run_scraper())
    else:
        print("Scraper übersprungen (--skip-scraper)")

    if "--skip-analyzer" not in sys.argv:
        run_analyzer()
    else:
        print("Analyzer übersprungen (--skip-analyzer)")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    url = f"http://localhost:{PORT}/frontend/index.html"
    print(f"\nÖffne Browser: {url}")
    webbrowser.open(url)

    print("Drücke Ctrl+C zum Beenden.")
    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nServer beendet.")


if __name__ == "__main__":
    main()
