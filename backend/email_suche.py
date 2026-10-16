"""Fehlende E-Mail-Adressen ergänzen (`python main.py --only-emails`).

Zwei Stufen:
1. Im schon gespeicherten Profiltext nach E-Mail und Website suchen.
2. Praxis-Websites besuchen (Startseite plus bis zu drei Kontakt- oder
   Impressum-Seiten) und dort suchen. Jede Anfrage läuft durch den
   SSRF-Schutz aus browser_schutz.py.

Viele Treffer auf Websites sind keine echten Kontaktadressen (Tracking-
Dienste, Platzhalter, Bilddateien wie "logo@2x.png"). `saubere_email()`
sortiert sie aus. Die Sperrlisten sind aus echten Fehltreffern entstanden.
"""
import asyncio
import random
import re
from urllib.parse import unquote

import pfade
from browser_schutz import ist_oeffentliche_http_url, nach_navigation_erlaubt, ssrf_schutz_einrichten
from dateihilfen import json_atomar_schreiben, json_sicher_laden
from merge_hilfen import ist_praxis_website
from playwright.async_api import async_playwright

EMAIL_MUSTER = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
WEBSITE_MUSTER = re.compile(r'(https?://[^\s\)\]"\'<>]+|www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s\)\]"\'<>]*)')
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MAX_UNTERSEITEN = 3
SPEICHERN_ALLE = 5

# Domains, die nie die Kontaktadresse einer Einzelpraxis sind: Tracking und
# Baukästen, Platzhalter, große Plattformen sowie Seiten, die früher als
# Fehltreffer auftauchten (Namensbedeutungen, Magazine, Spiele).
_GESPERRTE_DOMAINS = re.compile(
    r"@([\w\-]+\.)*(sentry\.io|ingest\.sentry\.io|wixpress\.com|mailchimp\.com|"
    r"googletagmanager\.com|example\.(com|org|net)|beispiel\.(de|com)|domain\.com|"
    r"website\.com|mustermann\.\w+|test\.\w+|"
    r"schemas?\.\w+|microsoft\.com|apple\.com|amazon\.(de|com|co\.uk)|"
    r"yahoo\.(com|de)|outlook\.com|live\.com|msn\.com|tiktok\.com|"
    r"pinterest\.(com|de)|reddit\.com|github\.com|bing\.com|google\.(com|de)|"
    r"facebook\.com|instagram\.com|linkedin\.com|xing\.com|twitter\.com|x\.com|"
    r"youtube\.com|wikipedia\.org|baby-vornamen\.de|gala\.de|tvmovie\.de|"
    r"crazygames\.com|mamenza\.com)$",
    re.IGNORECASE)
# Platzhalter vor dem @ ("noreply@", "ihre-mail@").
_GESPERRTE_NAMEN = re.compile(r"^(noreply|no-reply|benutzer|user|name|ihre?-?mail)@", re.IGNORECASE)
# Dateinamen wie "logo@2x.png" sehen aus wie eine Adresse.
_DATEIENDUNGEN = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|bmp|tiff?|css|js|json|pdf|docx?|xlsx?)$",
                            re.IGNORECASE)


def saubere_email(roh):
    """Gibt die bereinigte Adresse zurück oder None, wenn sie keine echte
    Kontaktadresse ist."""
    email = unquote(roh).strip().rstrip(".,;)")
    if not EMAIL_MUSTER.fullmatch(email):
        return None
    if _GESPERRTE_DOMAINS.search(email) or _GESPERRTE_NAMEN.search(email) or _DATEIENDUNGEN.search(email):
        return None
    return email


def email_und_website_aus_text(text):
    """Erste brauchbare E-Mail und erste echte Praxis-Website im Text.
    Links zu therapie.de oder Kartendiensten zählen nicht als Website."""
    email = next((e for e in (saubere_email(m.group(0)) for m in EMAIL_MUSTER.finditer(text)) if e), None)
    website = None
    for treffer in WEBSITE_MUSTER.finditer(text):
        kandidat = treffer.group(0)
        if not kandidat.startswith("http"):
            kandidat = "https://" + kandidat
        if ist_praxis_website(kandidat):
            website = kandidat
            break
    return email, website


def ergaenze_aus_text(profile):
    """Stufe 1 (ohne Netz): ungültige Adressen leeren, dann fehlende E-Mail
    und Website aus dem Profiltext übernehmen. Vorhandene Werte bleiben.
    Ändert die Profile direkt und gibt (bereinigt, aus_text) zurück."""
    bereinigt = aus_text = 0
    for p in profile:
        if p.get("email") and not saubere_email(p["email"]):
            p["email"] = ""
            bereinigt += 1
        email, website = email_und_website_aus_text(f"{p.get('volltext', '')} {p.get('persoenliches_profil', '')}")
        if not p.get("email") and email:
            p["email"] = email
            aus_text += 1
        if not p.get("website") and website:
            p["website"] = website
    return bereinigt, aus_text


def braucht_websuche(profile):
    """Profile ohne E-Mail, aber mit Website: nur die lohnen Stufe 2."""
    return [p for p in profile if not p.get("email") and p.get("website")]


async def email_auf_seite(page):
    """Erst mailto-Links, dann der Seitentext."""
    links = await page.evaluate(
        "() => [...document.querySelectorAll('a[href^=\"mailto:\"]')].map(a => a.getAttribute('href'))")
    for link in links:
        email = saubere_email(link.replace("mailto:", "").split("?")[0])
        if email:
            return email
    for treffer in EMAIL_MUSTER.finditer(await page.content()):
        email = saubere_email(treffer.group(0))
        if email:
            return email
    return None


async def _oeffnen(page, url, timeout):
    """goto() mit SSRF-Prüfung davor und danach. True, wenn die Seite
    gelesen werden darf."""
    if not ist_oeffentliche_http_url(url):
        return False
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception:
        return False
    return nach_navigation_erlaubt(page)


async def email_auf_website(page, website, pause=asyncio.sleep):
    """Sucht auf der Startseite und bis zu drei Kontakt-/Impressum-Seiten.
    Der Aufrufer muss vorher ssrf_schutz_einrichten() ausgeführt haben."""
    if not await _oeffnen(page, website, timeout=20000):
        return None
    email = await email_auf_seite(page)
    if email:
        return email
    unterseiten = await page.evaluate(f"""() => {{
        const woerter = ['kontakt', 'contact', 'impressum'];
        return [...document.querySelectorAll('a[href]')]
            .map(a => ({{ href: a.href, text: (a.innerText + a.href).toLowerCase() }}))
            .filter(a => woerter.some(w => a.text.includes(w)) && a.href.startsWith('http'))
            .map(a => a.href)
            .slice(0, {MAX_UNTERSEITEN});
    }}""")
    for url in unterseiten:
        if not ist_oeffentliche_http_url(url):
            continue
        await pause(random.uniform(1.0, 2.0))
        if await _oeffnen(page, url, timeout=15000):
            email = await email_auf_seite(page)
            if email:
                return email
    return None


async def ergaenze_von_websites(profile, alle, datei, pause=asyncio.sleep):
    """Stufe 2: besucht die Websites der `profile` und speichert alle
    SPEICHERN_ALLE Websites sowie am Ende (auch bei Abbruch) `alle` in
    `datei`. Gibt die Zahl der gefundenen Adressen zurück."""
    gefunden = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            kontext = await browser.new_context(user_agent=USER_AGENT)
            await ssrf_schutz_einrichten(kontext)   # vor der ersten Navigation
            page = await kontext.new_page()
            for i, profil in enumerate(profile, 1):
                print(f"  [{i}/{len(profile)}] {profil.get('name', '?')} -> {profil.get('website')}")
                email = await email_auf_website(page, profil.get("website"), pause=pause)
                if email:
                    profil["email"] = email
                    gefunden += 1
                    print(f"    -> {email}")
                await pause(2 + random.uniform(0, 1.5))
                if i % SPEICHERN_ALLE == 0:
                    json_atomar_schreiben(datei, alle)
        finally:
            json_atomar_schreiben(datei, alle)
            try:
                await browser.close()
            except Exception as fehler:
                print(f"  Browser konnte nicht sauber geschlossen werden: {fehler}")
    return gefunden


async def ergaenze_emails(datei=pfade.RESULTS_RAW, pause=asyncio.sleep):
    """Beide Stufen für die Rohdaten-Datei."""
    profile = json_sicher_laden(datei, None)
    if profile is None:
        print(f"Fehler: {datei} nicht gefunden. Bitte zuerst den Scraper ausführen.")
        return
    bereinigt, aus_text = ergaenze_aus_text(profile)
    print(f"  {len(profile)} Profile, {bereinigt} ungültige Adressen geleert, "
          f"Stufe 1: {aus_text} aus dem Profiltext.")
    offen = braucht_websuche(profile)
    print(f"  Stufe 2: {len(offen)} Praxis-Websites zu besuchen.")
    if offen:
        gefunden = await ergaenze_von_websites(offen, profile, datei, pause=pause)
        print(f"  Stufe 2: {gefunden} weitere Adressen gefunden.")
    json_atomar_schreiben(datei, profile)
    print(f"\n  Gesamt: {sum(1 for p in profile if p.get('email'))} von {len(profile)} Profilen haben eine E-Mail.")
