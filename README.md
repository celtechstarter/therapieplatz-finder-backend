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

- **Große Dateien.** Im Backend sind Scraper und Analyzer inzwischen in
  kleine Module mit je einer Aufgabe zerlegt (siehe Verzeichnis-Übersicht).
  Keine Backend-Datei hat mehr als rund 400 Zeilen. Noch groß ist in der
  Webapp `app/app-views.js` (rund 2.400 Zeilen). Die Webapp ist live, dort
  baue ich nur in kleinen, einzeln getesteten Schritten um.
- **Lange Kommentare.** Viele Kommentare erzählen die Geschichte eines
  Bugfixes mit Datum. Das hilft beim Nachvollziehen, macht den Code aber
  länger als nötig.
- **Deutsch und Englisch gemischt.** Neuere Funktionen heißen deutsch
  (`lies_profil`), ältere englisch (`extract_profile`).

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
├── requirements.txt           <- Python-Abhängigkeiten (feste Versionen)
├── conftest.py                <- pytest-Konfiguration (projektweit)
│
├── backend/                  <- Python-Pipeline
│   ├── pfade.py                <- zentrale Pfad-Konstanten (siehe unten)
│   ├── scraper.py              <- Suchseiten und Profile von therapie.de lesen (Playwright)
│   ├── email_suche.py          <- fehlende E-Mails ergänzen (Profiltext, dann eigene Praxis-Website)
│   ├── browser_schutz.py       <- Browser darf nur öffentliche Adressen öffnen (SSRF-Schutz)
│   ├── umkreis_ausbau.py       <- Hauptquelle Ort für Ort über Firecrawl erweitern (Ablauf + Kommandozeile)
│   ├── umkreis_plan.py         <- Ringplan um Dortmund, Status je Ort, Credits pro Monat
│   ├── umkreis_abruf.py        <- Seiten über Firecrawl holen und auslesen
│   ├── umkreis_doku.py         <- schreibt die Übersicht docs/UMKREIS_AUSBAU.md
│   ├── email_vorlagen.py       <- 40 Beispiel-Anfragen (Texte in daten/anfrage_vorlagen.json)
│   ├── filters.py              <- harte Zulassungsregeln (VOR der KI-Analyse)
│   ├── analyzer.py             <- Ablauf der Analyse: wer muss neu bewertet werden, Ergebnisse speichern
│   ├── analyse_regeln.py       <- Bewertung ohne KI (Inhalts-Hash, Wortsuche, "zu wenig Angaben")
│   ├── analyse_ki.py           <- Bewertung mit Claude (Prompt, Antwort prüfen, nur 3 erlaubte Felder)
│   ├── dateihilfen.py          <- gemeinsame Helfer (atomares JSON-Schreiben)
│   ├── merge_hilfen.py         <- gemeinsame Merge-/Dedup-Logik für Zusatzquellen
│   └── main.py                 <- Startbefehl: Scraper -> Analyzer -> Statistik
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
│   ├── excluded.json             <- von Hand ausgeblendete Praxen
│   ├── sent_log.json             <- alte Versandliste (aus der Zeit vor der Webapp)
│   └── archiv/                   <- letzte Sicherung vor großen Umbauten + ausgemusterte Einmal-Skripte
│
├── docs/                      <- Projektdokumente (nicht öffentlich, siehe .gitignore)
│   └── archiv/                   <- abgearbeitete Reviews/Audits/Briefings (nur noch als Nachweis)
├── design/                    <- Design-Rohmaterial (nicht öffentlich, siehe .gitignore)
├── deliverables/               <- fertige Exporte (xlsx/pdf/Videos)
│   └── flyer/                    <- Druck-PDFs; Bau-Skripte in flyer/quellen/
├── tests/                      <- pytest-Tests fürs Backend (siehe unten)
├── tools/                      <- Werkzeuge für Entwickler (Mutationstest)
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

python main.py                      # scrapt, analysiert, zeigt die Zahlen
python main.py --skip-scraper       # nur neu analysieren (results_raw.json existiert schon)
python main.py --skip-analyzer      # nur scrapen, ohne KI-Analyse (kein API-Key nötig)
python main.py --skip-scraper --neu-analyse-alt  # auch alte Ergebnisse ohne Inhalts-Hash neu analysieren (kostet API-Aufrufe)
python main.py --only-emails        # nur fehlende Emails nachrecherchieren
python main.py --stats              # nur Statistik ausgeben
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
– unabhängig davon, aus welchem Verzeichnis man ein Skript startet.

## Tests

```bash
python -m pytest tests/ -q                     # Backend (pytest)
python -m pytest tests/ --cov=backend         # mit Abdeckung (pip install pytest-cov)
python -m ruff check backend tests             # Linter (pip install ruff), Regeln in ruff.toml
cd webapp && npm test                           # Webapp (node --test)
```

Die Backend-Tests liegen in `tests/`, eine Testdatei pro Modul
(`test_scraper.py` für `scraper.py` usw.). Browser, DNS und KI sind dabei
Attrappen aus `tests/attrappen.py`: Sie schreiben mit, was der Code mit
ihnen macht (welche Seiten besucht wurden, welche Browser-Optionen gesetzt
sind). Die Tests prüfen also Verhalten, nicht den Quelltext. Kein Test geht
ins Netz. `tests/conftest.py` macht `backend/` importierbar und stellt die
Attrappen als Fixtures bereit.

Abdeckung (Stand 16.10.2026): Backend 93 % der Zeilen in diesem Repo,
Webapp-API ca. 90 %. Die Oberfläche (`webapp/app/`) ist nicht als Zahl
messbar, weil die Tests sie in einem simulierten Browser laden; sie wird
von den node-Tests und den Playwright-Browser-Tests geprüft.
Einzige Ausnahme beim Browser: je ein Test in `test_scraper.py` und
`test_umkreis_ausbau.py` lädt ein Beispiel-Profil in einen lokalen Chromium
(alle Netz-Anfragen blockiert) und wird übersprungen, wenn keiner
installiert ist.

### Wie gut sind die Tests?

Abdeckung allein sagt nur, welche Zeilen beim Testen laufen. Darum gibt es
zusätzlich einen **Mutationstest** (`tools/mutationstest.py`): Er baut in
einer Kopie des Projekts absichtlich kleine Fehler ein (`==` statt `!=`,
`and` statt `or`, `True` statt `False`, eine 1 statt einer 0 …) und prüft,
ob die Tests das merken. Je höher der Anteil, desto weniger "tote" Tests.

```bash
python tools/mutationstest.py backend/filters.py tests/test_filters.py
```

Stand 16.10.2026 (je bis zu 30 zufällige Mutationen pro Modul):

| Modul | erkannt | Modul | erkannt |
|---|---|---|---|
| analyse_regeln.py | 97 % | merge_hilfen.py | 100 % |
| analyzer.py | 93 % | dateihilfen.py | 100 % |
| filters.py | 90 % | umkreis_plan.py | 96 % |
| dedupe_bestand.py | 90 % | build_plz_tabelle.py | 92 % |
| browser_schutz.py | 90 % | analyse_ki.py | 88 % |
| scraper.py | 88 % | umkreis_abruf.py | 88 % |
| email_vorlagen.py | 88 % | umkreis_doku.py | 88 % |
| main.py | 89 % | build_webapp_chunks.py | 87 % |
| stats_export.py | 85 % | umkreis_ausbau.py | 84 % |
| email_suche.py | 80 % | | |

Die übrigen, nicht erkannten Mutationen habe ich einzeln angesehen: Meist
ändern sie nichts am Verhalten (z. B. `if __name__ == "__main__"` oder
eine Einstellung, die im Test keine Rolle spielt).

Beides sollte vor jedem Commit grün sein – ein Teil der Tests entstand direkt
aus echten, im Betrieb gefundenen Fehlern (siehe Docstrings/Commit-Messages
der jeweiligen Testdatei für den Hintergrund).

## Secrets

`.env` sowie alles unter `data/`
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
