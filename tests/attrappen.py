"""Gemeinsame Attrappen für die Scraper-Tests: Browser, Seite, DNS.

Sie verhalten sich wie die passenden Playwright-Objekte, soweit der Code sie
benutzt, und schreiben mit, was mit ihnen passiert ist (welche Seiten
besucht wurden, welche Browser-Optionen gesetzt wurden). So lässt sich das
Verhalten prüfen, ohne echten Browser und ohne Internet.
"""
import socket


class Antwort:
    def __init__(self, status=200):
        self.status = status


class FakePage:
    """Eine Seite, deren Inhalt pro URL vorgegeben wird.

    seiten = {url: {"links": [...], "weiter": "url", "html": "...",
                    "status": 200, "unterseiten": [...], "fehler": True,
                    "mailto": [...], "weiterleitung": "url"}}
    """

    def __init__(self, seiten=None):
        self.seiten = seiten or {}
        self.url = "about:blank"
        self.besucht = []
        self.screenshots = []

    def _eintrag(self):
        return self.seiten.get(self.url, {})

    async def goto(self, url, wait_until=None, timeout=None):
        eintrag = self.seiten.get(url, {})
        if eintrag.get("fehler"):
            raise TimeoutError("lädt nicht")
        self.besucht.append(url)
        self.url = eintrag.get("weiterleitung", url)
        return Antwort(eintrag.get("status", 200))

    async def content(self):
        return self._eintrag().get("html", "<html></html>")

    async def wait_for_selector(self, selektor, timeout=None):
        if not self._eintrag().get("links"):
            raise TimeoutError("keine Trefferliste")

    async def eval_on_selector_all(self, selektor, js):
        return self._eintrag().get("links", [])

    async def query_selector(self, selektor):
        weiter = self._eintrag().get("weiter")
        if not weiter:
            return None

        class _Link:
            async def get_attribute(self, name):
                return weiter
        return _Link()

    async def evaluate(self, js, *args):
        eintrag = self._eintrag()
        if "mailto" in js:
            return eintrag.get("mailto", [])
        if "kontakt" in js:
            return eintrag.get("unterseiten", [])
        return eintrag.get("html", "")

    async def screenshot(self, **optionen):
        self.screenshots.append(optionen)


class FakeKontext:
    def __init__(self, page, protokoll):
        self.page, self.protokoll = page, protokoll

    async def route(self, muster, handler):
        self.protokoll.append(("route", muster))

    async def add_init_script(self, *args, **kwargs):
        self.protokoll.append(("init_script", args, kwargs))

    async def new_page(self):
        self.protokoll.append(("new_page",))
        return self.page


class FakePlaywright:
    """Ersetzt async_playwright(). `protokoll` hält alles fest, was mit dem
    Browser gemacht wurde, in der Reihenfolge des Aufrufs."""

    def __init__(self, page=None, schliessen_fehler=False):
        self.page = page or FakePage()
        self.protokoll = []
        self.start_optionen = None
        self.kontext_optionen = None
        self.geschlossen = False
        self.schliessen_fehler = schliessen_fehler

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def chromium(self):
        return self

    async def launch(self, **optionen):
        self.start_optionen = optionen
        return self

    async def new_context(self, **optionen):
        self.kontext_optionen = optionen
        return FakeKontext(self.page, self.protokoll)

    async def close(self):
        if self.schliessen_fehler:
            raise RuntimeError("Browser hängt")
        self.geschlossen = True


class FakeRoute:
    def __init__(self, url):
        self.request = FakeRequest(url)
        self.aktion = None

    async def continue_(self):
        self.aktion = "continue"

    async def abort(self, fehlercode=None):
        self.aktion = "abort"


class FakeRequest:
    def __init__(self, url):
        self.url = url


FAKE_DNS = {
    "praxis-beispiel.de": "93.184.216.34",
    "cdn.praxis-beispiel.de": "93.184.216.35",
    "praxis-b.de": "93.184.216.36",
    "www.praxis-b.de": "93.184.216.36",
    "intern-rebind.example": "10.0.0.7",
    "localhost": "127.0.0.1",
}


def fake_getaddrinfo(aufrufe):
    """getaddrinfo-Ersatz: kennt nur FAKE_DNS, IP-Adressen gelten als sie selbst."""
    import ipaddress

    def _aufloesen(host, port, *args, **kwargs):
        aufrufe.append(host)
        try:
            ipaddress.ip_address(host)
            ip = host
        except ValueError:
            if host not in FAKE_DNS:
                raise socket.gaierror("unbekannter Host") from None
            ip = FAKE_DNS[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return _aufloesen
