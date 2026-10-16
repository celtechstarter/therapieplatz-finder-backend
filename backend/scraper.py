"""
Scraper v2 – ganz Dortmund, höflich und robust.

Verbesserungen gegenüber v1:
- SANFTES TEMPO: 4-6,5 Sekunden Pause zwischen Seitenaufrufen (zufällig).
- BAN-SCHUTZ: Bei HTTP 403/429 oder Captcha-Anzeichen stoppt der Lauf sofort
  und speichert den Fortschritt, statt weiterzumachen.
- FORTSCHRITT: Ergebnisse werden laufend gespeichert. Ein Neustart überspringt
  bereits gescrapte Profile automatisch (Resume).
- BUGFIX: Die Email-Suche auf externen Websites passiert NICHT mehr mitten in
  der Profil-Extraktion (das hat vorher Felder von der falschen Seite gelesen),
  sondern nur noch in der separaten Phase `enrich_emails`.
- GANZ DORTMUND: Standardsuche ist jetzt die Stadt Dortmund, nicht nur 44319.

Aufruf (aus dem backend/-Ordner, oder als "python -m backend.scraper" vom
Projekt-Root aus):
  python scraper.py            -> Dortmund komplett scrapen (mit Resume)
  python scraper.py --neu      -> alles neu scrapen (Resume ignorieren)
"""
import asyncio
import json
import re
import random
import sys
from datetime import datetime
from urllib.parse import quote, unquote, urlparse

from playwright.async_api import async_playwright

import pfade
from dateihilfen import json_atomar_schreiben, json_sicher_laden
from merge_hilfen import ist_praxis_website as _ist_praxis_website

BASE_URL = "https://www.therapie.de"
SUCHORTE = ["Dortmund", "Unna", "Bönen"]  # Stadtsuche deckt alle Dortmunder PLZ ab.
# Unna/Bönen ergaenzt (26.8.2026, Feedback des PTV Dortmund: deren
# Einzugsgebiet reicht bis Unna/Boenen). therapie.de sucht pro Ort in einem
# 10km-Radius (gegengeprueft: ort=Boenen liefert 16 Treffer, u.a. eine Praxis
# direkt in Boenen sowie mehrere in Unna/Hamm) - Ueberschneidungen mit den
# Dortmunder Treffern werden beim Mergen in results_raw.json ueber
# profil_url dedupliziert, wie bei den anderen Quellen auch.
OUTPUT_FILE = str(pfade.RESULTS_RAW)
# Keine Screenshots der Profilseiten mehr (entfernt 16.10.2026): sie
# speicherten Fotos und Kontaktdaten jeder Praxis, auch ohne Aufnahmestopp.
# Als Nachweis fuer die Kasse zaehlen die eigenen Absagen in "Meine Mappe".

# Formulierungen, die einen Aufnahmestopp anzeigen (wichtig als Nachweis
# für das Kostenerstattungsverfahren bei der Krankenkasse)
AUFNAHMESTOPP_MUSTER = [
    "keine neuen patienten",
    "keine neuen patient:innen",
    "keine neuen patientinnen",
    "aufnahmestopp",
    "keine aufnahme neuer",
    "nehme derzeit keine",
    "nehmen derzeit keine",
    "nehme zur zeit keine",
    "nehmen zur zeit keine",
    "nehme aktuell keine",
    "nehmen aktuell keine",
    "keine kapazitäten für neue",
    "keine freien therapieplätze",
]

# Höfliches Tempo (Sekunden zwischen Seitenaufrufen)
DELAY_MIN = 4.0
DELAY_MAX = 6.5

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class BanVerdacht(Exception):
    """Wird geworfen, wenn die Seite uns blockiert. Sofort aufhören!"""


async def _pause():
    await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


async def _goto(page, url, timeout=30000):
    """Seite laden und auf Ban-Anzeichen prüfen."""
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if resp is not None and resp.status in (403, 429):
        raise BanVerdacht(f"HTTP {resp.status} bei {url}")
    inhalt = (await page.content())[:5000].lower()
    if "ich bin kein roboter" in inhalt or "unusual traffic" in inhalt \
            or "access denied" in inhalt:
        raise BanVerdacht(f"Captcha/Block-Seite erkannt bei {url}")
    return resp


def _lade_ergebnisse():
    """Laedt den bisherigen Stand fuer den Resume-Modus. Nutzt bewusst
    json_sicher_laden(): eine abgeschnittene results_raw.json (Absturz mitten
    im Schreiben) darf den Scraper nicht mit JSONDecodeError abbrechen,
    sondern soll wie ein leerer Stand behandelt werden."""
    return json_sicher_laden(OUTPUT_FILE, [])


def _bekannte_urls(results):
    """Menge der bereits gescrapten Profil-URLs (Grundlage fuer Resume).

    .get() statt results[i]["profil_url"]: ein einzelner Datensatz ohne
    dieses Feld -- etwa aus einer aelteren oder von Hand bearbeiteten Datei --
    hat vorher den kompletten Lauf mit KeyError abgebrochen, bevor ueberhaupt
    etwas gescrapt wurde."""
    return {r.get("profil_url") for r in results
            if isinstance(r, dict) and r.get("profil_url")}


def _speichere_ergebnisse(results):
    # Atomar schreiben (siehe dateihilfen.py): ein Abbruch mitten im Schreiben
    # der ~1 MB grossen Datei wuerde sonst den kompletten Scraping-Fortschritt
    # in eine unlesbare, halbe Datei verwandeln.
    json_atomar_schreiben(OUTPUT_FILE, results)


# ---------------------------------------------------------------------------
# Suchergebnis-Seiten
# ---------------------------------------------------------------------------

async def get_profile_links(page, url):
    await _goto(page, url)
    try:
        await page.wait_for_selector(".search-results-list", timeout=10000)
    except Exception:
        pass
    links = await page.eval_on_selector_all(
        "a[href*='/profil/']",
        "els => [...new Set(els.map(e => e.href))]"
    )
    return [l for l in links if "/profil/" in l and "/info/" not in l]


async def get_next_page_url(page):
    next_el = await page.query_selector(".resultnav li.next a")
    if next_el:
        href = await next_el.get_attribute("href")
        if href:
            return href if href.startswith("http") else BASE_URL + href
    return None


async def get_all_profile_urls(page):
    """Sammelt Profil-URLs für alle Suchorte, über alle Ergebnisseiten."""
    alle = []
    for ort in SUCHORTE:
        start = f"{BASE_URL}/therapeutensuche/ergebnisse/?ort={quote(ort)}"
        current = start
        visited = set()
        while current and current not in visited:
            visited.add(current)
            print(f"  Suchseite: {current}")
            links = await get_profile_links(page, current)
            print(f"    -> {len(links)} Profile")
            alle.extend(links)
            next_url = await get_next_page_url(page)
            if not next_url or next_url in visited:
                break
            current = next_url
            await _pause()
    return list(dict.fromkeys(alle))


# ---------------------------------------------------------------------------
# Einzelnes Profil
# ---------------------------------------------------------------------------

async def find_section_items(page, section_title):
    return await page.evaluate("""(title) => {
        const h4s = [...document.querySelectorAll('.therapist-details h4')];
        const target = h4s.find(h => h.innerText.includes(title));
        if (!target) return [];
        const ul = target.nextElementSibling;
        if (!ul) return [];
        return [...ul.querySelectorAll('li')].map(li => li.innerText.trim()).filter(Boolean);
    }""", section_title)


_FREIE_PLAETZE_KOPF = re.compile(r"Freie Pl(?:ä|ae)tze\s*/\s*Wartezeiten\s*\n+\s*([^\n]+)", re.I)


def freie_plaetze_aus_text(profil_text):
    """Liest den Abschnitt "Freie Plaetze / Wartezeiten" aus.

    Vorher wurde nur nach Stichworten im ganzen Text gesucht -- dabei traf
    "freie plätze" schon die Abschnitts-Ueberschrift selbst, sodass fast
    jedes Profil als "freie Plätze" galt, auch mit "Wartezeit über zwölf
    Monate" (Befund 30.9.2026). Jetzt zaehlt nur die Zeile unter der
    Ueberschrift: "freie Plätze" bei "Freie Plätze vorhanden", sonst der
    Wortlaut ohne Schlusspunkt (z.B. "Wartezeit über drei Monate").
    Fehlt der Abschnitt: leerer String."""
    m = _FREIE_PLAETZE_KOPF.search(profil_text or "")
    if not m:
        return ""
    zeile = m.group(1).strip().rstrip(".").strip()
    if re.match(r"freie pl(?:ä|ae)tze vorhanden", zeile, re.I):
        return "freie Plätze"
    return zeile[:120]


def _finde_aufnahmestopp(profil_text):
    """Sucht Aufnahmestopp-Formulierungen und gibt (gefunden, zitat) zurück.
    Sucht direkt (case-insensitive) im Originaltext statt über eine
    .lower()-Kopie mit übernommenen Indizes: .lower() ist nicht
    längenerhaltend (z.B. 'İ' -> 'i̇', 2 statt 1 Zeichen), wodurch Positionen
    vor dem Treffer verschieben und das als Nachweis gedachte Zitat
    verfälscht ausgeschnitten würde."""
    for muster in AUFNAHMESTOPP_MUSTER:
        m = re.search(re.escape(muster), profil_text, re.IGNORECASE)
        if not m:
            continue
        pos = m.start()
        # Den umgebenden Satz als Zitat ausschneiden
        start = max(profil_text.rfind(".", 0, pos), profil_text.rfind("\n", 0, pos)) + 1
        ende_punkt = profil_text.find(".", pos)
        ende_zeile = profil_text.find("\n", pos)
        kandidaten = [e for e in (ende_punkt, ende_zeile) if e >= 0]
        ende = min(kandidaten) + 1 if kandidaten else min(pos + 200, len(profil_text))
        zitat = profil_text[start:ende].strip()
        return True, zitat[:400]
    return False, ""


async def extract_profile(page, url):
    """Scrapt ein einzelnes Profil. Navigiert NICHT auf fremde Seiten."""
    try:
        await _goto(page, url)
        await page.wait_for_selector(".therapist-details", timeout=10000)
    except BanVerdacht:
        raise
    except Exception as e:
        print(f"  Ladefehler: {e}")
        return None
    return await lies_profil(page, url)


async def lies_profil(page, url):
    """Liest die Profilfelder aus der Seite, die GERADE in `page` geladen ist
    (keine Navigation). Getrennt von extract_profile(), damit
    umkreis_ausbau.py dieselbe Auslese-Logik nutzen kann, wenn das HTML ueber
    Firecrawl kommt und per page.set_content() geladen wird -- so gibt es nur
    EINE Stelle, an der die Felder aus einem therapie.de-Profil gelesen
    werden."""
    data = {"profil_url": url, "scraped_at": datetime.now().isoformat(timespec="seconds")}

    async def text(selector, default=""):
        try:
            el = await page.query_selector(selector)
            return (await el.inner_text()).strip() if el else default
        except Exception:
            return default

    data["name"] = await text("h1")

    strasse = await text("[itemprop='streetAddress']")
    stadt = await text("[itemprop='addressLocality']")
    plz = await text("[itemprop='postalCode']")
    if strasse:
        data["adresse"] = f"{strasse}, {plz} {stadt}".strip(", ")
    else:
        # Fallback, wenn therapie.de die Adresse ausnahmsweise NICHT als
        # schema.org-Mikrodaten (itemprop) auszeichnet. Der erste
        # .therapist-details-Block ist die Kontaktkarte oben rechts und
        # beginnt dort immer mit denselben zwei Kopfzeilen:
        #   lines[0] = Name der Praxis/Person, lines[1] = Berufsbezeichnung.
        # Erst danach folgen Strasse, PLZ+Ort und ggf. Adresszusatz --
        # deshalb lines[2:5] (die drei Zeilen nach dem Kopf). Mehr als drei
        # Adresszeilen gibt es auf der Seite nicht; alles danach waeren
        # bereits Telefon/Email, die hier nicht in die Adresse gehoeren.
        block1 = await text(".therapist-details")
        lines = [l.strip() for l in block1.splitlines() if l.strip()]
        data["adresse"] = " | ".join(lines[2:5]) if len(lines) > 2 else ""
    data["plz"] = plz

    data["telefon"] = await text("[itemprop='telephone']")

    email_el = await page.query_selector("a[href^='mailto:']")
    if email_el:
        href = await email_el.get_attribute("href")
        data["email"] = href.replace("mailto:", "").split("?")[0].strip() if href else ""
    else:
        data["email"] = ""

    data["website"] = ""
    for kandidat in await page.query_selector_all(
            ".therapist-details a[href^='http']:not([href*='therapie.de'])"):
        href = await kandidat.get_attribute("href")
        if href and _ist_praxis_website(href):
            data["website"] = href
            break

    abrechnung_raw = await text("#abrechnungsverfahren")
    data["abrechnungsarten"] = [a.strip() for a in abrechnung_raw.split(",") if a.strip()]

    data["behandlungsschwerpunkte"] = await find_section_items(page, "Behandlungs-Schwerpunkte")
    data["therapieverfahren"] = await find_section_items(page, "Verfahren")
    data["therapieangebot"] = await find_section_items(page, "Therapie-Angebot")

    profil_text = ""
    try:
        blocks = await page.query_selector_all(".therapist-details")
        for b in blocks:
            profil_text += await b.inner_text() + "\n"
    except Exception:
        pass

    data["freie_plaetze"] = freie_plaetze_aus_text(profil_text)

    # Aufnahmestopp erkennen und Original-Satz als Beweis-Zitat speichern
    stopp, zitat = _finde_aufnahmestopp(profil_text)
    data["aufnahmestopp"] = stopp
    data["aufnahmestopp_zitat"] = zitat

    # Freitext "Persoenliches Profil": therapie.de rendert pro Profilseite
    # mehrere .therapist-details-Bloecke in fester Reihenfolge:
    #   [0] Kontaktkarte (Name/Adresse/Telefon)
    #   [1] Fachangaben (Abrechnung, Verfahren, Schwerpunkte, Angebot)
    #   [2..] optionale Freitextbloecke, zuletzt das persoenliche Profil.
    # Weniger als drei Bloecke heisst deshalb: die Praxis hat gar keinen
    # Freitext gepflegt -> leerer String statt versehentlich die Fachangaben
    # als "persoenliches Profil" zu uebernehmen. Der letzte Block ist der
    # Freitext; darin ist das <p> der eigentliche Text (ohne Ueberschrift),
    # sonst als Notloesung die ersten 1000 Zeichen des Blocks.
    data["persoenliches_profil"] = await page.evaluate("""() => {
        const blocks = [...document.querySelectorAll('.therapist-details')];
        if (blocks.length < 3) return '';
        const last = blocks[blocks.length - 1];
        const p = last.querySelector('p');
        return p ? p.innerText.trim() : last.innerText.trim().substring(0, 1000);
    }""")

    # Kompletten Text speichern (keine Kürzung mehr) – damit können später
    # neue Funktionen aus den vorhandenen Daten gebaut werden, ohne neu zu scrapen
    data["volltext"] = profil_text
    return data


# ---------------------------------------------------------------------------
# Hauptlauf mit Resume
# ---------------------------------------------------------------------------

async def main(neu=False):
    print("=== Scraper v2 (Dortmund komplett, sanftes Tempo) ===")
    print(f"Tempo: {DELAY_MIN}-{DELAY_MAX}s Pause pro Seite. Das dauert bewusst.\n")

    results = [] if neu else _lade_ergebnisse()
    bekannt = _bekannte_urls(results)
    if bekannt:
        print(f"Resume: {len(bekannt)} Profile bereits vorhanden, werden übersprungen.\n")

    gebannt = False
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=USER_AGENT, locale="de-DE")
            page = await context.new_page()

            print("Sammle Profil-Links...")
            urls = await get_all_profile_urls(page)
            neu_zu_holen = [u for u in urls if u not in bekannt]
            print(f"\nGesamt gefunden: {len(urls)} | Neu zu scrapen: {len(neu_zu_holen)}")
            geschaetzt = len(neu_zu_holen) * (DELAY_MIN + DELAY_MAX) / 2 / 60
            print(f"Geschätzte Dauer: ca. {geschaetzt:.0f} Minuten\n")

            for i, url in enumerate(neu_zu_holen, 1):
                print(f"[{i}/{len(neu_zu_holen)}] {url}")
                await _pause()
                profile = await extract_profile(page, url)
                if profile:
                    results.append(profile)
                    hinweis = "  [AUFNAHMESTOPP]" if profile.get("aufnahmestopp") else ""
                    print(f"  -> {profile.get('name', '?')}{hinweis}")
                else:
                    print("  -> Übersprungen (Ladefehler)")
                if i % 5 == 0 or i == len(neu_zu_holen):
                    _speichere_ergebnisse(results)

        except BanVerdacht as e:
            gebannt = True
            print("\n" + "=" * 60)
            print("STOPP: Die Seite blockiert uns gerade.")
            print(f"Grund: {e}")
            print(f"Fortschritt gespeichert ({len(results)} Profile).")
            print("Bitte ein paar Stunden warten und dann einfach neu starten –")
            print("der Lauf macht automatisch da weiter, wo er aufgehört hat.")
            print("=" * 60)
        finally:
            # Speichern und Browser-Schliessen gehoeren in ein finally:
            # vorher lief beides NUR bei sauberem Ende oder bei BanVerdacht.
            # Ein Playwright-Timeout, ein Tippfehler in einem Selektor oder
            # Ctrl+C mitten im Lauf hat dadurch den kompletten seit dem
            # letzten Zwischenspeichern gescrapten Fortschritt verworfen und
            # den Chromium-Prozess als Zombie zurueckgelassen.
            _speichere_ergebnisse(results)
            try:
                await browser.close()
            except Exception as e:
                print(f"  Browser konnte nicht sauber geschlossen werden: {e}")

    if gebannt:
        return results

    print(f"\nFertig! {len(results)} Profile in {OUTPUT_FILE}")
    return results


# ---------------------------------------------------------------------------
# Email-Anreicherung (separate Phase, NACH dem Scrapen)
# ---------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Domain-Teil muss GENAU auf eines dieser Muster enden (Subdomain-sicher),
# damit z.B. "...@sentry-next.wixpress.com" (echter Fund in den Live-Daten)
# nicht durchrutscht, weil "wixpress.com" nicht direkt hinter "@" steht.
# Grosse Plattform-/Konzern-Domains sind hier zusaetzlich gelistet: eine
# Dortmunder Einzelpraxis hat NIE eine @microsoft.com- oder @amazon.de-Adresse
# als Kontakt. Bugfix (12.8.2026): ein Treffer der (inzwischen entfernten) Bing-Suche fuer den Namen einer
# Dortmunder Therapeutin landete faelschlich auf einer Microsoft-Supportseite,
# von der find_email_on_page() "kunden@microsoft.com" extrahierte -- ohne diese
# Sperre waere das ungeprueft als Kontakt-Email der Therapeutin gespeichert
# worden (und haette am Ende eine Anfrage mit Gesundheitsangaben an die
# falsche Adresse geschickt). Siehe auch _DIRECTORY_DOMAINS weiter unten,
# die verhindert, dass solche Seiten ueberhaupt erst besucht werden.
#
# Bugfix (26.8.2026, Marcel gemeldet): drei Live-Eintraege hatten ganz
# offensichtlich falsche Emails (baby-vornamen.de, website.com, ein
# sentry-next.wixpress.com-Tracking-String). Ursache war nicht diese
# Blacklist selbst -- wixpress.com stand schon drin --, sondern dass die
# betroffenen Datensaetze VOR der jeweiligen Blacklist-Ergaenzung gescraped
# wurden und nie erneut gegen die aktuelle Liste geprueft wurden (siehe
# results_analyzed.json, dort direkt bereinigt). Domains hier ergaenzt,
# damit kuenftige Scraper-/Nachrecherche-Laeufe dieselben Treffer nicht
# erneut aufnehmen: baby-vornamen.de (Vornamen-Bedeutungsseite, tauchte bei
# 11 verschiedenen Therapeuten mit unterschiedlichen Vornamen als "Email"
# auf), beispiel.de/beispiel.com (deutsches Pendant zu example.com), gala.de
# und tvmovie.de (Boulevard-/TV-Magazine), crazygames.com (Gaming-Seite),
# mamenza.com (Drittanbieter-Widget), website.com (Platzhalter-Domain wie
# domain.com).
_EMAIL_DOMAIN_BLACKLIST = re.compile(
    r"@([\w\-]+\.)*(sentry\.io|ingest\.sentry\.io|wixpress\.com|mailchimp\.com|"
    r"googletagmanager\.com|example\.(com|org|net)|beispiel\.(de|com)|domain\.com|"
    r"website\.com|mustermann\.\w+|test\.\w+|"
    r"schemas?\.\w+|microsoft\.com|apple\.com|amazon\.(de|com|co\.uk)|"
    r"yahoo\.(com|de)|outlook\.com|live\.com|msn\.com|tiktok\.com|"
    r"pinterest\.(com|de)|reddit\.com|github\.com|bing\.com|google\.(com|de)|"
    r"facebook\.com|instagram\.com|linkedin\.com|xing\.com|twitter\.com|x\.com|"
    r"youtube\.com|wikipedia\.org|baby-vornamen\.de|gala\.de|tvmovie\.de|"
    r"crazygames\.com|mamenza\.com)$",
    re.IGNORECASE,
)
_EMAIL_LOCALPART_BLACKLIST = re.compile(
    r"^(noreply|no-reply|benutzer|user|name|ihre?-?mail)@", re.IGNORECASE
)

# Bugfix (12.8.2026): Bild-Dateinamen im "@2x"/"@3x"-Retina-Format (z.B.
# "logo@2x.png") erfuellen EMAIL_REGEX vollstaendig (".png" sieht wie eine
# TLD aus) und wurden von find_email_on_page() als echte Email durchgereicht
# -- gefunden als "chosen-sprite@2x.png" bei einem Live-Testlauf. Dateiendung
# statt echter TLD am Ende der Domain wird deshalb explizit abgelehnt.
_EMAIL_DATEIENDUNG_BLACKLIST = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|bmp|tiff?|css|js|json|pdf|docx?|xlsx?)$",
    re.IGNORECASE,
)


def _clean_email(raw):
    email = unquote(raw).strip().rstrip(".,;)")
    if not EMAIL_REGEX.fullmatch(email):
        return None
    if _EMAIL_DOMAIN_BLACKLIST.search(email) or _EMAIL_LOCALPART_BLACKLIST.search(email):
        return None
    if _EMAIL_DATEIENDUNG_BLACKLIST.search(email):
        return None
    return email


async def find_email_on_page(page):
    hrefs = await page.evaluate(
        "() => [...document.querySelectorAll('a[href^=\"mailto:\"]')].map(a => a.getAttribute('href'))"
    )
    for href in hrefs:
        email = _clean_email(href.replace("mailto:", "").split("?")[0])
        if email:
            return email
    content = await page.content()
    for match in EMAIL_REGEX.finditer(content):
        email = _clean_email(match.group(0))
        if email:
            return email
    return None


def _ist_oeffentliche_http_url(url):
    """SSRF-Schutz: 'website'-Werte kommen aus gescraptem Fremdtext (Regex
    ueber Profilseiten). Ein praeparierter Profiltext koennte eine
    localhost-/private-IP-URL enthalten und den Scraper damit z.B. gegen den
    eigenen lokalen Server (main.py) navigieren lassen. Nur echte,
    aufloesbare, oeffentliche http(s)-Hosts erlauben."""
    import ipaddress
    import socket
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname
        if host in ("localhost",) or host.endswith(".local"):
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _nach_navigation_erlaubt(page):
    """Prueft die TATSAECHLICH erreichte Adresse nach einem page.goto().

    Die Pruefung VOR dem Aufruf sichert nur die angefragte URL ab. Ein
    Server kann per HTTP-Redirect (301/302) oder Meta-Refresh auf
    http://127.0.0.1:8080/ bzw. eine interne IP weiterleiten -- der Scraper
    wuerde dann trotz bestandener Vorpruefung Inhalte aus dem lokalen Netz
    einlesen und daraus womoeglich eine "Kontakt-Email" extrahieren (SSRF).
    Deshalb nach jeder Navigation erneut gegen dieselbe Regel pruefen.
    Seit Review #13 nur noch zweite Absicherung: primaer blockt
    ssrf_route_handler() solche Requests schon VOR dem Absenden."""
    aktuelle_url = getattr(page, "url", "") or ""
    if not _ist_oeffentliche_http_url(aktuelle_url):
        print(f"    -> Weiterleitung auf nicht-oeffentliche Adresse blockiert: {aktuelle_url}")
        return False
    return True


def ssrf_route_handler():
    """Baut einen Playwright-Route-Handler, der JEDEN Request des Browsers
    VOR dem Absenden prueft (Review #13).

    Warum: _nach_navigation_erlaubt() prueft erst NACH page.goto() -- da ist
    der Request an eine interne Adresse (z.B. per 302-Weiterleitung auf
    http://127.0.0.1:8080/) schon passiert. Subressourcen einer Praxis-
    Website (Bilder, Skripte, iframes, fetch/XHR) wurden gar nicht geprueft;
    eine praeparierte Seite koennte so ueber den Browser des Scrapers
    Anfragen ins lokale Netz schicken. Playwright ruft den Handler fuer jede
    Anfrage auf, auch fuer die Ziele von HTTP-Weiterleitungen (jeder
    Redirect-Hop ist ein eigener Request).

    Nicht-oeffentliche Ziele -> route.abort("blockedbyclient"), sonst
    route.continue_(). Das Ergebnis wird pro (Schema, Host) zwischen-
    gespeichert, damit nicht jedes Bild eine eigene DNS-Aufloesung ausloest.
    Grenzen: WebSockets laufen nicht ueber page/context.route; DNS-Rebinding
    (Host loest bei der Pruefung oeffentlich, beim Verbindungsaufbau intern
    auf) ist damit nicht vollstaendig ausgeschlossen -- die Nachpruefung per
    _nach_navigation_erlaubt() bleibt deshalb als zweite Absicherung."""
    cache = {}

    async def handler(route, request=None):
        req = request or route.request
        url = getattr(req, "url", "") or ""
        try:
            parsed = urlparse(url)
            schluessel = (parsed.scheme, parsed.hostname)
        except Exception:
            schluessel = None
        if schluessel is not None and schluessel in cache:
            erlaubt = cache[schluessel]
        else:
            erlaubt = await asyncio.to_thread(_ist_oeffentliche_http_url, url)
            if schluessel is not None:
                cache[schluessel] = erlaubt
        try:
            if erlaubt:
                await route.continue_()
            else:
                print(f"    -> Request an nicht-oeffentliche Adresse blockiert: {url[:120]}")
                await route.abort("blockedbyclient")
        except Exception as e:
            # Seite/Kontext schon geschlossen o.ae. -- darf den Lauf nicht abbrechen.
            print(f"    -> Route-Handler: {e}")

    return handler


async def ssrf_schutz_einrichten(context_oder_page):
    """Haengt ssrf_route_handler() fuer ALLE Requests ("**/*") ein. Auf einem
    BrowserContext aufgerufen gilt der Schutz auch fuer Popups/neue Tabs.
    Muss VOR der ersten Navigation zu einer Praxis-Website passieren."""
    await context_oder_page.route("**/*", ssrf_route_handler())


async def find_email_on_website(page, website_url):
    """Sucht eine Kontakt-Email auf der Praxis-Website (Startseite plus bis
    zu 3 Kontakt/Impressum-Unterseiten). Der Aufrufer MUSS vorher
    ssrf_schutz_einrichten() auf Context/Page ausgefuehrt haben (siehe
    enrich_emails); die Pruefungen hier (vorher +
    _nach_navigation_erlaubt nachher) sind die zweite Absicherung."""
    if not _ist_oeffentliche_http_url(website_url):
        return None
    try:
        await page.goto(website_url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return None
    if not _nach_navigation_erlaubt(page):
        return None
    email = await find_email_on_page(page)
    if email:
        return email
    sub_links = await page.evaluate("""() => {
        const keywords = ['kontakt', 'contact', 'impressum'];
        return [...document.querySelectorAll('a[href]')]
            .map(a => ({ href: a.href, text: (a.innerText + a.href).toLowerCase() }))
            .filter(a => keywords.some(k => a.text.includes(k)) && a.href.startsWith('http'))
            .map(a => a.href)
            .slice(0, 3);
    }""")
    for sub_url in sub_links:
        if not _ist_oeffentliche_http_url(sub_url):
            continue
        await asyncio.sleep(random.uniform(1.0, 2.0))  # Pause auch zwischen Unterseiten derselben Praxis-Website
        try:
            await page.goto(sub_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            continue
        if not _nach_navigation_erlaubt(page):
            continue
        email = await find_email_on_page(page)
        if email:
            return email
    return None


def extract_from_text(text):
    email = None
    for match in EMAIL_REGEX.finditer(text):
        candidate = _clean_email(match.group(0))
        if candidate:
            email = candidate
            break
    url_match = re.search(
        r'(https?://[^\s\)\]"\'<>]+|www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s\)\]"\'<>]*)',
        text
    )
    website = url_match.group(0) if url_match else None
    if website and not website.startswith("http"):
        website = "https://" + website
    return email, website


async def enrich_emails(input_file=OUTPUT_FILE):
    """Ergänzt fehlende Emails: erst aus Profiltext, dann von Praxis-Websites."""
    try:
        with open(input_file, encoding="utf-8") as f:
            profiles = json.load(f)
    except FileNotFoundError:
        print(f"Fehler: {input_file} nicht gefunden. Bitte zuerst den Scraper ausführen.")
        return

    print(f"  {len(profiles)} Profile geladen.")

    cleaned = 0
    for p in profiles:
        if p.get("email") and not _clean_email(p["email"]):
            p["email"] = ""
            cleaned += 1
    if cleaned:
        print(f"  {cleaned} ungültige Emails bereinigt.")

    from_text = 0
    for p in profiles:
        text = p.get("volltext", "") + " " + p.get("persoenliches_profil", "")
        email_found, website_found = extract_from_text(text)
        if not p.get("email") and email_found:
            p["email"] = email_found
            from_text += 1
        if not p.get("website") and website_found:
            p["website"] = website_found
    print(f"  Stufe 1: {from_text} Emails direkt aus Profiltext.")

    need = [p for p in profiles if not p.get("email") and p.get("website")]
    print(f"  Stufe 2: {len(need)} Praxis-Websites zu besuchen.")

    if need:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            found = 0
            try:
                context = await browser.new_context(user_agent=USER_AGENT)
                # SSRF-Schutz fuer JEDEN Request (Review #13), vor der
                # ersten Navigation zu einer Praxis-Website.
                await ssrf_schutz_einrichten(context)
                page = await context.new_page()
                for i, profile in enumerate(need, 1):
                    print(f"  [{i}/{len(need)}] {profile.get('name','?')} -> {profile.get('website')}")
                    email = await find_email_on_website(page, profile.get("website"))
                    if email:
                        profile["email"] = email
                        found += 1
                        print(f"    -> {email}")
                    await asyncio.sleep(2 + random.uniform(0, 1.5))
                    if i % 5 == 0:
                        json_atomar_schreiben(input_file, profiles)
            finally:
                # Zwischenstand und Browser immer sichern/schliessen, egal ob
                # der Lauf sauber endet, abgebrochen wird oder eine
                # unerwartete Exception wirft (sonst gehen alle seit dem
                # letzten Fuenfer-Block gefundenen Emails verloren).
                json_atomar_schreiben(input_file, profiles)
                try:
                    await browser.close()
                except Exception as e:
                    print(f"  Browser konnte nicht sauber geschlossen werden: {e}")
        print(f"  Stufe 2: {found} weitere Emails gefunden.")

    json_atomar_schreiben(input_file, profiles)
    total = sum(1 for p in profiles if p.get("email"))
    print(f"\n  Gesamt: {total} von {len(profiles)} Profilen haben eine Email.")


# ---------------------------------------------------------------------------
# Verzeichnis-/Plattform-Domains: nie die eigene Website einer Praxis
# ---------------------------------------------------------------------------

_DIRECTORY_DOMAINS = {
    "therapie.de", "jameda.de", "sanego.de", "doctolib.de",
    "arztsuche.de", "meinestadt.de", "gelbeseiten.de", "11880.com",
    "dasoertliche.de", "psychotherapeutensuche.de", "kvwl.de",
    "therapie-suche.de", "google.com", "google.de", "bing.com",
    "wikipedia.org", "facebook.com", "instagram.com", "linkedin.com",
    "xing.com", "twitter.com", "x.com", "youtube.com",
    "psychotherapie.de", "ivv.de", "imedo.de",
    "vorname.com", "namensbedeutung.net",
    # Grosse Plattformen/Konzerne -- nie die echte Website einer Einzelpraxis,
    # aber koennen als irrefuehrender Link auf Profilseiten auftauchen (siehe Bugfix-
    # Kommentar bei _EMAIL_DOMAIN_BLACKLIST: "kunden@microsoft.com"-Fehltreffer).
    "microsoft.com", "apple.com", "amazon.de", "amazon.com", "amazon.co.uk",
    "yahoo.com", "yahoo.de", "outlook.com", "live.com", "msn.com",
    "tiktok.com", "pinterest.com", "pinterest.de", "reddit.com", "github.com",
    # Bugfix (26.8.2026): Treffer der frueheren Bing-Suche fuer Namen landeten
    # faelschlich auf themenfremden, aber fuer den Namen hoch rankenden
    # Seiten (siehe _EMAIL_DOMAIN_BLACKLIST-Kommentar fuer Details/Beispiele).
    "baby-vornamen.de", "gala.de", "tvmovie.de", "crazygames.com",
    "mamenza.com", "website.com",
}


def _is_directory(url):
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    return any(domain == d or domain.endswith("." + d) for d in _DIRECTORY_DOMAINS)


if __name__ == "__main__":
    asyncio.run(main(neu="--neu" in sys.argv))
