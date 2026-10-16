"""Schutz beim Besuch fremder Praxis-Websites (SSRF-Schutz).

Die Website-Adressen stammen aus fremden Profiltexten. Ein präparierter
Text könnte eine interne Adresse wie http://127.0.0.1 oder das Heimnetz
enthalten, und der Browser des Scrapers würde dann Dinge im eigenen Netz
aufrufen. Deshalb gilt für jede Anfrage: nur echte, öffentliche
http(s)-Adressen.

Zwei Schutzschichten:
1. `ssrf_schutz_einrichten()` prüft im Browser JEDE Anfrage, bevor sie
   rausgeht, auch Weiterleitungen, Bilder und Skripte.
2. `nach_navigation_erlaubt()` prüft danach noch einmal, wo der Browser
   wirklich gelandet ist.

Grenze: Eine Adresse, die bei der Prüfung öffentlich und beim Verbinden
plötzlich intern auflöst (DNS-Rebinding), lässt sich so nicht ganz
ausschließen. Dafür gibt es die zweite Schicht.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


def ist_oeffentliche_http_url(url):
    """True nur für http(s)-Adressen, deren Name auf ausschließlich
    öffentliche IP-Adressen auflöst. Alles andere, auch jeder Fehler, ist
    False."""
    try:
        teile = urlparse(url)
        if teile.scheme not in ("http", "https") or not teile.hostname:
            return False
        host = teile.hostname
        if host == "localhost" or host.endswith(".local"):
            return False
        try:
            adressen = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for adresse in adressen:
            ip = ipaddress.ip_address(adresse[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def nach_navigation_erlaubt(page):
    """Prüft die Adresse, auf der die Seite nach einem goto() tatsächlich
    gelandet ist (Weiterleitungen eingeschlossen)."""
    adresse = getattr(page, "url", "") or ""
    if not ist_oeffentliche_http_url(adresse):
        print(f"    -> Weiterleitung auf nicht-öffentliche Adresse blockiert: {adresse}")
        return False
    return True


def ssrf_route_handler():
    """Playwright-Handler, der jede Anfrage vor dem Absenden prüft:
    erlaubt -> weiter, sonst abbrechen. Das Ergebnis wird pro (Schema, Host)
    gemerkt, damit nicht jedes Bild eine eigene DNS-Abfrage auslöst."""
    gemerkt = {}

    async def handler(route, request=None):
        url = getattr(request or route.request, "url", "") or ""
        try:
            teile = urlparse(url)
            schluessel = (teile.scheme, teile.hostname)
        except Exception:
            schluessel = None
        if schluessel is not None and schluessel in gemerkt:
            erlaubt = gemerkt[schluessel]
        else:
            erlaubt = await asyncio.to_thread(ist_oeffentliche_http_url, url)
            if schluessel is not None:
                gemerkt[schluessel] = erlaubt
        try:
            if erlaubt:
                await route.continue_()
            else:
                print(f"    -> Anfrage an nicht-öffentliche Adresse blockiert: {url[:120]}")
                await route.abort("blockedbyclient")
        except Exception as fehler:
            # Seite schon geschlossen o. ä.: darf den Lauf nicht abbrechen.
            print(f"    -> Route-Handler: {fehler}")

    return handler


async def ssrf_schutz_einrichten(context_oder_page):
    """Hängt den Prüf-Handler für ALLE Anfragen ein. Muss vor der ersten
    Navigation zu einer Praxis-Website passieren. Auf einem Browser-Kontext
    gilt der Schutz auch für Popups und neue Tabs."""
    await context_oder_page.route("**/*", ssrf_route_handler())
