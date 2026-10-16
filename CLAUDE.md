# Therapie-Mailer Projekt

## Ziel
Python-Pipeline, die Psychotherapie-Praxen von therapie.de und weiteren Registern sammelt, nach festen Regeln filtert und mit der Claude API (oder kostenlos per Regeln) bewertet. Zweiter Teil: die deployte Web-App `webapp/` (siehe `README.md` für den vollständigen Aufbau).

## Arbeitsweise ab jetzt (gilt für alles, Backend wie Webapp)

- **Struktur sauber halten**: neue Dateien an die bestehende Ordnerlogik anpassen (siehe `README.md`), keine losen Skripte/Daten im Root, keine Duplikate. Bevor etwas Neues entsteht: kurz prüfen, ob es nicht eigentlich in einen vorhandenen Ordner gehört.
- **Tests direkt mitschreiben, nicht nachträglich**: jede neue Funktion/jedes neue Feature kriegt beim Bauen einen Test dazu (`pytest` für `backend/`, `node --test` für `webapp/`). Vor jedem Commit müssen beide Suiten grün sein — kein "mach ich später".
- **Kleine, nachvollziehbare Commits** mit klaren deutschen Messages. Committen ist ok, **gepusht wird nur, wenn Marcel das ausdrücklich sagt** (webapp ist live, Auto-Deploy bei jedem Push).
- **Secrets bleiben Secrets**: `.env` nie ins Git-Repo, immer über `.gitignore` geprüft. Bei neuen Secrets: `.env.example`/Doku aktualisieren, nie den echten Wert committen.
- **Sicherheitsrelevante Änderungen** (Auth, Formulare, Datenzugriff, alles was Nutzerdaten anfasst) bekommen vor dem Commit einen kurzen Threat-Check: Wer könnte das wie missbrauchen? Reicht die Eingabevalidierung? Bei größeren Änderungen den `security-review`-Skill nutzen.
- **Dokumentation mitziehen**: README/CONTRIBUTING/Docstrings aktualisieren, wenn sich Struktur oder Verhalten ändert — nicht getrennt "irgendwann mal" nachpflegen.
- **Lieber einmal mehr nachfragen/vorsichtig sein** als stillschweigend Testdaten, Auth-Logik oder die Datenchunk-Prüfsummen in `webapp/api/data.js` anfassen.

## Projektstruktur (siehe README.md für Details)
```
therapie-mailer/
├── backend/            <- Python-Pipeline (scraper, analyzer, main.py, pfade.py)
├── data/               <- Scraping-/Analyse-Ergebnisse (gitignored)
├── docs/               <- Anforderungen, Security-Audit, Anleitung
├── deliverables/       <- fertige Exporte (xlsx/pdf)
├── tests/              <- pytest-Tests fürs Backend
├── requirements.txt
└── webapp/             <- DAS DEPLOYTE PRODUKT (eigenes Git-Repo, eigenes CONTRIBUTING.md)
```

## SCRAPER (backend/scraper.py)
- Nutzt Playwright (Python) um therapie.de zu scrapen
- Sucht pro Ort in `SUCHORTE` (Dortmund, Unna, Bönen) unter
  https://www.therapie.de/therapeutensuche/ergebnisse/?ort=<Ort>
- Geht durch ALLE Seiten der Suchergebnisse
- Für jeden Therapeuten wird das individuelle Profil geöffnet und extrahiert:
  - Name, Titel, Adresse, Telefon, Email (falls vorhanden)
  - Abrechnungsarten (GKV, PKV, Selbstzahler etc.)
  - Behandlungsschwerpunkte
  - Therapieverfahren
  - Therapieangebot (Einzel/Gruppe, Erwachsene/Kinder)
  - Freie Plätze / Wartezeiten
  - Persönliches Profil (Freitext)
  - Profil-URL
- Speichert alles in `data/results_raw.json`
- SSRF-Schutz beim Besuch von Praxis-Websites (`enrich_emails`): `ssrf_schutz_einrichten()` hängt vor der ersten
  Navigation einen Route-Handler an den Browser-Context, der JEDEN Request
  (auch Redirect-Ziele und Subressourcen) gegen `_ist_oeffentliche_http_url`
  prüft und nicht-öffentliche Ziele abbricht (Review #13).
  `_nach_navigation_erlaubt()` bleibt als zweite Absicherung.

## UMKREIS-AUSBAU (backend/umkreis_ausbau.py)
- Erweitert therapie.de Ort für Ort über Firecrawl (`FIRECRAWL_API_KEY` in
  `.env`), in Ringen um Dortmund (`UMKREIS_PLAN`, Ring 0 = Bestand aus
  scraper.py). Filter schon in der Such-URL (`SUCH_FILTER`: Kasse oder
  Kostenerstattung + Einzeltherapie Erwachsene), bekannte Profil-URLs
  kosten keinen Credit, Monatslimit (`FIRECRAWL_MONATSLIMIT`) wird nie
  überschritten, bei 403/429 von therapie.de sofort Stopp.
- Profilfelder liest `scraper.lies_profil()` (HTML per `page.set_content`,
  alle Requests blockiert) – es gibt nur EINE Auslese-Logik.
- Fortschritt: `data/umkreis_status.json`; lesbare Übersicht schreibt das
  Skript selbst nach `docs/UMKREIS_AUSBAU.md` (nur zwischen den
  AUTO-Markern, Notizen darunter bleiben erhalten).
- Neue Profile tragen `suchort` und `erfasst_ueber: "firecrawl"`. Danach
  `dedupe_bestand.py` → `analyzer.py` → `build_webapp_chunks.py`.

## FILTER (backend/filters.py) – läuft VOR der KI
Harte, nachprüfbare Regeln entscheiden zuerst, wer überhaupt in die Auswahl
kommt. Die KI entscheidet das ausdrücklich **nicht** mehr (früher über die
Felder `Relevant`, `Einzeltherapie_Erwachsene`, `Stadtteil_Priorität` – die
gibt es nicht mehr).

- Regel 1: muss Einzeltherapie für Erwachsene anbieten (fehlt das Feld im
  Profil: nur Warnung, kein Ausschluss).
- Regel 2: reine Kinder- und Jugendlichenpsychotherapeuten raus (Zulassung
  nur bis 21 Jahre).
- Regel 3: Heilpraktiker für Psychotherapie ohne Approbation raus, solange
  GKV-Abrechnung gefordert ist.
- "Approbation für Erwachsene" ist dreistufig (`_approbations_status()`,
  Review #10): `bestaetigt` nur über eine nicht verneinte Berufsbezeichnung
  (Psychologische/r bzw. Ärztliche/r Psychotherapeut/in, Facharzt für
  Psych...); ein allgemeines "Approbation"/"approbiert" ohne Angabe wofür
  ist nur `unklar` (Profil bleibt drin, aber mit Prüf-Warnung). Verneinte
  Erwähnungen ("ohne Approbation"), reine KJP-Approbationen ("Approbation
  als Kinder- und Jugendlichenpsychotherapeutin") und "approbierte
  Kolleginnen" zählen gar nicht.
- `kategorie()` setzt zusätzlich `gkv_art`: `kassensitz`, `kostenerstattung`
  oder `privat`.
- `filtere()` verändert die übergebenen Dicts **in-place** (ergänzt
  `filter_warnungen`, `gkv_art`, bei Ausschluss `ausschluss_grund`) und gibt
  `(behalten, ausgeschlossen)` zurück.
- Die Ausgeschlossenen landen mit Begründung in `data/ausgeschlossen.json`.

## ANALYZER (backend/analyzer.py)
- Liest `data/results_raw.json`
- Schritt 1: `filters.filtere()` (siehe oben). Schritt 2: KI-Analyse nur für
  die verbliebenen Profile. Bereits analysierte Profile werden übersprungen
  (Resume über `profil_url` UND `inhalt_hash`, Review #11), manuell
  ausgeblendete (`data/excluded.json`) fliegen raus.
- Aktualität (Review #11): jedes Ergebnis (auch Einträge in
  `data/uebersprungen.json`) speichert `inhalt_hash` (sha256 über
  `HASH_FELDER` des Rohprofils, Seitenaufruf-Zähler ignoriert) und
  `analysiert_am`. Geänderter Inhalt → neu analysieren, altes Ergebnis wird
  ersetzt. Alte Ergebnisse ohne Hash werden aus Kostengründen NICHT neu
  analysiert, außer mit `NEU_ANALYSE_ALT=1` bzw. `--neu-analyse-alt`.
- `build_webapp_chunks.py` übernimmt aus dem Live-Stand weiter
  id/km/anrede/therapieform, `aufnahmestopp`/`aufnahmestopp_zitat` aber nur
  noch bei `aufnahmestopp_quelle == "manuell"`; sonst frisch aus dem
  Rohprofil.
- Modell: `CLAUDE_MODEL` aus der Umgebung, Standard `claude-sonnet-4-5`.
- Profile ganz ohne verwertbare Angaben (keine Abrechnungsarten, kein
  Therapieangebot, keine Schwerpunkte, kein Profiltext, typisch fuer reine
  Registerdaten) gehen NICHT an die KI (`zu_wenig_angaben()`, 3.10.2026) und
  werden auch nicht in `uebersprungen.json` gemerkt: sobald eine andere Quelle
  sie ergaenzt, laufen sie beim naechsten Lauf normal durch.
- Steht die Kasse schon ueber die Abrechnungsarten fest (Register/Kassensitz)
  und hat das Profil weder eigenen Text noch eine Angabe zu freien Plaetzen,
  setzt `analyse_ohne_ki()` (4.10.2026) das Ergebnis direkt (GKV ja, Plaetze
  unklar) statt die KI zu fragen -- deren Antwort war in diesen Faellen
  immer genau das.
- `--ohne-ki` bzw. `OHNE_KI=1` (4.10.2026): gar keine API-Aufrufe, kein
  API-Key noetig. `analyse_per_regel()` bewertet Kasse und freie Plaetze per
  Wortsuche (Verneinung wie "keine freien Plaetze"/"Aufnahmestopp" gewinnt).
  Kostenloser Standardweg, solange kein API-Guthaben da ist.
- Für jeden Therapeuten wird das Profil an die Claude API geschickt.
- Claude liefert genau diese drei Felder (`ERLAUBTE_ANALYSE_FELDER` in
  `analyzer.py`) – alles andere aus der Antwort wird verworfen, damit ein
  präparierter Profiltext per Prompt Injection keine Originaldaten wie
  `email` oder `name` überschreiben kann:
  1. GKV_akzeptiert: true/false/"unklar"
     - Auch implizit aus Text lesen z.B. "gesetzlich Versicherte willkommen"
  2. Freie_Plaetze: true/false/"unklar"
  3. Notiz: kurze Begründung warum empfohlen oder nicht
- Email_generiert schreibt die KI seit 26.8.2026 NICHT mehr selbst (siehe
  `backend/email_vorlagen.py`). Stattdessen zieht `analyzer.main()` pro
  Profil zufällig eine von 40 vorformulierten Vorlagen und füllt sie lokal
  mit `anrede_aus_name()`/`therapieform_aus_profil()`. Grund: bei vielen
  Praxen fällt eine identische Serienmail auf, und ein präparierter
  Profiltext kann den Email-Inhalt so gar nicht mehr beeinflussen (statt
  nur per Whitelist blockiert zu werden). Alle 40 Vorlagen fragen explizit
  nach der ungefähren Wartezeit statt allgemein nach Kapazitäten/Warteliste
  (Hinweis eines Psychotherapeuten, 14.8.2026: Kassen wie die TK akzeptieren
  "nicht erreicht" nicht als Nachweis). `anrede`/`therapieform` werden dabei
  direkt mit in `results_analyzed.json` gespeichert, nicht mehr nachträglich
  per Regex aus dem Email-Text zurückgewonnen (siehe
  `build_webapp_chunks.py`).
- KLARSTELLUNG (26.8.2026): kurzzeitig wurde vermutet, die live deployte
  Webapp würde `Email_generiert` ungefiltert an alle eingeloggten Personen
  ausliefern (mit festem Namen/fester Situation). Das war ein Irrtum: die Webapp
  hat dieses Feld nie zum Versenden benutzt. Der tatsächlich gesendete Text
  wird komplett unabhängig client-seitig über `buildEmail()` in
  `webapp/app/app-utils.js` gebaut, aus echten, im Onboarding-Wizard PRO
  PERSON erfassten Werten (`state.name`, `state.themen`) — das war schon
  vor diesem Datum so. `Email_generiert`/`anrede`/`therapieform` in
  `results_analyzed.json` sind reine Backend-Referenzwerte (siehe
  Modul-Docstring in `backend/email_vorlagen.py` für Details), nicht der
  Text, den echte Nutzer:innen verschicken. Die 40 Vorlagen und die
  Supabase-Spalten `profiles.eigener_name`/`eigene_situation` (Migration
  `profiles_eigener_name_und_situation`) sind aktuell NICHT an die Webapp
  angeschlossen. Tatsächlich fehlender Teil aus dem Hinweis vom 14.8.2026, der jetzt
  im echten Sende-Flow steckt: `EMAIL_BITTE` in `webapp/app/app-utils.js`
  fragt seit 26.8.2026 konkret nach der Wartezeit statt allgemein nach
  Kapazitäten/Warteliste. Vor dem tatsächlichen Versand kann der Text in
  der Webapp wie gehabt manuell angepasst werden.

- Wer in die finale Liste kommt, entscheiden `filters.filtere()` (siehe oben)
  UND `GKV_akzeptiert` true/unklar aus der KI-Analyse zusammen – nicht mehr
  `Relevant`/`Einzeltherapie_Erwachsene` (die Felder liefert die KI nicht
  mehr, siehe `ERLAUBTE_ANALYSE_FELDER`).
- Speichert in `data/results_analyzed.json`

## MAIN (backend/main.py)
- Startbefehl: Scraper, danach Analyzer, danach Statistik.
- Schalter: `--skip-scraper`, `--skip-analyzer`, `--only-emails`, `--stats`.
- Der frühere lokale Server mit Vorschau (`backend/frontend/`) und der
  Gmail-Versand (`mailer.py`, `credentials.json`, `token.json`) sind seit
  16.10.2026 entfernt. Mails verschickt nur noch die Webapp (über Resend).

## REQUIREMENTS.TXT
Feste Versionen, siehe Kommentar in `requirements.txt`.

## Wichtige Hinweise
- Fehlerbehandlung überall (Seiten die nicht laden, fehlende Felder etc.)
- Rate limiting beim Scrapen: 4 bis 6,5 Sekunden zwischen Requests (`DELAY_MIN`/`DELAY_MAX` in scraper.py), bei 403/429/Captcha sofort Stopp
- Fortschrittsanzeige im Terminal während des Scrapens
- ANTHROPIC_API_KEY als Umgebungsvariable lesen
