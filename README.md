# Therapieplatz Finder

[![Backend-Tests](https://github.com/celtechstarter/therapieplatz-finder-backend/actions/workflows/tests.yml/badge.svg)](https://github.com/celtechstarter/therapieplatz-finder-backend/actions/workflows/tests.yml)

Findet Psychotherapeuten mit freien Kapazitäten, prüft sie automatisiert auf
Relevanz (Kassensitz, Behandlungsschwerpunkte, freie Plätze) und hilft beim
Versenden personalisierter Anfragen. Zwei Teile:

1. **`backend/`** – Python-Pipeline (scrapen → analysieren → lokal
   anschauen/versenden), läuft nur lokal, nicht deployed.
2. **`webapp/`** – die eigentliche, öffentlich erreichbare Web-App
   ([therapieplatz-finder.de](https://therapieplatz-finder.de)), eigenes
   Git-Repo, automatisches Deploy auf Vercel bei jedem Push.

Dieses Root-Verzeichnis ist inzwischen selbst ein (öffentliches) Git-Repository
– als Showcase der Backend-Pipeline, unabhängig von `webapp/`, das weiterhin
sein eigenes, separates Repo mit eigenem Deploy ist. Bewusst NICHT Teil dieses
öffentlichen Repos (siehe `.gitignore`): `data/`, `deliverables/`
(personenbezogene Kontaktdaten), alle Secrets, sowie `docs/` (enthält u.a.
Security-Audit-Details zu teils noch offenen Befunden) und `design/`
(kein Teil des eigentlichen Produkts). Diese Ordner
existieren weiterhin lokal, sind nur nicht veröffentlicht.

## So ist das Projekt entstanden

Ehrlich vorweg: Ich bin kein ausgebildeter Entwickler. Den Code hat zum
größten Teil eine KI geschrieben (Claude, über Cowork und Claude Code), und
ich lese ihn nicht Zeile für Zeile. Das ist das, was man „Vibe Coding“ nennt.
Die Idee kam aus meiner eigenen, langen Suche nach einem Therapieplatz.

Ich weiß, dass Vibe Coding zu Recht kritisch gesehen wird: Code, den niemand
versteht, kann Fehler und Sicherheitslücken enthalten, die keiner bemerkt.
Darum habe ich mir Regeln gesetzt, die genau das abfangen sollen:

- **Tests gehören zu jeder Änderung.** Im Backend gibt es über 500
  pytest-Tests, in der Webapp über 600 `node --test`-Tests plus
  Playwright-Tests für Klickwege, Tastatur und Barrierefreiheit. Beide
  laufen bei jedem Push automatisch (GitHub Actions). Viele Tests
  sind aus echten Fehlern im Betrieb entstanden. Der Hintergrund steht
  jeweils im Docstring.
- **Regeln stehen schriftlich fest.** In `CLAUDE.md` steht, wie die KI hier
  arbeiten muss: Tests vor jedem Commit, keine Secrets im Repo, Threat-Check
  bei allem, was Nutzerdaten anfasst, kein Push ohne mein ausdrückliches OK.
- **Wiederholte Prüfungen.** Es gab mehrere Sicherheits- und Code-Audits
  (August, September, Oktober 2026), die Befunde sind größtenteils behoben
  und mit Tests abgesichert.
- **Die KI entscheidet nichts Wichtiges allein.** Wer in die Liste kommt,
  entscheiden harte, nachprüfbare Regeln (`filters.py`). Die KI liefert nur
  drei eng begrenzte Felder, alles andere aus ihrer Antwort wird verworfen
  (Schutz gegen Prompt Injection über präparierte Profiltexte).

Bekannte Baustellen, die ich selbst sehe:

- **Große Dateien.** `backend/scraper.py` (rund 750 Zeilen) macht mehrere
  Dinge auf einmal: Suchergebnisse lesen, Profile auslesen, Praxis-Websites
  nach E-Mails durchsuchen. In der Webapp ist `app/app-views.js` mit rund
  2.400 Zeilen die größte Datei. Beides sollte in kleinere Module zerlegt
  werden. Ich habe das bewusst noch nicht gemacht, weil die App live ist und
  ein großer Umbau ohne Not Fehler einschleppen kann.
- **Lange Kommentare.** Viele Kommentare erzählen die Geschichte eines
  Bugfixes mit Datum. Das hilft beim Nachvollziehen, macht den Code aber
  länger als nötig.
- **Deutsch und Englisch gemischt.** Neuere Funktionen heißen deutsch
  (`lies_profil`), ältere englisch (`extract_profile`).
- **`backend/frontend/`** ist nur noch eine lokale Vorschau aus der
  Anfangszeit. Das eigentliche Produkt ist die Webapp.

Was fehlt: Bisher hat noch kein Mensch vom Fach den Code geprüft. Alle
Prüfungen kamen von KI oder von mir. Kritik und Hinweise sind ausdrücklich
willkommen.

## Verzeichnis-Übersicht

```
therapie-mailer/
├── README.md                 <- diese Datei
├── CLAUDE.md                 <- Projekt-Anweisungen für Claude/Cowork
├── LICENSE                   <- MIT-Lizenz
├── .github/workflows/        <- GitHub Actions: pytest bei jedem Push
├── .env                      <- ANTHROPIC_API_KEY (Secret, gitignored)
├── .env.example              <- Vorlage für .env (nur Platzhalter, im Repo)
├── credentials.json          <- Gmail-OAuth-Client (Secret, gitignored)
├── token.json                <- Gmail-Login-Token (Secret, gitignored)
├── requirements.txt           <- Python-Abhängigkeiten (feste Versionen)
├── conftest.py                <- pytest-Konfiguration (projektweit)
│
├── backend/                  <- Python-Pipeline
│   ├── pfade.py                <- zentrale Pfad-Konstanten (siehe unten)
│   ├── scraper.py              <- Scraper für die Haupt-Suchseite (Playwright)
│   ├── umkreis_ausbau.py       <- Hauptquelle Ort für Ort über Firecrawl erweitern (Ringplan, Credit-Budget)
│   ├── analyzer.py             <- KI-Analyse (Claude API) + harte Filterregeln
│   ├── filters.py              <- harte Zulassungsregeln (VOR der KI-Analyse)
│   ├── mailer.py               <- Gmail-Versand (OAuth2)
│   ├── dateihilfen.py          <- gemeinsame Helfer (atomares JSON-Schreiben)
│   ├── merge_hilfen.py         <- gemeinsame Merge-/Dedup-Logik für Zusatzquellen
│   ├── main.py                 <- Orchestrator: startet Scraper -> Analyzer -> lokalen Server
│   └── frontend/index.html     <- einfache lokale Vorschau-Oberfläche (von main.py ausgeliefert)
│
│   Daneben pflegt Marcel lokal noch mehrere quellen-spezifische Scraper/Merge-
│   Skripte, die zusätzliche öffentliche Register/Verzeichnisse mit der
│   Hauptquelle abgleichen. Diese sind bewusst NICHT Teil dieses öffentlichen
│   Repos (siehe .gitignore) und werden auch im Rest dieser README nicht
│   namentlich genannt.
│
├── data/                      <- alle Scraping-/Analyse-Ergebnisse (JSON, gitignored)
│   ├── results_raw.json          <- rohe Scraper-Ausgabe
│   ├── results_analyzed.json     <- nach KI-Analyse + Filterung (Endergebnis)
│   ├── ausgeschlossen.json       <- Analyzer-Log: alle automatisch Ausgeschlossenen MIT Begründung
│   ├── excluded.json             <- manuell ausgeblendete Profile (über die lokale Vorschau)
│   ├── sent_log.json             <- Versandhistorie
│   └── archiv/                   <- letzte Sicherung vor großen Umbauten + ausgemusterte Einmal-Skripte
│
├── docs/                      <- Projektdokumente (nicht öffentlich, siehe .gitignore)
│   └── archiv/                   <- abgearbeitete Reviews/Audits/Briefings (nur noch als Nachweis)
├── design/                    <- Design-Rohmaterial (nicht öffentlich, siehe .gitignore)
├── deliverables/               <- fertige Exporte (xlsx/pdf/Videos)
│   └── flyer/                    <- Druck-PDFs; Bau-Skripte in flyer/quellen/
├── tests/                      <- pytest-Tests fürs Backend (siehe unten)
│
└── webapp/                     <- DAS DEPLOYTE PRODUKT (eigenes Git-Repo!)
    ├── app/                       <- Single-Page-App (app.js, index.html, ...)
    ├── api/                       <- Vercel-Functions (Auth, Datenauslieferung)
    ├── assets/                    <- finale, optimierte Bilder/Grafiken
    ├── tests/                     <- Node-Tests (node --test)
    ├── *.html                     <- statische Seiten (Impressum, Datenschutz, Landingpage, ...)
    └── ROADMAP.md, CONTRIBUTING.md, ... <- webapp-spezifische Doku (liegt bewusst IM Repo)
```

## Backend starten

```bash
cd backend
pip install -r ../requirements.txt
playwright install chromium        # einmalig
cp ../.env.example ../.env          # dann ANTHROPIC_API_KEY eintragen
                                    # (alternativ: export ANTHROPIC_API_KEY=dein_key)

python main.py                      # scrapt, analysiert, öffnet lokale Vorschau im Browser
python main.py --skip-scraper       # nur neu analysieren (results_raw.json existiert schon)
python main.py --skip-analyzer      # nur scrapen, ohne KI-Analyse (kein API-Key nötig)
python main.py --skip-scraper --neu-analyse-alt  # auch alte Ergebnisse ohne Inhalts-Hash neu analysieren (kostet API-Aufrufe)
python main.py --only-emails        # nur fehlende Emails nachrecherchieren
python main.py --stats              # nur Statistik ausgeben, kein Server
```

Einzugsgebiet erweitern (braucht `FIRECRAWL_API_KEY` in der `.env`):

```bash
python umkreis_ausbau.py            # Ringplan, Status je Ort, verbrauchte Credits (kostet nichts)
python umkreis_ausbau.py --los      # nächste offene Orte abarbeiten, bis das Monatsbudget erreicht ist
python umkreis_ausbau.py --los --budget 200 --max-orte 2
python dedupe_bestand.py && python analyzer.py && python build_webapp_chunks.py   # danach wie gewohnt
```

Der Fortschritt steht in `data/umkreis_status.json`; eine lesbare Übersicht
schreibt das Skript nach jedem Ort nach `docs/UMKREIS_AUSBAU.md` (lokal).

Ohne `--skip-analyzer` prüft `main.py` den `ANTHROPIC_API_KEY` **vor** dem
Scraper und bricht sofort ab, wenn er fehlt – sonst würde erst der Analyzer
nach dem stundenlangen Scraping-Lauf scheitern.

`backend/pfade.py` legt fest, wo alle Ergebnisdateien landen (`../data/`)
und wo die Secrets erwartet werden (`../credentials.json`, `../token.json`)
– unabhängig davon, aus welchem Verzeichnis man ein Skript startet.

## Tests

```bash
python -m pytest tests/ -q                     # Backend (pytest)
python -m pytest tests/ --cov=backend         # mit Abdeckung (pip install pytest-cov)
cd webapp && npm test                           # Webapp (node --test)
```

Die Backend-Tests liegen in `tests/` und decken jeweils ein Modul ab, u.a.
`test_analyzer.py`, `test_dateihilfen.py`, `test_filters.py`, `test_mailer.py`,
`test_main.py`, `test_main_server.py` (echter lokaler Vorschau-Server),
`test_merge_hilfen.py`, `test_pfade.py`, `test_scraper.py`,
`test_scraper_ablauf.py` (Blättern, Resume, Ban-Stopp, Email-Suche mit
Browser-Attrappe), `test_stats_export.py`, `test_umkreis_ausbau.py`,
`test_build_webapp_chunks.py`, `test_build_plz_tabelle.py`. Kein Test geht ins Netz.

Abdeckung (Stand 3.10.2026): Backend 88 % der Zeilen in diesem Repo,
Webapp-API ca. 90 %. Die Oberfläche (`webapp/app/`) ist nicht als Zahl
messbar, weil die Tests sie in einem simulierten Browser laden; sie wird
von den node-Tests und den Playwright-Browser-Tests geprüft.
Einzige Ausnahme beim Browser: ein Test in `test_umkreis_ausbau.py` lädt
ein Beispiel-Profil in einen lokalen Chromium (ohne Netzwerk) und wird
übersprungen, wenn keiner installiert ist.

Beides sollte vor jedem Commit grün sein – ein Teil der Tests entstand direkt
aus echten, im Betrieb gefundenen Fehlern (siehe Docstrings/Commit-Messages
der jeweiligen Testdatei für den Hintergrund).

## Secrets

`.env`, `credentials.json`, `token.json` sowie alles unter `data/`
und `deliverables/` (dort liegen dieselben personenbezogenen
Kontaktdaten als xlsx/pdf) sind in `.gitignore` eingetragen; ebenso `*.pdf`
und `*.xlsx` direkt im Root. Als Vorlage für die eigene `.env` dient
`.env.example` – die enthält nur Platzhalter und darf ins Repo. `webapp/` hat
sein eigenes, separates `.gitignore` und enthält keine dieser Dateien.

## Webapp (das eigentliche Produkt)

Läuft komplett unabhängig vom Backend – die Webapp hat ihre eigene
Nutzerverwaltung (Supabase Auth) und lädt ihre Therapeuten-Daten aus fertig
gebauten, base64-codierten Datenchunks (`webapp/api/*.b64`), nicht live aus
`data/`. Wie diese Chunks aktuell gehalten werden und wie das Deployment
funktioniert, steht in `webapp/ROADMAP.md`.

## Lizenz

Der Code in diesem Repository steht unter der [MIT-Lizenz](LICENSE): Du darfst
ihn lesen, nutzen, verändern und weitergeben, solange der Lizenzhinweis mit
meinem Namen erhalten bleibt. Die Praxisdaten und die Webapp gehören nicht
dazu, sie sind nicht Teil dieses Repos.
