"""Tests fuer filters.py -- die harten Zulassungsregeln, die VOR der
KI-Analyse entscheiden, wer ueberhaupt in die engere Auswahl kommt.
Diese Regeln sind der wichtigste Einzelpunkt im ganzen Projekt: ein Fehler
hier heisst entweder "Therapeut faelschlich ausgeschlossen" (verpasste
Chance) oder "Therapeut faelschlich aufgenommen" (falsche Erwartung beim
Nutzer, z.B. eine KJP-Praxis, die gar keine Erwachsenen behandelt)."""

import pytest


import filters


# ---------- pruefe_profil: Regel 1 (Einzeltherapie Erwachsene) ----------

def test_regel1_exakter_treffer_wird_angenommen():
    p = {"therapieangebot": ["Einzeltherapie: Erwachsene"], "name": "Dipl.-Psych. A"}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True


def test_regel1_variante_mit_zusatz_wird_jetzt_auch_angenommen():
    """Regression zum Audit-Befund M12: die alte Implementierung prüfte auf
    exakte String-Gleichheit mit 'einzeltherapie: erwachsene'. Schon eine
    harmlose Variante wie '(ab 18)' hätte JEDEN Therapeuten mit diesem Label
    still ausgeschlossen. Der Fix prüft jetzt auf die Wortteile 'einzel' und
    'erwachsen' statt auf exakte Gleichheit."""
    p = {"therapieangebot": ["Einzeltherapie: Erwachsene (ab 18)"], "name": "Dipl.-Psych. B"}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True


def test_regel1_nur_gruppentherapie_wird_abgelehnt():
    p = {"therapieangebot": ["Gruppentherapie: Erwachsene"], "name": "Dipl.-Psych. C"}
    r = filters.pruefe_profil(p)
    assert r["ok"] is False
    assert "Einzeltherapie" in r["grund"]


def test_regel1_leeres_angebot_wird_nicht_ausgeschlossen_sondern_gewarnt():
    """Fehlt das Angebot im Profil komplett (haeufig bei unvollstaendig
    gepflegten Profilen), soll NICHT automatisch ausgeschlossen werden --
    stattdessen eine Warnung, damit approbierte Erwachsenen-Therapeuten
    ohne gepflegtes Feld nicht verloren gehen."""
    p = {"therapieangebot": [], "name": "Approbierte Psychotherapeutin"}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert any("nicht explizit" in w for w in r["warnungen"])


# ---------- pruefe_profil: Regel 2 (KJP) ----------

def test_regel2_reine_kjp_wird_ausgeschlossen():
    p = {
        "therapieangebot": ["Einzeltherapie: Erwachsene"],
        "name": "Kinder- und Jugendlichenpsychotherapeutin",
    }
    r = filters.pruefe_profil(p)
    assert r["ok"] is False
    assert "21 Jahre" in r["grund"]


def test_regel2_kjp_mit_erwachsenen_approbation_wird_angenommen_mit_warnung():
    p = {
        "therapieangebot": ["Einzeltherapie: Erwachsene"],
        "name": "Kinder- und Jugendlichenpsychotherapeutin, approbierte Psychologische Psychotherapeutin",
    }
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert any("Kinder" in w for w in r["warnungen"])


# ---------- pruefe_profil: Regel 3 (Heilpraktiker) ----------

def test_regel3_heilpraktiker_ohne_gkv_erfordernis_wird_angenommen_mit_warnung():
    p = {"therapieangebot": ["Einzeltherapie: Erwachsene"], "name": "Heilpraktiker für Psychotherapie"}
    r = filters.pruefe_profil(p, gkv_erforderlich=False)
    assert r["ok"] is True
    assert any("Selbstzahler" in w for w in r["warnungen"])


def test_regel3_heilpraktiker_mit_gkv_erfordernis_wird_ausgeschlossen():
    p = {"therapieangebot": ["Einzeltherapie: Erwachsene"], "name": "Heilpraktiker für Psychotherapie"}
    r = filters.pruefe_profil(p, gkv_erforderlich=True)
    assert r["ok"] is False
    assert "gesetzliche Krankenkasse" in r["grund"]


def test_regel3_approbierter_heilpraktiker_wird_nicht_blockiert():
    p = {
        "therapieangebot": ["Einzeltherapie: Erwachsene"],
        "name": "Heilpraktiker für Psychotherapie, approbierte Psychologische Psychotherapeutin",
    }
    r = filters.pruefe_profil(p, gkv_erforderlich=True)
    assert r["ok"] is True


# ---------- kategorie() ----------

def test_kategorie_kostenerstattung_hat_vorrang_vor_gesetzlich():
    """Wichtiger Fallstrick: eine Praxis, die GKV NUR ueber
    Kostenerstattung anbietet, darf NICHT als normaler 'kassensitz'
    einsortiert werden -- fuer die App-Logik ist der Unterschied
    entscheidend (Absagen zaehlen dort nicht als reguläre Absage)."""
    p = {"abrechnungsarten": ["Gesetzliche Krankenversicherung im Kostenerstattungsverfahren"]}
    assert filters.kategorie(p) == "kostenerstattung"


def test_kategorie_gesetzlich_ohne_kostenerstattung():
    p = {"abrechnungsarten": ["Gesetzliche Krankenversicherung"]}
    assert filters.kategorie(p) == "kassensitz"


def test_kategorie_privat_bei_fehlendem_feld():
    assert filters.kategorie({}) == "privat"
    assert filters.kategorie({"abrechnungsarten": []}) == "privat"
    assert filters.kategorie({"abrechnungsarten": None}) == "privat"


def test_kategorie_case_insensitive():
    p = {"abrechnungsarten": ["GESETZLICHE KRANKENVERSICHERUNG"]}
    assert filters.kategorie(p) == "kassensitz"


def test_kategorie_echter_kassensitz_mit_zusaetzlichem_separatem_kostenerstattungs_eintrag():
    """Gegenstueck zum kombinierten Label oben: hat eine Praxis einen ECHTEN
    Kassensitz UND bietet, als eigener/getrennter Listeneintrag, zusaetzlich
    Kostenerstattung an, zaehlt der Kassensitz (direkter, sofort nutzbarer
    Weg) - nicht Kostenerstattung. Unterschied zum kombinierten Label: hier
    sind es zwei GETRENNTE Eintraege, nicht einer, der beides in einem Satz
    verknuepft."""
    p = {"abrechnungsarten": ["Gesetzliche Krankenversicherung", "Kostenerstattungsverfahren"]}
    assert filters.kategorie(p) == "kassensitz"


# ---------- filtere() ----------

def test_filtere_teilt_in_behalten_und_raus():
    profile = [
        {"name": "A", "therapieangebot": ["Einzeltherapie: Erwachsene"], "profil_url": "u1"},
        {"name": "Kinder- und Jugendlichenpsychotherapeut B", "therapieangebot": ["Einzeltherapie: Erwachsene"], "profil_url": "u2"},
    ]
    behalten, raus = filters.filtere(profile, verbose=False)
    assert len(behalten) == 1
    assert len(raus) == 1
    assert raus[0]["ausschluss_grund"]


def test_filtere_markiert_aufnahmestopp_als_warnung():
    profile = [{"name": "A", "therapieangebot": ["Einzeltherapie: Erwachsene"], "profil_url": "u1", "aufnahmestopp": True}]
    behalten, _ = filters.filtere(profile, verbose=False)
    assert any("AUFNAHMESTOPP" in w for w in behalten[0]["filter_warnungen"])


def test_filtere_veraendert_die_uebergebenen_dicts_in_place():
    """Dokumentiert das (bewusste) In-Place-Verhalten aus dem Docstring:
    analyzer.py liest gkv_art nach dem Filterlauf direkt vom Therapeuten-Dict
    und verlaesst sich genau darauf."""
    profil = {"name": "Dipl.-Psych. A, approbierte Psychologische Psychotherapeutin",
              "therapieangebot": ["Einzeltherapie: Erwachsene"],
              "abrechnungsarten": ["Gesetzliche Krankenversicherung"], "profil_url": "u1"}
    behalten, _ = filters.filtere([profil], verbose=False)
    assert behalten[0] is profil            # dasselbe Objekt, keine Kopie
    assert profil["gkv_art"] == "kassensitz"
    assert profil["filter_warnungen"] == []


# ---------- None-Werte in Profilfeldern (Audit-Befunde B1/T5) ----------
#
# Gescrapte Profile enthalten regelmaessig JSON `null` statt eines leeren
# Strings/einer leeren Liste (Feld auf der Quellseite nicht gepflegt).
# profil.get("name", "") liefert dann None -- der Default greift nur bei
# FEHLENDEM Schluessel. Vorher stuerzte der komplette Filterlauf ab.

def test_volltext_uebersteht_none_in_textfeldern():
    profil = {"name": None, "persoenliches_profil": None, "volltext": None,
              "therapieangebot": None, "therapieverfahren": None}
    assert filters._volltext(profil) == "    "  # nur die Trenn-Leerzeichen


def test_pruefe_profil_uebersteht_none_in_allen_feldern():
    profil = {"name": None, "persoenliches_profil": None, "volltext": None,
              "therapieangebot": None, "therapieverfahren": None,
              "abrechnungsarten": None}
    r = filters.pruefe_profil(profil)
    assert r["ok"] is True  # kein Angebot angegeben -> nur Warnung, kein Ausschluss
    assert any("nicht explizit" in w for w in r["warnungen"])


def test_pruefe_profil_uebersteht_none_eintraege_in_listen():
    profil = {"name": "Dipl.-Psych. A",
              "therapieangebot": [None, "Einzeltherapie: Erwachsene", None],
              "therapieverfahren": [None, "Verhaltenstherapie"]}
    assert filters.pruefe_profil(profil)["ok"] is True


def test_pruefe_profil_meldet_grund_lesbar_trotz_none_eintraegen():
    profil = {"name": "Dipl.-Psych. A", "therapieangebot": [None, "Gruppentherapie: Erwachsene"]}
    r = filters.pruefe_profil(profil)
    assert r["ok"] is False
    assert "Gruppentherapie: Erwachsene" in r["grund"]
    assert "None" not in r["grund"]


def test_kategorie_uebersteht_none_eintraege_in_abrechnungsarten():
    assert filters.kategorie({"abrechnungsarten": [None, "Gesetzliche Krankenversicherung"]}) == "kassensitz"
    assert filters.kategorie({"abrechnungsarten": [None]}) == "privat"


def test_filtere_uebersteht_profil_komplett_aus_none_feldern():
    profile = [{"profil_url": "u1", "name": None, "therapieangebot": None,
                "abrechnungsarten": None, "volltext": None}]
    behalten, raus = filters.filtere(profile, verbose=False)
    assert len(behalten) == 1
    assert behalten[0]["gkv_art"] == "privat"


# ---------- Regel 1 ueber die zusammengefuegte Liste (Audit-Befund B10) ----------

def test_regel1_findet_auf_zwei_listenpunkte_verteiltes_label():
    """Sollte therapie.de das Label eines Tages aufteilen, findet die
    Pruefung pro Einzeleintrag nichts mehr -- ohne die Zusatzpruefung ueber
    die zusammengefuegte Liste waeren dann schlagartig ALLE Profile still
    ausgeschlossen."""
    p = {"therapieangebot": ["Einzeltherapie:", "Erwachsene"], "name": "Dipl.-Psych. A"}
    assert filters.pruefe_profil(p)["ok"] is True


def test_regel1_kinder_einzel_plus_gruppe_erwachsene_bleibt_ausgeschlossen():
    """Gegenprobe: die Zusatzpruefung darf NICHT dazu fuehren, dass
    'Einzeltherapie fuer Kinder' + 'Gruppentherapie fuer Erwachsene'
    faelschlich als Einzeltherapie fuer Erwachsene durchgeht."""
    p = {"therapieangebot": ["Einzeltherapie: Kinder/Jugendliche",
                             "Gruppentherapie: Erwachsene"],
         "name": "Dipl.-Psych. A"}
    assert filters.pruefe_profil(p)["ok"] is False


# ---------- Approbation dreistufig (Review #10) ----------
#
# Frueher reichte das isolierte Wort "Approbation" IRGENDWO im Profiltext als
# Erwachsenen-Nachweis. Dadurch kamen z.B. "Heilpraktikerin, ohne Approbation"
# oder reine KJP ("approbierte Kinder- und Jugendlichenpsychotherapeutin") bei
# GKV-Suche faelschlich durch.

EINZEL = ["Einzeltherapie: Erwachsene"]


def test_heilpraktikerin_ohne_approbation_wird_bei_gkv_ausgeschlossen():
    p = {"therapieangebot": EINZEL, "name": "Anna A",
         "volltext": "Heilpraktikerin für Psychotherapie, ohne Approbation"}
    r = filters.pruefe_profil(p, gkv_erforderlich=True)
    assert r["ok"] is False
    assert "Heilpraktiker" in r["grund"]


def test_heilpraktiker_mit_verneinung_ohne_komma_und_nicht_approbiert():
    for text in ["Heilpraktiker für Psychotherapie ohne Approbation",
                 "Heilpraktiker (Psychotherapie), keine staatliche Approbation",
                 "Heilpraktiker für Psychotherapie, nicht approbiert",
                 "Heilpraktikerin, ohne Approbation als Psychologische Psychotherapeutin"]:
        p = {"therapieangebot": EINZEL, "name": "B", "volltext": text}
        assert filters.pruefe_profil(p)["ok"] is False, text


def test_reine_kjp_approbation_zaehlt_nicht_als_erwachsenen_nachweis():
    for text in ["Ich bin approbierte Kinder- und Jugendlichenpsychotherapeutin.",
                 "2015 Approbation als Kinder- und Jugendlichenpsychotherapeutin",
                 "Kinder- und Jugendlichenpsychotherapeut/in approbiert",
                 "Kinder- und Jugendlichenpsychotherapeutin mit abschließender Approbation",
                 "Berufsbegleitende Approbationsausbildung zur Kinder- und "
                 "Jugendlichenpsychotherapeutin"]:
        p = {"therapieangebot": EINZEL, "name": "C", "volltext": text}
        r = filters.pruefe_profil(p)
        assert r["ok"] is False, text
        assert "21 Jahre" in r["grund"]


def test_approbierte_kolleginnen_sind_kein_nachweis_fuer_die_person():
    p = {"therapieangebot": EINZEL, "name": "D",
         "volltext": "Heilpraktikerin für Psychotherapie. In der Praxisgemeinschaft "
                     "arbeite ich mit approbierten Kolleginnen zusammen."}
    assert filters.pruefe_profil(p)["ok"] is False


def test_allgemeine_approbation_bei_kjp_bleibt_drin_aber_mit_pruef_warnung():
    """Unklarer Fall: KJP plus ein allgemeines 'Approbation' ohne Angabe,
    wofuer. Wie bisher nicht ausschliessen, aber NICHT mehr als bestaetigte
    Erwachsenen-Zulassung ausgeben, sondern als Pruef-Warnung."""
    p = {"therapieangebot": EINZEL, "name": "E",
         "volltext": "Kinder- und Jugendlichenpsychotherapeutin. Meine Approbation "
                     "erlangte ich im Jahre 2011."}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert any("unklar" in w for w in r["warnungen"])
    assert not any("Erwachsenen-Zulassung laut Profil vorhanden" in w for w in r["warnungen"])


def test_heilpraktiker_mit_allgemeiner_approbation_bleibt_mit_warnung():
    p = {"therapieangebot": EINZEL, "name": "F",
         "volltext": "Heilpraktiker für Psychotherapie. Approbation 2010."}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert any("nicht eindeutig" in w for w in r["warnungen"])


def test_widerspruch_berufsbezeichnung_und_ohne_approbation_wird_markiert():
    p = {"therapieangebot": EINZEL, "name": "G",
         "volltext": "Psychologische Psychotherapeutin (in Ausbildung). "
                     "Behandlung derzeit ohne Approbation."}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert any("Widersprüchliche" in w for w in r["warnungen"])


def test_verneinung_in_anderem_satzteil_zaehlt_nicht():
    """'Keine Kassenzulassung, Psychologische Psychotherapeutin' -- die
    Verneinung bezieht sich auf die Kassenzulassung, nicht auf den Beruf."""
    p = {"therapieangebot": EINZEL, "name": "H",
         "volltext": "Heilpraktikergesetz erwähnt. Keine Kassenzulassung, "
                     "Psychologische Psychotherapeutin"}
    r = filters.pruefe_profil(p)
    assert r["ok"] is True
    assert r["warnungen"] == []


def test_nicht_nur_ist_keine_verneinung():
    status, verneint = filters._approbations_status(
        "ich bin nicht nur approbierte psychologische psychotherapeutin")
    assert status == "bestaetigt"
    assert verneint is False


# Regressionstests: echte Erwachsenen-Nachweise muessen wie bisher greifen,
# auch in Kombination mit KJP oder Heilpraktiker.

@pytest.mark.parametrize("beruf", [
    "Psychologische Psychotherapeutin",
    "Psychologischer Psychotherapeut",
    "Psychologische/r Psychotherapeut/in approbiert",
    "Ärztliche Psychotherapeutin",
    "Ärztlicher Psychotherapeut",
    "Facharzt für Psychiatrie und Psychotherapie",
    "Fachärztin für Psychosomatische Medizin",
    "Facharzt/-ärztin für Psychosomatische Medizin und Psychotherapie",
    "Approbation als Psychologische Psychotherapeutin",
    "approbierte Psychologische Psychotherapeutin",
])
def test_echte_erwachsenen_nachweise_bleiben_bestaetigt(beruf):
    assert filters._approbations_status(beruf.lower())[0] == "bestaetigt"
    for zusatz in ["Kinder- und Jugendlichenpsychotherapeutin", "Heilpraktiker für Psychotherapie"]:
        p = {"therapieangebot": EINZEL, "name": "X", "volltext": f"{zusatz}, {beruf}"}
        r = filters.pruefe_profil(p, gkv_erforderlich=True)
        assert r["ok"] is True, (zusatz, beruf)
        assert not any("unklar" in w or "nicht eindeutig" in w for w in r["warnungen"])


def test_kassenaerztliche_vereinigung_ist_kein_beruf():
    assert filters._approbations_status(
        "kassensitz laut kassenärztliche vereinigung westfalen-lippe")[0] == "keine"


# ---------- Hinweis "Berufsbezeichnung unklar" ----------

def _erwachsenenprofil(name, text=""):
    return {"name": name, "persoenliches_profil": text,
            "therapieangebot": ["Einzeltherapie: Erwachsene"],
            "abrechnungsarten": ["Gesetzliche Krankenversicherung"]}


def test_ohne_jede_berufsbezeichnung_gibt_es_einen_pruefhinweis():
    ergebnis = filters.pruefe_profil(_erwachsenenprofil("Praxis am Markt", "Gesprächstherapie für Erwachsene."))
    assert ergebnis["ok"] is True
    assert any("Berufsbezeichnung" in w for w in ergebnis["warnungen"])


def test_allgemeine_bezeichnung_psychotherapeutin_reicht_gegen_den_hinweis():
    ergebnis = filters.pruefe_profil(_erwachsenenprofil("Praxis am Markt", "Ich bin Psychotherapeutin."))
    assert not any("Berufsbezeichnung" in w for w in ergebnis["warnungen"])


def test_bestaetigte_approbation_ohne_jeden_hinweis():
    ergebnis = filters.pruefe_profil(_erwachsenenprofil("Dipl.-Psych. Anna Beispiel, Psychologische Psychotherapeutin"))
    assert ergebnis == {"ok": True, "grund": "", "warnungen": []}


def test_verneinung_ganz_am_textanfang_wird_erkannt():
    """Die Verneinung steht im allerersten Wort des Textes (Position 0)."""
    assert filters._ist_verneint("ohne approbation", len("ohne "))
    assert not filters._ist_verneint("mit approbation", len("mit "))


def test_main_schreibt_die_ausgeschlossenen_mit_grund(tmp_path, monkeypatch):
    import json
    import pfade
    roh, log = tmp_path / "roh.json", tmp_path / "raus.json"
    roh.write_text(json.dumps([
        {"name": "A", "titel": "Psychologische Psychotherapeutin", "abrechnungsarten": ["Gesetzliche Krankenkassen"],
         "therapieangebot": ["Einzeltherapie Erwachsene"]},
        {"name": "B", "titel": "Kinder- und Jugendlichenpsychotherapeutin",
         "therapieangebot": ["Einzeltherapie Kinder"]},
    ]), encoding="utf-8")
    monkeypatch.setattr(pfade, "AUSGESCHLOSSEN_LOG", log)
    assert filters.main([str(roh)]) == 1
    [raus] = json.loads(log.read_text(encoding="utf-8"))
    assert raus["name"] == "B" and raus["ausschluss_grund"]
