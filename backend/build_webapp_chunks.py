"""
Baut aus data/results_analyzed.json den Datensatz, den die Webapp ausliefert
(webapp/api/data-chunks/chunkNNN.b64 + die zugehoerigen SHA-256-Konstanten in
webapp/api/data.js). Siehe webapp/CONTRIBUTING.md Abschnitt 2 fuer die
Chunk-Pipeline und WARUM sie so aussieht -- dieses Skript ist der fehlende
Baustein, der die *.b64-Dateien und Pruefsummen dort ueberhaupt erzeugt.

Warum dieses Skript existiert (Kontext, 20.8.2026): der urspruengliche
Build-Vorgang war offenbar ein Wegwerf-Skript, das nie ins Repo aufgenommen
wurde -- beim Versuch, nach dem Import einer neuen Zusatzquelle neue
Therapeuten in die Webapp zu bekommen, gab es dafuer keine Grundlage mehr.
Dieses Skript wurde aus dem BEOBACHTBAREN Verhalten der Live-Daten
rekonstruiert (siehe Funktionsdocstrings unten fuer die jeweilige Herleitung)
und bleibt bewusst im Repo, damit das nicht nochmal passiert.

Schema-Unterschiede analysiert -> Webapp (siehe TRANSFORM_FELDER unten):
  abrechnungsarten          -> abrechnung
  behandlungsschwerpunkte   -> schwerpunkte
  Freie_Plaetze              -> freie_plaetze
Zusaetzliche Felder, die es in results_analyzed.json NICHT gibt und die
dieses Skript selbst herleitet:
  id             fortlaufend, MUSS ueber Rebuilds stabil bleiben (siehe
                 baue_datensatz() Docstring -- app/app.js speichert pro
                 Nutzer:in lokal Zustand wie state.contacted[t.id],
                 state.hidden etc.; eine neu vergebene id wuerde bereits
                 getrackten Kontakt/Absagen/Nachweisen einer VOELLIG
                 ANDEREN Praxis zuordnen).
  km             Luftlinie zur Postleitzahl 44319 (Dortmund-Wickede/Brackel,
                 der Referenzpunkt aus dem urspruenglichen Scraper-Aufruf,
                 siehe scraper.py LISTE_URL). Neuzugaenge seit 4.10.2026 ueber
                 die Mitte ihres PLZ-Gebiets (km_aus_plz), aeltere Werte
                 adressgenau aus dem Geocode-Cache. Die Webapp zeigt km nur
                 noch als Fallback, sonst rechnet sie ab der PLZ der Nutzerin.
  anrede         wird NICHT neu generiert, sondern aus dem bereits von
                 analyzer.py erzeugten Email_generiert-Text extrahiert
                 ("Guten Tag X,", siehe extrahiere_anrede()) -- an 474 von
                 474 bereits live vorhandenen Eintraegen mit 98.7% exakter
                 Uebereinstimmung verifiziert.
  therapieform   ebenso aus Email_generiert extrahiert ("Falls Sie X
                 anbieten,", siehe extrahiere_therapieform()), mit
                 "Einzeltherapie" als Standardwert, wenn der Satz fehlt --
                 exakt der gleiche Standardwert, den app/app.js client-
                 seitig sowieso verwendet (`t.therapieform || "Einzeltherapie"`).
  aufnahmestopp  kommt seit Review #11 IMMER frisch aus dem Rohprofil (der
                 Scraper erkennt es per _finde_aufnahmestopp() im
                 Profiltext und speichert Zitat mit), siehe
                 waehle_aufnahmestopp(). Aus dem Live-Stand uebernommen wird
                 es NUR, wenn es dort ausdruecklich als manuelle Korrektur
                 markiert ist (aufnahmestopp_quelle == "manuell"). Frueher
                 wurde der Live-Wert blind uebernommen -- ein aufgehobener
                 oder neu eingetragener Aufnahmestopp kam so nie in der
                 Webapp an. Im Frontend ist das Feld nur noch Badge bzw.
                 Sortierkriterium der Telefon-Ansicht, kein Ausschluss.

WICHTIGES SICHERHEITSNETZ: fuer Eintraege, die schon in den aktuell live
ausgelieferten Daten stehen (Abgleich ueber profil_url), werden id/km/
anrede/therapieform NICHT neu berechnet, sondern unveraendert
uebernommen -- das vermeidet unnoetige Diffs und schuetzt vor genau dem
Risiko oben (id-Verschiebung). Nur echte Neuzugaenge bekommen frisch
berechnete Werte. Bei den "rohen" Inhaltsfeldern (Adresse/Telefon/Email/...)
gilt zusaetzlich: ein frischer, aber leerer Wert ueberschreibt NIE einen
vorhandenen Live-Wert (siehe bevorzuge_frisch()) -- das faengt ab, dass der
aktuelle Scraper z.B. keine telefonsprechstunde-Daten mehr liefert, obwohl
169 der 475 Live-Eintraege das Feld haben.

Aufruf (aus dem backend/-Ordner):
  python build_webapp_chunks.py
"""
import base64
import gzip
import hashlib
import json
import re
from math import asin, cos, radians, sin, sqrt

import pfade
from dateihilfen import json_sicher_laden
from merge_hilfen import ist_praxis_website

WEBAPP_API_DIR = pfade.PROJEKT_ROOT / "webapp" / "api"
CHUNKS_DIR = WEBAPP_API_DIR / "data-chunks"
ANZAHL_CHUNKS = 48

# PLZ 44319 (Dortmund-Wickede/Brackel) -- Referenzpunkt fuer km, siehe
# Modul-Docstring. Zentroid laut Nominatim/OpenStreetMap.
REF_LAT, REF_LON = 51.5371637, 7.5989724

ANREDE_RE = re.compile(r"^Guten Tag (.+?),", re.S)
THERAPIEFORM_RE = re.compile(r"Falls Sie (.+?) anbieten,", re.S)
STANDARD_THERAPIEFORM = "Einzeltherapie"

# PLZ -> [Breite, Laenge], dieselbe Tabelle, mit der die Webapp Entfernungen
# ab der PLZ der Nutzerin rechnet (siehe build_plz_tabelle.py).
PLZ_TABELLE = pfade.PROJEKT_ROOT / "webapp" / "app" / "assets" / "plz-koordinaten.json"
PLZ_RE = re.compile(r"\b(\d{5})\b")


def extrahiere_anrede(email_text):
    """Liest die Anrede aus dem von analyzer.py generierten Email-Text
    ("Guten Tag X,..."). Leerer String, wenn das Muster fehlt -- app/app.js
    faellt dann selbst auf "sehr geehrte Damen und Herren" zurueck."""
    m = ANREDE_RE.search(email_text or "")
    return m.group(1).strip() if m else ""


def extrahiere_therapieform(email_text):
    """Liest die genannte Therapieform aus dem Email-Text ("Falls Sie X
    anbieten,..."). Faellt auf denselben Standardwert zurueck, den
    app/app.js clientseitig sowieso verwendet, wenn das Feld fehlt."""
    m = THERAPIEFORM_RE.search(email_text or "")
    return m.group(1).strip() if m else STANDARD_THERAPIEFORM


def haversine_km(lat1, lon1, lat2, lon2):
    """Luftlinien-Entfernung in km zwischen zwei Koordinaten."""
    erdradius_km = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * erdradius_km * asin(sqrt(a))


def km_aus_plz(adresse, tabelle):
    """Luftlinie von PLZ 44319 zur Mitte des PLZ-Gebiets der Adresse, auf eine
    Nachkommastelle gerundet. None ohne (bekannte) PLZ -- die Webapp zeigt
    dann keine Distanz an, das ist ein vorgesehener Fall.

    Seit 4.10.2026 statt Nominatim-Geocoding pro Adresse: bei ~2.000
    Neuzugaengen haette das wegen des Ratenlimits fast eine Stunde gedauert,
    und die Webapp rechnet die angezeigte Entfernung ohnehin ueber dieselbe
    PLZ-Tabelle (ab der PLZ der Nutzerin). km ist nur noch der Fallback."""
    treffer = PLZ_RE.findall(adresse or "")
    for plz in reversed(treffer):  # die PLZ steht vor dem Ort, also hinten
        if plz in tabelle:
            lat, lon = tabelle[plz]
            return round(haversine_km(REF_LAT, REF_LON, lat, lon), 1)
    return None


def naechste_ids(vorhandene_ids, anzahl):
    start = max(vorhandene_ids, default=0) + 1
    return list(range(start, start + anzahl))


def bevorzuge_frisch(frischer_wert, alter_wert):
    """Nimmt den frischen Wert -- ausser er ist leer (None/""/[]/{}), dann
    wird der alte (Live-)Wert beibehalten. Eine Datenaktualisierung darf nie
    etwas entfernen, was vorher schon da war (siehe Modul-Docstring,
    telefonsprechstunde-Beispiel)."""
    if frischer_wert in (None, "", [], {}):
        return alter_wert
    return frischer_wert


def bevorzuge_frisch_email(analysiert, alter_wert):
    """Wie bevorzuge_frisch(), aber mit einer Ausnahme: ist
    `email_entfernt_grund` gesetzt (siehe analyzer.py/manuelle Korrektur bei
    falsch zugeordneten Emails, 26.8.2026), war das Leeren der Email
    ABSICHTLICH -- dann NICHT auf den alten Live-Wert zurueckfallen, sonst
    macht das Sicherheitsnetz genau die Korrektur rueckgaengig, die es
    eigentlich transportieren soll (siehe Commit zur Email-
    Korrektur vom 26.8.2026: bevorzuge_frisch() hat den falschen Live-Wert beim Rebuild
    wieder eingesetzt, obwohl results_analyzed.json schon korrigiert war)."""
    if analysiert.get("email_entfernt_grund"):
        return analysiert.get("email") or ""
    return bevorzuge_frisch(analysiert.get("email"), alter_wert)


def lade_live_daten():
    """Entpackt die aktuell in webapp/api/data-chunks/ liegenden Chunks
    zurueck zu der Liste, die die Webapp gerade wirklich ausliefert --
    Grundlage fuer den Stabilitaets-Abgleich (id/km/anrede/therapieform),
    siehe Modul-Docstring."""
    chunk_dateien = sorted(CHUNKS_DIR.glob("chunk*.b64"))
    if not chunk_dateien:
        return []
    b64 = "".join(p.read_text(encoding="utf-8") for p in chunk_dateien)
    roh = gzip.decompress(base64.b64decode(b64))
    return json.loads(roh)


AUFNAHMESTOPP_MANUELL = "manuell"


def waehle_aufnahmestopp(analysiert, live=None):
    """Liefert (aufnahmestopp, zitat, quelle) fuer den Webapp-Datensatz.

    Reihenfolge:
      1. Live-Datensatz mit aufnahmestopp_quelle == "manuell": eine von Hand
         gesetzte Korrektur -- bleibt ueber Rebuilds erhalten.
      2. Frischer Datensatz mit aufnahmestopp_quelle == "manuell" (Korrektur
         direkt in results_analyzed.json eingetragen).
      3. Sonst: frischer Wert aus dem Rohprofil (Scraper-Erkennung), fehlt
         das Feld (Quelle ohne Aufnahmestopp-Erkennung) -> False.
    quelle ist nur bei manuellen Korrekturen gesetzt, sonst None (dann wird
    kein aufnahmestopp_quelle-Feld ausgeliefert, Schema bleibt wie bisher).
    """
    live = live or {}
    for kandidat in (live, analysiert):
        if kandidat.get("aufnahmestopp_quelle") == AUFNAHMESTOPP_MANUELL:
            stopp = bool(kandidat.get("aufnahmestopp"))
            return stopp, (kandidat.get("aufnahmestopp_zitat") or "") if stopp else "", AUFNAHMESTOPP_MANUELL
    stopp = bool(analysiert.get("aufnahmestopp"))
    zitat = (analysiert.get("aufnahmestopp_zitat") or "") if stopp else ""
    return stopp, zitat, None


def baue_datensatz(analysiert, live=None):
    """Transformiert einen results_analyzed.json-Eintrag ins Webapp-Schema.

    `live` ist der bereits live ausgelieferte Datensatz mit derselben
    profil_url (falls vorhanden). Ist er gesetzt, werden id/km/anrede/
    therapieform UNVERAENDERT von dort uebernommen (siehe Modul-Docstring,
    Sicherheitsnetz) -- alles andere kommt frisch aus `analysiert`, faellt
    aber bei leeren Werten auf `live` zurueck (bevorzuge_frisch()).
    aufnahmestopp/aufnahmestopp_zitat: siehe waehle_aufnahmestopp() (nur
    manuelle Korrekturen aus dem Live-Stand bleiben erhalten).

    Ist `live` None (echter Neuzugang), werden id/km/anrede/therapieform
    frisch berechnet -- id NICHT hier (siehe naechste_ids(), das passiert
    zentral in main(), weil es alle Neuzugaenge gleichzeitig kennen muss).
    """
    live = live or {}
    frisch_fp = analysiert.get("Freie_Plaetze")
    freie_plaetze = frisch_fp if frisch_fp is not None else live.get("freie_plaetze", "unklar")

    datensatz = {
        "name": bevorzuge_frisch(analysiert.get("name"), live.get("name")) or "",
        "adresse": bevorzuge_frisch(analysiert.get("adresse"), live.get("adresse")) or "",
        "telefon": bevorzuge_frisch(analysiert.get("telefon"), live.get("telefon")) or "",
        "email": bevorzuge_frisch_email(analysiert, live.get("email")) or "",
        # Kartenlinks nie als Website ausliefern -- auch nicht als Fallback
        # aus dem Live-Stand (siehe merge_hilfen.ist_praxis_website).
        "website": next((w for w in (analysiert.get("website"), live.get("website"))
                         if ist_praxis_website(w)), ""),
        "profil_url": analysiert.get("profil_url") or live.get("profil_url") or "",
        "abrechnung": bevorzuge_frisch(analysiert.get("abrechnungsarten"), live.get("abrechnung")) or [],
        "schwerpunkte": bevorzuge_frisch(analysiert.get("behandlungsschwerpunkte"), live.get("schwerpunkte")) or [],
        "freie_plaetze": freie_plaetze,
        "scraped_at": bevorzuge_frisch(analysiert.get("scraped_at"), live.get("scraped_at")) or "",
    }
    sprechstunde = bevorzuge_frisch(analysiert.get("telefonsprechstunde"), live.get("telefonsprechstunde"))
    if sprechstunde:
        datensatz["telefonsprechstunde"] = sprechstunde

    if live:
        datensatz["id"] = live.get("id")
        datensatz["km"] = live.get("km")
        datensatz["anrede"] = live.get("anrede", "")
        datensatz["therapieform"] = live.get("therapieform", STANDARD_THERAPIEFORM)
    else:
        # Seit der Umstellung auf email_vorlagen.py (siehe dortigen
        # Modul-Docstring) liefert analyzer.py anrede/therapieform direkt
        # mit, weil die Email nicht mehr per KI geschrieben wird und die
        # Regex-Muster unten nur noch auf die eine alte KI-Formulierung
        # passen wuerden -- die 40 neuen Vorlagen haben unterschiedliche
        # Formulierungen. Fallback auf die alte Extraktion bleibt fuer
        # Eintraege stehen, die vor dieser Umstellung analysiert wurden und
        # deshalb noch kein eigenes anrede/therapieform-Feld haben.
        email_text = analysiert.get("Email_generiert") or ""
        datensatz["anrede"] = analysiert.get("anrede") or extrahiere_anrede(email_text)
        datensatz["therapieform"] = analysiert.get("therapieform") or extrahiere_therapieform(email_text)
        # km wird in main() nachtraeglich per km_aus_plz() gesetzt.
        datensatz["km"] = None
        # id wird zentral in main() ueber naechste_ids() vergeben.
        datensatz["id"] = None

    stopp, zitat, quelle = waehle_aufnahmestopp(analysiert, live)
    datensatz["aufnahmestopp"] = stopp
    datensatz["aufnahmestopp_zitat"] = zitat
    if quelle:
        datensatz["aufnahmestopp_quelle"] = quelle

    return datensatz


def teile_in_chunks(text, anzahl):
    laenge = len(text)
    stuecke = []
    for i in range(anzahl):
        start = i * laenge // anzahl
        ende = (i + 1) * laenge // anzahl
        stuecke.append(text[start:ende])
    return stuecke


def main():
    analysiert_liste = json_sicher_laden(pfade.RESULTS_ANALYZED, [])
    if not analysiert_liste:
        print("Keine results_analyzed.json gefunden -- Abbruch.")
        return

    live_liste = lade_live_daten()
    live_index = {d["profil_url"]: d for d in live_liste if d.get("profil_url")}
    analysiert_index = {a["profil_url"]: a for a in analysiert_liste if a.get("profil_url")}

    print(f"results_analyzed.json: {len(analysiert_liste)} Eintraege")
    print(f"aktuell live: {len(live_liste)} Eintraege")

    # Reihenfolge der bisherigen Live-Liste beibehalten (nur aktualisieren,
    # nicht neu sortieren) -- wer nicht mehr in results_analyzed.json
    # vorkommt (z.B. durch neuen Filterlauf ausgeschlossen), faellt raus.
    aktualisierte = []
    for live_eintrag in live_liste:
        url = live_eintrag.get("profil_url")
        analysiert_eintrag = analysiert_index.get(url)
        if analysiert_eintrag is None:
            continue
        aktualisierte.append(baue_datensatz(analysiert_eintrag, live_eintrag))

    neue_analysiert = [a for a in analysiert_liste if a.get("profil_url") not in live_index]
    neue_datensaetze = [baue_datensatz(a, live=None) for a in neue_analysiert]

    weggefallen = len(live_liste) - len(aktualisierte)
    print(f"{weggefallen} Eintraege nicht mehr in results_analyzed.json (fallen raus).")
    print(f"{len(neue_datensaetze)} echte Neuzugaenge.\n")

    if neue_datensaetze:
        # Fruehere, per Nominatim adressgenau ermittelte Werte (Cache) haben
        # Vorrang, alles andere kommt aus der PLZ-Tabelle (siehe km_aus_plz).
        cache = json_sicher_laden(pfade.GEOCODE_CACHE, {})
        tabelle = json_sicher_laden(PLZ_TABELLE, {})
        vorhandene_ids = [d["id"] for d in aktualisierte if d.get("id") is not None]
        ids = naechste_ids(vorhandene_ids, len(neue_datensaetze))
        for datensatz, neue_id in zip(neue_datensaetze, ids, strict=True):
            datensatz["id"] = neue_id
            adresse = datensatz["adresse"]
            km = cache[adresse] if cache.get(adresse) is not None else km_aus_plz(adresse, tabelle)
            datensatz["km"] = km
        ohne_km = sum(1 for d in neue_datensaetze if d["km"] is None)
        print(f"  {len(neue_datensaetze)} Neuzugaenge mit id und km versehen ({ohne_km} ohne bekannte PLZ).")

    gesamt = aktualisierte + neue_datensaetze
    print(f"\nGesamt: {len(gesamt)} Eintraege fuer die Webapp.")

    roh_json = json.dumps(gesamt, ensure_ascii=False, separators=(",", ":"))
    komprimiert = gzip.compress(roh_json.encode("utf-8"))
    b64 = base64.b64encode(komprimiert).decode("ascii")

    gesamt_hash = hashlib.sha256(b64.encode("ascii")).hexdigest()
    stuecke = teile_in_chunks(b64, ANZAHL_CHUNKS)
    chunk_hashes = [hashlib.sha256(stueck.encode("ascii")).hexdigest() for stueck in stuecke]

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    # Alte Chunk-Dateien erst raeumen, falls die Anzahl sich mal aendert.
    for alte_datei in CHUNKS_DIR.glob("chunk*.b64"):
        alte_datei.unlink()
    for i, stueck in enumerate(stuecke):
        (CHUNKS_DIR / f"chunk{i:03d}.b64").write_text(stueck, encoding="utf-8")

    print(f"\n{ANZAHL_CHUNKS} Chunk-Dateien geschrieben nach {CHUNKS_DIR}")
    print(f"\nEXPECTED_SHA256 = \"{gesamt_hash}\"")
    print("EXPECTED_CHUNK_SHA256 muss manuell in webapp/api/data.js eingetragen werden:")
    print(json.dumps(chunk_hashes, indent=2))

    (pfade.DATA_DIR / "webapp_chunk_hashes.json").write_text(
        json.dumps({"gesamt": gesamt_hash, "chunks": chunk_hashes}, indent=2),
        encoding="utf-8",
    )
    print(f"\nHashes zusaetzlich gespeichert in {pfade.DATA_DIR / 'webapp_chunk_hashes.json'}")


if __name__ == "__main__":
    main()
