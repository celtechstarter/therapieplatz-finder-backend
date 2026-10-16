"""Tests fuer backend/umkreis_ausbau.py. Kein echter Firecrawl-Aufruf, kein
Netzwerk: Abrufe und Profil-Auslese werden durch Fakes ersetzt. Nur der
letzte Test startet (falls vorhanden) einen lokalen Chromium, um zu pruefen,
dass Firecrawl-HTML ueber scraper.lies_profil() korrekt ausgelesen wird."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
import umkreis_abruf as abruf
import umkreis_ausbau as ua
import umkreis_doku as udoku
import umkreis_plan as plan


def JETZT():
    return datetime(2026, 9, 30, 12, 0)


def _liste(slugs, treffer=None):
    titel = f"<title>{treffer} Therapeuten in und um X | therapie.de</title>" if treffer else ""
    links = "".join(f'<a href="/profil/{s}/">x</a><a href="/profil/{s}/">doppelt</a>' for s in slugs)
    return f"<html><head>{titel}</head><body>{links}<a href=\"/profil/info/\">info</a></body></html>"


class FakeLeser:
    def __init__(self):
        self.gelesen = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def lesen(self, url, html):
        self.gelesen.append(url)
        if "kaputt" in url:
            return None
        return {"profil_url": url, "name": url.rsplit("/", 2)[-2]}


def _holer(seiten, zaehler):
    """seiten: dict url -> html. Unbekannte URL = Profilseite."""
    def holen(url):
        zaehler.append(url)
        return seiten.get(url, "<div class='therapist-details'>Profil</div>"), 1
    return holen


def _pfade(tmp_path, raw=None):
    raw_pfad = tmp_path / "raw.json"
    raw_pfad.write_text(json.dumps(raw or []), encoding="utf-8")
    return dict(status_pfad=tmp_path / "status.json", raw_pfad=raw_pfad,
                doku_pfad=tmp_path / "UMKREIS.md")


# ---------- Suchseiten ----------

def test_such_url_enthaelt_quellfilter_und_kodierten_ort():
    url = abruf.such_url("Lünen")
    assert "ort=L%C3%BCnen" in url
    assert "abrechnungsverfahren=7" in url and "therapieangebot=1" in url
    assert "page=" not in url
    assert abruf.such_url("Lünen", 3).endswith("&page=3")


def test_profil_links_eindeutig_absolut_ohne_info():
    links = abruf.profil_links_aus_html(_liste(["a.b", "c"]))
    assert links == ["https://www.therapie.de/profil/a.b/", "https://www.therapie.de/profil/c/"]


def test_trefferzahl_aus_titel():
    assert abruf.trefferzahl_aus_html(_liste(["a"], treffer=79)) == 79
    assert abruf.trefferzahl_aus_html("<html></html>") is None


# ---------- Plan / Status ----------

def test_naechste_orte_ueberspringt_bestand_und_fertige_und_zieht_angefangene_vor():
    status = plan.lade_status(Path("/nicht/da.json"))
    assert "Dortmund" not in plan.naechste_orte(status)
    erster_ring = [o for o, _ in plan.UMKREIS_PLAN[1]["orte"]]
    status["orte"][erster_ring[0]] = {"status": "fertig"}
    status["orte"][erster_ring[2]] = {"status": "teilweise"}
    naechste = plan.naechste_orte(status, 2)
    assert naechste[0] == erster_ring[2]
    assert erster_ring[0] not in plan.naechste_orte(status)


def test_plan_ringe_sind_nach_entfernung_sortiert():
    for ring in plan.UMKREIS_PLAN:
        kms = [km for _, km in ring["orte"]]
        assert kms == sorted(kms), f"Ring {ring['ring']} nicht sortiert"
    orte = [o for r in plan.UMKREIS_PLAN for o, _ in r["orte"]]
    assert len(orte) == len(set(orte)), "Ort doppelt im Plan"


def test_credits_werden_pro_monat_und_ort_gebucht():
    status = plan.lade_status(Path("/nicht/da.json"))
    plan.buche_credits(status, 3, "Kamen", JETZT())
    plan.buche_credits(status, 2, "Kamen", JETZT())
    assert status["credits_pro_monat"]["2026-09"] == 5
    assert status["orte"]["Kamen"]["credits"] == 5


# ---------- Lauf ----------

def test_lauf_holt_nur_neue_profile_und_markiert_ort_fertig(tmp_path):
    seiten = {abruf.such_url("Kamen", 1): _liste(["alt", "neu1"], treffer=3),
              abruf.such_url("Kamen", 2): _liste(["neu2", "kaputt"]),
              abruf.such_url("Kamen", 3): _liste([])}
    abrufe = []
    raw = [{"profil_url": "https://www.therapie.de/profil/alt/", "name": "Alt"}]
    p = _pfade(tmp_path, raw)
    status = asyncio.run(ua.lauf(["Kamen"], _holer(seiten, abrufe), leser_fabrik=FakeLeser,
                                 budget=100, jetzt=JETZT, **p))
    e = status["orte"]["Kamen"]
    assert e["status"] == "fertig" and e["treffer"] == 3
    assert e["gefunden"] == 4 and e["neu"] == 2
    assert e["fehlgeschlagen"] == ["https://www.therapie.de/profil/kaputt/"]
    assert "https://www.therapie.de/profil/alt/" not in abrufe  # bekannt -> kein Credit
    assert e["credits"] == len(abrufe) == 6  # 3 Suchseiten + 3 Profile
    gespeichert = json.loads(p["raw_pfad"].read_text(encoding="utf-8"))
    neue = [r for r in gespeichert if r.get("erfasst_ueber") == "firecrawl"]
    assert {r["suchort"] for r in neue} == {"Kamen"} and len(neue) == 2
    doku = p["doku_pfad"].read_text(encoding="utf-8")
    assert "| Kamen | 10 | fertig | 2026-09-30 | 3 | 4 | 2 | 6 |" in doku


def test_lauf_stoppt_bei_budget_und_macht_spaeter_ohne_suchseiten_weiter(tmp_path):
    seiten = {abruf.such_url("Kamen", 1): _liste(["a", "b", "c"]), abruf.such_url("Kamen", 2): _liste([])}
    p = _pfade(tmp_path)
    abrufe = []
    status = asyncio.run(ua.lauf(["Kamen"], _holer(seiten, abrufe), leser_fabrik=FakeLeser,
                                 budget=3, jetzt=JETZT, **p))
    e = status["orte"]["Kamen"]
    assert e["status"] == "teilweise" and e["neu"] == 1
    assert e["offene_urls"] == ["https://www.therapie.de/profil/b/", "https://www.therapie.de/profil/c/"]

    abrufe2 = []
    status = asyncio.run(ua.lauf(["Kamen"], _holer(seiten, abrufe2), leser_fabrik=FakeLeser,
                                 budget=10, jetzt=JETZT, **p))
    assert all("/profil/" in u for u in abrufe2), "Suchseiten duerfen nicht erneut abgerufen werden"
    assert status["orte"]["Kamen"]["status"] == "fertig"
    assert status["orte"]["Kamen"]["neu"] == 3
    assert "offene_urls" not in status["orte"]["Kamen"]


def test_lauf_respektiert_monatslimit(tmp_path):
    p = _pfade(tmp_path)
    p["status_pfad"].write_text(json.dumps({"orte": {}, "credits_pro_monat": {"2026-09": 1000}}))
    abrufe = []
    asyncio.run(ua.lauf(["Kamen"], _holer({}, abrufe), leser_fabrik=FakeLeser,
                        monatslimit=1000, jetzt=JETZT, **p))
    assert abrufe == []


def test_lauf_stoppt_sofort_wenn_ziel_blockiert(tmp_path):
    p = _pfade(tmp_path)

    def holen(url):
        raise abruf.ZielBlockiert("therapie.de antwortet mit 429")
    status = asyncio.run(ua.lauf(["Kamen", "Lünen"], holen, leser_fabrik=FakeLeser,
                                 budget=50, jetzt=JETZT, **p))
    assert "Lünen" not in status["orte"]
    assert status["orte"]["Kamen"]["status"] == "teilweise"


# ---------- Firecrawl-Client ----------

class FakeAntwort:
    def __init__(self, code, daten=None):
        self.status_code = code
        self._daten = daten

    def json(self):
        return self._daten


class FakeHttp:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.aufrufe.append((url, headers, json))
        return self.antworten.pop(0)


def test_firecrawl_ohne_key_bricht_mit_klarer_meldung_ab():
    with pytest.raises(abruf.FirecrawlFehler, match="FIRECRAWL_API_KEY"):
        abruf.firecrawl_holer("")


def test_firecrawl_liefert_html_und_credits_und_schickt_key_nur_im_header():
    http = FakeHttp([FakeAntwort(200, {"data": {"rawHtml": "<p>x</p>",
                                                 "metadata": {"statusCode": 200, "creditsUsed": 1}}})])
    holen = abruf.firecrawl_holer("fc-test", http=http, schlafen=lambda s: None)
    assert holen("https://www.therapie.de/profil/a/") == ("<p>x</p>", 1)
    url, headers, body = http.aufrufe[0]
    assert url == abruf.FIRECRAWL_URL and headers["Authorization"] == "Bearer fc-test"
    assert "fc-test" not in json.dumps(body)
    # Rohes HTML der ganzen Seite: lies_profil braucht alle Profilblöcke.
    assert body == {"url": "https://www.therapie.de/profil/a/", "formats": ["rawHtml"], "onlyMainContent": False}


def test_firecrawl_402_heisst_credits_leer():
    holen = abruf.firecrawl_holer("k", http=FakeHttp([FakeAntwort(402)]), schlafen=lambda s: None)
    with pytest.raises(abruf.CreditsLeer):
        holen("u")


def test_firecrawl_429_wartet_und_versucht_erneut():
    pausen = []
    http = FakeHttp([FakeAntwort(429), FakeAntwort(200, {"data": {"rawHtml": "ok", "metadata": {}}})])
    holen = abruf.firecrawl_holer("k", pause=1, http=http, schlafen=pausen.append)
    assert holen("u") == ("ok", 1)
    assert 60 in pausen


def test_firecrawl_zielseite_403_stoppt():
    http = FakeHttp([FakeAntwort(200, {"data": {"rawHtml": "", "metadata": {"statusCode": 403}}})])
    holen = abruf.firecrawl_holer("k", http=http, schlafen=lambda s: None)
    with pytest.raises(abruf.ZielBlockiert):
        holen("u")


# ---------- Doku ----------

def test_doku_ersetzt_nur_auto_bereich(tmp_path):
    pfad = tmp_path / "U.md"
    pfad.write_text(f"# Kopf\n\n{udoku.DOKU_START}\nalt\n{udoku.DOKU_ENDE}\n\n## Notizen\n- bleibt\n", encoding="utf-8")
    status = plan.lade_status(tmp_path / "x.json")
    status["orte"]["Bielefeld"] = {"status": "fertig", "datum": "2026-10-01", "gefunden": 5, "neu": 2, "credits": 8}
    udoku.schreibe_doku(status, pfad, JETZT(), quellen={})
    text = pfad.read_text(encoding="utf-8")
    assert text.startswith("# Kopf") and "- bleibt" in text and "\nalt\n" not in text
    assert "| Dortmund | 0 | Bestand |" in text
    assert "| Bielefeld | fertig | 2026-10-01 | 5 | 2 | 8 |" in text
    assert text.count(udoku.DOKU_START) == 1


def test_doku_wird_neu_angelegt_wenn_es_sie_noch_nicht_gibt(tmp_path):
    pfad = tmp_path / "neu" / "U.md"
    status = plan.lade_status(tmp_path / "x.json")
    status["orte"]["Kamen"] = {"status": "fertig", "neu": 3}
    status["orte"]["Hamm"] = {"status": "fertig", "neu": 1}
    status["orte"]["Lünen"] = {"status": "teilweise", "neu": 2}
    udoku.schreibe_doku(status, pfad, JETZT(), quellen={})
    text = pfad.read_text(encoding="utf-8")
    assert text.startswith("# Umkreis-Ausbau\n\n" + udoku.DOKU_START)
    assert "**Stand:** 2 Orte fertig, 6 neue Profile über Firecrawl." in text


def test_doku_mit_nur_einem_marker_wird_nicht_zerschnitten(tmp_path):
    """Fehlt der Endmarker (z. B. von Hand gelöscht), bleibt der alte Text
    komplett erhalten und der neue Bereich wird angehängt."""
    pfad = tmp_path / "U.md"
    pfad.write_text(f"# Eigene Notizen\n{udoku.DOKU_START}\nhalb\n", encoding="utf-8")
    udoku.schreibe_doku(plan.lade_status(tmp_path / "x.json"), pfad, JETZT(), quellen={})
    text = pfad.read_text(encoding="utf-8")
    assert text.startswith(f"# Eigene Notizen\n{udoku.DOKU_START}\nhalb\n")
    assert text.count(udoku.DOKU_ENDE) == 1


def test_echte_doku_datei_hat_auto_marker():
    # docs/ ist gitignored (nur lokal) -- in einem frischen Clone fehlt sie.
    if not udoku.DOKU_DATEI.exists():
        pytest.skip("docs/UMKREIS_AUSBAU.md nur lokal vorhanden")
    text = udoku.DOKU_DATEI.read_text(encoding="utf-8")
    assert udoku.DOKU_START in text and udoku.DOKU_ENDE in text


# ---------- Profil-Auslese mit echtem (lokalem) Browser ----------

PROFIL_HTML = """<html><body>
<h1>Dipl.-Psych. Erika Beispiel</h1>
<div class="therapist-details">Erika Beispiel<br>Psychologische Psychotherapeutin
<span itemprop="streetAddress">Musterweg 1</span> <span itemprop="postalCode">59174</span>
<span itemprop="addressLocality">Kamen</span> <span itemprop="telephone">02307 123</span>
<a href="mailto:praxis@beispiel-kamen.de">Mail</a></div>
<div class="therapist-details"><div id="abrechnungsverfahren">Kassenleistung, Selbstzahler</div>
<h4>Therapie-Angebot</h4><ul><li>Einzeltherapie: Erwachsene</li></ul></div>
</body></html>"""


def test_profil_leser_liest_firecrawl_html_wie_scraper():
    async def lauf():
        async with abruf.ProfilLeser() as leser:
            return await leser.lesen("https://www.therapie.de/profil/beispiel/", PROFIL_HTML)
    try:
        profil = asyncio.run(lauf())
    except Exception as e:  # kein Chromium in dieser Umgebung
        pytest.skip(f"Browser nicht verfuegbar: {e}")
    assert profil["name"] == "Dipl.-Psych. Erika Beispiel"
    assert profil["adresse"] == "Musterweg 1, 59174 Kamen"
    assert profil["email"] == "praxis@beispiel-kamen.de"
    assert profil["abrechnungsarten"] == ["Kassenleistung", "Selbstzahler"]
    assert profil["therapieangebot"] == ["Einzeltherapie: Erwachsene"]
    assert "screenshot" not in profil


def test_profil_leser_ohne_profilblock_liefert_none():
    leser = abruf.ProfilLeser()
    assert asyncio.run(leser.lesen("u", "<html>Captcha</html>")) is None


def test_profil_leser_schaltet_javascript_aus_und_blockt_alle_anfragen(monkeypatch):
    """Das HTML kommt von einer fremden Seite. Beim Auslesen darf es weder
    Skripte ausfuehren noch irgendetwas nachladen (Tracking, Bilder, Fremd-
    Anfragen). Geprueft ohne echten Browser ueber eine Attrappe."""
    import types
    protokoll = {}

    class _Route:
        def __init__(self):
            self.abgebrochen = False

        async def abort(self):
            self.abgebrochen = True

    class _Kontext:
        async def route(self, muster, handler):
            protokoll["muster"] = muster
            protokoll["handler"] = handler

        async def new_page(self):
            return "seite"

    class _Browser:
        async def new_context(self, **optionen):
            protokoll["optionen"] = optionen
            return _Kontext()

        async def close(self):
            protokoll["geschlossen"] = True

    class _PW:
        class chromium:
            @staticmethod
            async def launch(headless):
                protokoll["headless"] = headless
                return _Browser()

        async def start(self):
            return self

        async def stop(self):
            protokoll["gestoppt"] = True

    fake = types.ModuleType("playwright.async_api")
    fake.async_playwright = lambda: _PW()
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake)

    async def lauf():
        async with abruf.ProfilLeser():
            pass
        route = _Route()
        await protokoll["handler"](route)
        return route

    route = asyncio.run(lauf())
    assert protokoll["optionen"]["java_script_enabled"] is False
    assert protokoll["headless"] is True
    assert protokoll["muster"] == "**/*"
    assert route.abgebrochen
    assert protokoll["geschlossen"] and protokoll["gestoppt"]


def test_profil_leser_nimmt_kartenlink_nicht_als_website():
    html = PROFIL_HTML.replace('<a href="mailto:', '<a href="https://www.google.com/maps/search/?api=1">Karte</a><a href="mailto:')
    async def lauf():
        async with abruf.ProfilLeser() as leser:
            return await leser.lesen("https://www.therapie.de/profil/beispiel/", html)
    try:
        profil = asyncio.run(lauf())
    except Exception as e:
        pytest.skip(f"Browser nicht verfuegbar: {e}")
    assert profil["website"] == ""


# ---------- gemeinsamer Plan fuer die Zusatz-Scraper ----------

def test_suchorte_ring0_ist_bestand_und_ring1_haengt_an():
    assert plan.suchorte(0) == ["Dortmund", "Unna", "Bönen"]
    ring1 = plan.suchorte(1)
    assert ring1[:3] == ["Dortmund", "Unna", "Bönen"] and "Kamen" in ring1 and "Bochum" not in ring1


def test_bis_ring_aus_argv():
    assert plan.bis_ring_aus_argv(["x.py"]) == 0
    assert plan.bis_ring_aus_argv(["x.py", "--bis-ring", "2"]) == 2
    with pytest.raises(SystemExit):
        plan.bis_ring_aus_argv(["x.py", "--bis-ring"])


def test_vermerke_quelle_erscheint_in_doku(tmp_path):
    doku = tmp_path / "U.md"
    udoku.vermerke_quelle("Kammer", 1, ["Menden"], status_pfad=tmp_path / "s.json", doku_pfad=doku,
                       jetzt=JETZT, quellen_pfad=tmp_path / "q.json")
    text = doku.read_text(encoding="utf-8")
    assert "| Kammer | 1 | 2026-09-30 | Menden |" in text


# ---------- mehrdeutige Ortsnamen (Befund 30.9.2026) ----------

def test_mehrdeutiger_ort_nutzt_eindeutigen_suchbegriff():
    assert "ort=59065" in abruf.such_url("Hamm")
    assert "ort=Menden%20%28Sauerland%29" in abruf.such_url("Menden")
    assert "ort=Kamen" in abruf.such_url("Kamen")


def test_null_treffer_wird_nicht_als_fertig_abgehakt(tmp_path):
    seiten = {abruf.such_url("Hamm", 1): "<title>0 Therapeuten in und um | therapie.de</title>"}
    abrufe = []
    p = _pfade(tmp_path)
    status = asyncio.run(ua.lauf(["Hamm"], _holer(seiten, abrufe), leser_fabrik=FakeLeser,
                                 budget=10, jetzt=JETZT, **p))
    assert status["orte"]["Hamm"]["status"] == "kein_treffer"
    assert len(abrufe) == 1
    assert "Hamm" not in plan.naechste_orte(status)  # erst nach Pruefung des Suchbegriffs erneut
    assert "0 Treffer, Suchbegriff prüfen" in p["doku_pfad"].read_text(encoding="utf-8")


# ---------- Kommandozeile ----------

def _main(tmp_path, argv, status=None):
    status_pfad, doku_pfad = tmp_paths = (tmp_path / "status.json", tmp_path / "U.md")
    if status is not None:
        status_pfad.write_text(json.dumps(status), encoding="utf-8")
    aufrufe = []
    ua.main(argv, status_pfad=status_pfad, doku_pfad=doku_pfad,
            starte_lauf=lambda orte, **k: aufrufe.append((orte, k)))
    return aufrufe, tmp_paths


def test_main_doku_schreibt_nur_die_uebersicht(tmp_path):
    aufrufe, (_, doku_pfad) = _main(tmp_path, ["--doku"])
    assert aufrufe == []
    assert udoku.DOKU_START in doku_pfad.read_text(encoding="utf-8")


def test_main_ohne_schalter_zeigt_nur_den_stand(tmp_path, capsys):
    aufrufe, (_, doku_pfad) = _main(tmp_path, [])
    assert aufrufe == [] and not doku_pfad.exists()
    assert "Als Naechstes: Holzwickede" in capsys.readouterr().out


def test_main_los_nimmt_die_naechsten_offenen_orte_mit_budget(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRECRAWL_MONATSLIMIT", raising=False)
    aufrufe, _ = _main(tmp_path, ["--los", "--max-orte", "2", "--budget", "50"])
    assert aufrufe == [(["Holzwickede", "Kamen"], {"budget": 50, "monatslimit": 1000})]


def test_main_ort_nimmt_genau_diesen_ort(tmp_path):
    aufrufe, _ = _main(tmp_path, ["--ort", "Paderborn"])
    assert aufrufe[0][0] == ["Paderborn"]


def test_main_alles_erledigt_startet_keinen_lauf(tmp_path, capsys):
    fertig = {"orte": {o: {"status": "fertig"} for r in plan.UMKREIS_PLAN for o, _ in r["orte"]},
              "credits_pro_monat": {}}
    aufrufe, _ = _main(tmp_path, ["--los"], status=fertig)
    assert aufrufe == []
    assert "Alle Orte im Plan sind erledigt" in capsys.readouterr().out


def test_doku_stand_zaehlt_fertige_orte_und_neue_profile():
    status = {"orte": {"Kamen": {"status": "fertig", "neu": 4}, "Unna": {"status": "fertig"},
                       "Lünen": {"status": "teilweise", "neu": 2}},
              "credits_pro_monat": {"2026-09": 30, "2026-10": 12}}
    text = udoku.doku_tabelle(status, jetzt=JETZT(), quellen={})
    assert "**Stand:** 2 Orte fertig, 6 neue Profile" in text
    assert "Firecrawl-Credits: 2026-09: 30, 2026-10: 12_" in text


def test_doku_legt_fehlende_ordner_an(tmp_path):
    ziel = tmp_path / "neu" / "unter" / "U.md"
    udoku.schreibe_doku({"orte": {}, "credits_pro_monat": {}}, ziel, jetzt=JETZT(), quellen={})
    assert udoku.DOKU_START in ziel.read_text(encoding="utf-8")
