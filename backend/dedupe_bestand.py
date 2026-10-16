"""
Einmaliges Aufraeum-Skript: fasst Dubletten zusammen, die durch die Pipeline
gerutscht sind, weil dedup_schluessel() (Name + Adresse) sie nicht als
dieselbe Person erkannt hat.

Zwei Ausloeser bisher:
1. (26.8.2026) Eine Zusatzquelle liefert Namen mit Anrede ("Herr Max
   Mustermann"), die alte Titel-Regex kannte nur akademische Titel --
   dedup_schluessel() griff deshalb nie zwischen so einem Eintrag und
   derselben Person aus einer anderen Quelle. 88 Therapeuten standen dadurch
   doppelt in results_raw.json und results_analyzed.json.
2. (23.9.2026, Nutzer-Meldungen zu zwei Praxen) Quellen
   schreiben Strassen unterschiedlich ab ("Str." vs. "Straße") oder haengen
   einen Stadtteil an ("Dortmund-Husen") -- gefixt in
   merge_hilfen.normalisiere_adresse(). Bei einer der beiden weicht die Adresse
   sogar komplett ab (zwei unterschiedliche im System hinterlegte
   Anschriften), Telefon UND Email sind aber identisch -- dafuer gruppiert
   _gruppiere() unten zusaetzlich ueber (Name, Telefon) und (Name, Email).

Ein Regex-/Logik-Fix allein verhindert nur KUENFTIGE Dubletten (beim
naechsten merge_*.py-Lauf) -- er raeumt nicht rueckwirkend auf, weil merge()
nur beim Einfuegen NEUER Zusatzeintraege prueft, nicht die schon vorhandene
Rohdatei gegen sich selbst. Dieses Skript holt das jeweils einmalig nach.

Vorgehen pro Dubletten-Gruppe (gleicher normalisierter Name + Adresse, ODER
gleicher normalisierter Name + Telefon, ODER gleicher normalisierter Name +
Email -- siehe _gruppiere()):
- Bevorzugter Eintrag ("primary"): wer schon in sent_log.json steht, bleibt
  IMMER primary (sonst wuerde main.py ihn faelschlich wieder als "offen"
  anzeigen und Marcel koennte doppelt anschreiben). Sonst gewinnt der
  "reichste" Eintrag (Email vorhanden zaehlt am meisten, dann Laenge von
  Freitext/Schwerpunkten).
- Fehlende Felder von primary werden aus den anderen Gruppenmitgliedern
  aufgefuellt (Listenfelder wie behandlungsschwerpunkte werden vereinigt).
- Wenn die Gruppe MEHRERE unterschiedliche Email-Adressen enthaelt (nicht
  nur "eine hat, eine nicht"), wird das NICHT stillschweigend aufgeloest --
  primary behaelt seine eigene Email, die Alternative(n) landen als Hinweis
  in filter_warnungen, damit das sichtbar bleibt und manuell geprueft werden
  kann (siehe CLAUDE.md: "Lieber einmal mehr nachfragen/vorsichtig sein").
- Dieselbe Entscheidung (welche URL bleibt) wird auf results_raw.json UND
  results_analyzed.json angewendet, damit beide Dateien konsistent bleiben.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dateihilfen import json_atomar_schreiben, json_sicher_laden
from merge_hilfen import dedup_schluessel, normalisiere_name, normalisiere_telefon
from pfade import RESULTS_ANALYZED, RESULTS_RAW, SENT_LOG

# Felder, bei denen "fehlend auffuellen" eine Vereinigung statt eines
# einfachen Ersetzens bedeutet.
_LISTEN_FELDER = (
    "abrechnungsarten",
    "behandlungsschwerpunkte",
    "therapieverfahren",
    "therapieangebot",
    "filter_warnungen",
)


def _score(eintrag):
    """Je hoeher, desto 'reicher' der Datensatz -- entscheidet, welcher
    Eintrag einer Dubletten-Gruppe als primary gewaehlt wird, wenn keiner
    davon schon versendet wurde."""
    s = 0
    if (eintrag.get("email") or "").strip():
        s += 1000
    s += len(eintrag.get("behandlungsschwerpunkte") or []) * 10
    s += len(eintrag.get("persoenliches_profil") or "")
    s += len(eintrag.get("volltext") or "")
    if eintrag.get("freie_plaetze"):
        s += 5
    return s


def _waehle_primary(gruppe, gesendete_urls, analysierte_urls=frozenset()):
    """Reihenfolge: schon angeschrieben > schon analysiert (= steht in der
    Webapp, hat dort eine feste id, an der Nutzer-Zustand haengt) > reichster
    Eintrag. Ohne die mittlere Stufe koennte der Rohdaten-Durchlauf (siehe
    main()) einen nie analysierten Registereintrag zum primary machen und den
    analysierten -- samt seiner Webapp-id -- entfernen."""
    for bevorzugt in (gesendete_urls, analysierte_urls):
        kandidaten = [e for e in gruppe if e.get("profil_url") in bevorzugt]
        if kandidaten:
            return max(kandidaten, key=_score)
    return max(gruppe, key=_score)


def _email_varianten(gruppe):
    """dict: lowercase-Email -> Liste der Eintraege, die sie tragen. Nur
    nicht-leere Emails."""
    varianten = {}
    for e in gruppe:
        em = (e.get("email") or "").strip()
        if em:
            varianten.setdefault(em.lower(), []).append(e)
    return varianten


class _UnionFind:
    """Minimalistische Union-Find-Struktur (Pfadkompression, kein Rang noetig
    bei diesen Datenmengen) -- verbindet Eintraege, die ueber MINDESTENS
    eines der Signale in _gruppiere() zusammengehoeren, auch transitiv (wenn
    A mit B ueber die Adresse zusammenhaengt und B mit C ueber das Telefon,
    landen A, B und C in derselben Gruppe)."""

    def __init__(self, n):
        self.eltern = list(range(n))

    def find(self, i):
        while self.eltern[i] != i:
            self.eltern[i] = self.eltern[self.eltern[i]]
            i = self.eltern[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.eltern[ra] = rb


def _gruppiere(analysierte_eintraege):
    """Gruppiert per Union-Find ueber mehrere Signale: (Name, Adresse) wie
    bisher ueber dedup_schluessel(), zusaetzlich (Name, Telefon) und (Name,
    Email) fuer Faelle, in denen die Adresse abweicht, Telefon oder Email
    aber exakt uebereinstimmen (Nutzer-Meldung 23.9.2026: zwei im
    System hinterlegte Adressen, aber identische Telefonnummer UND Email).

    Bewusst nur fuer diesen retroaktiven Cleanup, nicht fuer den laufenden
    merge() in merge_hilfen.py: dort soll der Abgleich konservativ bleiben,
    damit ein unbeaufsichtigter Scraper-Lauf nicht faelschlich zwei
    verschiedene Personen zusammenlegt, nur weil sie zufaellig dieselbe
    Sammel-Telefonnummer einer Praxis teilen. Hier ist das Risiko klein,
    weil zusaetzlich der normalisierte NAME exakt uebereinstimmen muss --
    zwei verschiedene Personen mit identischem Namen UND identischem
    Telefon/Email in derselben Praxis waeren ein Zufall, der bei den
    bisherigen Datenmengen nicht aufgetreten ist."""
    eintraege = list(analysierte_eintraege)
    n = len(eintraege)
    uf = _UnionFind(n)

    def _verbinde(index_dict, schluessel, i):
        for j in index_dict.get(schluessel, []):
            uf.union(i, j)
        index_dict.setdefault(schluessel, []).append(i)

    adress_index, telefon_index, email_index = {}, {}, {}
    for i, e in enumerate(eintraege):
        schluessel = dedup_schluessel(e)
        if schluessel is not None:
            _verbinde(adress_index, schluessel, i)

        name_norm = normalisiere_name(e.get("name"))
        if name_norm:
            tel_norm = normalisiere_telefon(e.get("telefon"))
            if tel_norm:
                _verbinde(telefon_index, (name_norm, tel_norm), i)
            email_norm = (e.get("email") or "").strip().lower()
            if email_norm:
                _verbinde(email_index, (name_norm, email_norm), i)

    gruppen = {}
    for i in range(n):
        gruppen.setdefault(uf.find(i), []).append(eintraege[i])
    return list(gruppen.values())


def entscheide(analysierte_eintraege, gesendete_urls, analysierte_urls=frozenset()):
    """Reine Entscheidungsfunktion (keine Seiteneffekte): gruppiert
    `analysierte_eintraege` per _gruppiere() (Adresse ODER Telefon ODER
    Email, siehe dort) und gibt pro Dubletten-Gruppe (>= 2 Mitglieder) ein
    Entscheidungs-Dict zurueck:
        {"primary_url": str, "entfernte_urls": [str, ...],
         "email_konflikt": None oder (gewaehlte_email, [alternative_emails])}
    """
    entscheidungen = []
    for gruppe in _gruppiere(analysierte_eintraege):
        if len(gruppe) < 2:
            continue
        primary = _waehle_primary(gruppe, gesendete_urls, analysierte_urls)
        entfernte_urls = [
            e.get("profil_url") for e in gruppe if e is not primary and e.get("profil_url")
        ]

        konflikt = None
        varianten = _email_varianten(gruppe)
        if len(varianten) > 1:
            gewaehlt = (primary.get("email") or "").strip().lower()
            alternativen = sorted(em for em in varianten if em != gewaehlt)
            konflikt = (gewaehlt, alternativen)

        entscheidungen.append({
            "primary_url": primary.get("profil_url"),
            "entfernte_urls": entfernte_urls,
            "email_konflikt": konflikt,
            "name": primary.get("name"),
            "adresse": primary.get("adresse"),
        })
    return entscheidungen


def _merge_felder_auf(primary, andere):
    for e in andere:
        for feld, wert in e.items():
            if feld == "profil_url":
                continue
            if feld in _LISTEN_FELDER:
                kombiniert = list(primary.get(feld) or [])
                for w in (wert or []):
                    if w not in kombiniert:
                        kombiniert.append(w)
                if kombiniert:
                    primary[feld] = kombiniert
            elif not primary.get(feld) and wert:
                primary[feld] = wert


def wende_an(eintraege, entscheidungen):
    """Wendet die von entscheide() getroffenen Entscheidungen auf eine
    Liste an (results_raw.json ODER results_analyzed.json -- dieselben
    Entscheidungen passen auf beide, da sie ueber profil_url adressiert
    sind). Gibt die neue, dublettenfreie Liste zurueck (Original bleibt
    unveraendert)."""
    by_url = {e.get("profil_url"): e for e in eintraege if e.get("profil_url")}
    zu_entfernen = set()

    for entscheidung in entscheidungen:
        primary = by_url.get(entscheidung["primary_url"])
        if primary is None:
            continue  # diese Liste enthaelt die Gruppe nicht (sollte nicht vorkommen)
        andere = [by_url[u] for u in entscheidung["entfernte_urls"] if u in by_url]
        _merge_felder_auf(primary, andere)

        if entscheidung["email_konflikt"]:
            _, alternativen = entscheidung["email_konflikt"]
            hinweis = (
                "Dublette zusammengefuehrt: abweichende Email-Adresse(n) "
                f"gefunden ({', '.join(alternativen)}), bitte manuell pruefen."
            )
            warnliste = list(primary.get("filter_warnungen") or [])
            if hinweis not in warnliste:
                warnliste.append(hinweis)
            primary["filter_warnungen"] = warnliste

        zu_entfernen.update(entscheidung["entfernte_urls"])

    return [e for e in eintraege if e.get("profil_url") not in zu_entfernen]


def _bericht(entscheidungen, titel):
    konflikte = [e for e in entscheidungen if e["email_konflikt"]]
    entfernt = sum(len(e["entfernte_urls"]) for e in entscheidungen)
    print(f"{titel}: {len(entscheidungen)} Dubletten-Gruppen, {entfernt} Eintraege werden entfernt.")
    if konflikte:
        print(f"  {len(konflikte)} Gruppen mit abweichenden Email-Adressen (manuell pruefen!):")
        for k in konflikte:
            gewaehlt, alternativen = k["email_konflikt"]
            print(f"  - {k['name']} ({k['adresse']}): behalten={gewaehlt!r}, verworfen={alternativen}")


def main():
    raw = json_sicher_laden(RESULTS_RAW, [])
    analysiert = json_sicher_laden(RESULTS_ANALYZED, [])
    sent_log = json_sicher_laden(SENT_LOG, [])
    gesendete_urls = {e.get("profil_url") for e in sent_log if e.get("profil_url")}

    # Durchlauf 1: Dubletten unter den bereits analysierten Eintraegen.
    entscheidungen = entscheide(analysiert, gesendete_urls)
    neue_analysiert = wende_an(analysiert, entscheidungen)
    neue_raw = wende_an(raw, entscheidungen)
    if entscheidungen:
        _bericht(entscheidungen, "Analysierte Eintraege")

    # Durchlauf 2 (4.10.2026): Dubletten, die nur in den Rohdaten stehen.
    # Registerquellen liefern viele Profile, die (noch) nie analysiert wurden;
    # Durchlauf 1 sieht sie nicht. Ohne diesen Schritt blieben z.B. ein
    # Kammer- und ein KV-Eintrag derselben Person mit identischer Adresse
    # dauerhaft getrennt -- und der Kammer-Eintrag bekaeme die KV-
    # Bestaetigung nie. Analysierte Eintraege gewinnen dabei immer (id bleibt).
    analysierte_urls = {a.get("profil_url") for a in neue_analysiert if a.get("profil_url")}
    roh_entscheidungen = []
    for e in entscheide(neue_raw, gesendete_urls, analysierte_urls):
        # Nie einen Eintrag entfernen, der schon in der Webapp steht (seine id
        # traegt evtl. Nutzer-Zustand). Zwei App-Eintraege derselben Person
        # bleiben hier also bewusst beide stehen; sie werden nur gemeldet.
        app_doppelt = [u for u in e["entfernte_urls"] if u in analysierte_urls]
        if app_doppelt:
            print(f"  Hinweis: {e['name']} steht mehrfach in der App ({len(app_doppelt) + 1}x), "
                  "nicht automatisch zusammengefuehrt.")
        e["entfernte_urls"] = [u for u in e["entfernte_urls"] if u not in analysierte_urls]
        if e["entfernte_urls"]:
            roh_entscheidungen.append(e)
    if roh_entscheidungen:
        _bericht(roh_entscheidungen, "Rohdaten")
        neue_raw = wende_an(neue_raw, roh_entscheidungen)
        neue_analysiert = wende_an(neue_analysiert, roh_entscheidungen)

    if not entscheidungen and not roh_entscheidungen:
        print("Keine Dubletten gefunden -- nichts zu tun.")
        return

    json_atomar_schreiben(RESULTS_ANALYZED, neue_analysiert)
    json_atomar_schreiben(RESULTS_RAW, neue_raw)

    print(f"\nresults_analyzed.json: {len(analysiert)} -> {len(neue_analysiert)} Eintraege")
    print(f"results_raw.json: {len(raw)} -> {len(neue_raw)} Eintraege")


if __name__ == "__main__":
    main()
