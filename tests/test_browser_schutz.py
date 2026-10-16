"""Tests für browser_schutz.py: nur öffentliche Adressen besuchen (SSRF-Schutz).

DNS ist durch eine Attrappe ersetzt (fake_dns), es geht nichts ins Netz.
"""
import asyncio
import socket

import browser_schutz as schutz
import pytest
from attrappen import FakeRequest, FakeRoute


def _ergebnis(handler, url):
    route = FakeRoute(url)
    asyncio.run(handler(route))
    return route.aktion


# ---------- ist_oeffentliche_http_url ----------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.178.1/admin",
    "http://169.254.169.254/latest/meta-data/",   # Cloud-Metadaten
    "http://[::1]/",
    "http://intern-rebind.example/",              # öffentlicher Name, interne IP
    "http://localhost:8080/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "http://gibt-es-nicht.invalid/",
    "http://[::1",                                # kaputte Adresse: kein Absturz
])
def test_nicht_oeffentliche_adressen_werden_abgelehnt(fake_dns, url):
    assert schutz.ist_oeffentliche_http_url(url) is False


@pytest.mark.parametrize("url", ["https://praxis-beispiel.de/", "http://93.184.216.34/impressum"])
def test_oeffentliche_adressen_sind_erlaubt(fake_dns, url):
    assert schutz.ist_oeffentliche_http_url(url) is True


@pytest.mark.parametrize("url", [
    "http://localhost/",          # Name "localhost" immer verboten
    "http://drucker.local/",      # Namen im Heimnetz
    "ftp://praxis-beispiel.de/",  # nur http(s)
    "http:///nur-ein-pfad",       # kein Hostname
])
def test_jede_regel_greift_auch_wenn_der_name_oeffentlich_aufloest(monkeypatch, url):
    """Der Name löst hier bewusst auf eine ÖFFENTLICHE Adresse auf, damit nur
    die jeweilige Regel greifen kann. Sonst würde die IP-Prüfung eine Lücke
    in der Namens- oder Protokollprüfung verdecken."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    assert schutz.ist_oeffentliche_http_url(url) is False


def test_name_mit_mehreren_adressen_wird_abgelehnt_wenn_eine_intern_ist(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))])
    assert schutz.ist_oeffentliche_http_url("https://gemischt.example/") is False


# ---------- nach_navigation_erlaubt ----------

class _Seite:
    def __init__(self, url):
        self.url = url


def test_nach_navigation_prueft_die_tatsaechlich_erreichte_adresse(fake_dns):
    assert schutz.nach_navigation_erlaubt(_Seite("https://praxis-beispiel.de/kontakt")) is True
    assert schutz.nach_navigation_erlaubt(_Seite("http://127.0.0.1:8080/")) is False
    assert schutz.nach_navigation_erlaubt(_Seite("")) is False


# ---------- ssrf_route_handler: jede Anfrage im Browser ----------

def test_handler_laesst_nur_oeffentliche_anfragen_durch(fake_dns):
    """Playwright ruft den Handler für jede Anfrage auf, also auch für das
    Ziel einer Weiterleitung und für jedes Bild oder Skript der Seite."""
    handler = schutz.ssrf_route_handler()
    folge = [
        ("https://praxis-beispiel.de/", "continue"),
        ("http://127.0.0.1:8080/", "abort"),
        ("https://cdn.praxis-beispiel.de/app.js", "continue"),
        ("http://10.0.0.5/tracking.gif", "abort"),
    ]
    for url, erwartet in folge:
        assert _ergebnis(handler, url) == erwartet, url


def test_handler_fragt_dns_pro_host_nur_einmal(fake_dns):
    handler = schutz.ssrf_route_handler()
    for pfad in ("a.png", "b.png", "c.js"):
        assert _ergebnis(handler, f"https://praxis-beispiel.de/{pfad}") == "continue"
    assert fake_dns.count("praxis-beispiel.de") == 1


def test_handler_nutzt_den_mitgegebenen_request(fake_dns):
    """Playwright übergibt je nach Signatur (route) oder (route, request)."""
    route = FakeRoute("https://praxis-beispiel.de/")
    asyncio.run(schutz.ssrf_route_handler()(route, FakeRequest("http://127.0.0.1/")))
    assert route.aktion == "abort"


def test_handler_uebersteht_eine_geschlossene_seite(fake_dns):
    class _Kaputt(FakeRoute):
        async def continue_(self):
            raise RuntimeError("Target page, context or browser has been closed")
    route = _Kaputt("https://praxis-beispiel.de/")
    asyncio.run(schutz.ssrf_route_handler()(route))
    assert route.aktion is None   # nicht weitergeleitet, aber auch nicht abgestürzt


def test_schutz_einrichten_haengt_den_handler_fuer_alle_anfragen_ein():
    eingehaengt = []

    class _Kontext:
        async def route(self, muster, handler):
            eingehaengt.append((muster, handler))

    asyncio.run(schutz.ssrf_schutz_einrichten(_Kontext()))
    [(muster, handler)] = eingehaengt
    assert muster == "**/*"
    route = FakeRoute("http://127.0.0.1/")
    asyncio.run(handler(route))
    assert route.aktion == "abort"   # es ist wirklich der Prüf-Handler
