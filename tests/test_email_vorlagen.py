"""Tests fuer backend/email_vorlagen.py -- die 40 rotierenden Anfrage-Texte
(siehe Modul-Docstring: sollen nicht als Serienbrief erkennbar sein).

Seit 26.8.2026 enthalten die Vorlagen KEINE festen Marcel-Fakten mehr
(weder Name noch Diagnose), sondern die Platzhalter {name} und
{situation}. Grund: mehrere echte Menschen nutzen die Webapp aktiv, und
ohne diese Aenderung haette jede Person beim Senden eine Anfrage mit
Marcels Namen und Diagnose verschickt statt ihrer eigenen (siehe
Modul-Docstring fuer Details)."""
import re


import email_vorlagen


def test_es_gibt_genau_vierzig_vorlagen():
    assert len(email_vorlagen.VORLAGEN) == 40


def test_alle_vorlagen_sind_einzigartig():
    assert len(set(email_vorlagen.VORLAGEN)) == 40


def test_keine_vorlage_enthaelt_bindestriche_oder_gedankenstriche():
    # Projekt-Stilregel (siehe CLAUDE.md/webapp-Tests) plus explizite
    # Vorgabe fuer diese Vorlagen: gar keine Bindestriche.
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        for zeichen in ("-", "–", "—"):
            assert zeichen not in text, f"Vorlage {i} enthaelt '{zeichen}'"


def test_jede_vorlage_hat_alle_vier_platzhalter():
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        assert "{anrede}" in text, f"Vorlage {i}: {{anrede}} fehlt"
        assert "{therapieform}" in text, f"Vorlage {i}: {{therapieform}} fehlt"
        assert "{name}" in text, f"Vorlage {i}: {{name}} fehlt"
        assert "{situation}" in text, f"Vorlage {i}: {{situation}} fehlt"


def test_jede_vorlage_endet_mit_dem_namen_platzhalter():
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        assert text.strip().endswith("{name}"), f"Vorlage {i}: Unterschrift ist nicht der Platzhalter"


def test_keine_vorlage_enthaelt_noch_hardcodierte_marcel_fakten():
    # Der eigentliche Bugfix: keine Vorlage darf mehr Marcels Namen oder
    # seine konkrete Diagnose fest enthalten, das kommt jetzt ausschliesslich
    # aus dem Profil der jeweils sendenden Person.
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        assert "Marcel" not in text, f"Vorlage {i}: enthaelt noch hardcoded 'Marcel'"
        assert "Welk" not in text, f"Vorlage {i}: enthaelt noch hardcoded 'Welk'"
        assert "adhs" not in text.lower(), f"Vorlage {i}: enthaelt noch hardcoded ADHS"
        assert "depressive" not in text.lower(), f"Vorlage {i}: enthaelt noch hardcoded Diagnose"


def test_jede_vorlage_nennt_die_festen_kernfakten():
    # GKV-Status, ambulante Behandlung fuer Erwachsene und die Bitte um eine
    # Wartezeit-Angabe gelten fuer jede Person, die dieses Tool nutzt, und
    # bleiben deshalb fest in jeder Vorlage stehen.
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        t = text.lower()
        assert "gesetzlich" in t and "versichert" in t, f"Vorlage {i}: GKV-Status fehlt"
        assert "warte" in t, f"Vorlage {i}: keine Frage nach Wartezeit (Wartezeit-Fix)"


# ---------- anrede_aus_name() ----------

def test_anrede_aus_name_entfernt_vornamen_behaelt_titel():
    assert email_vorlagen.anrede_aus_name("Frau Dipl.-Psych. Anna Beispiel") == "Frau Dipl.-Psych. Beispiel"


def test_anrede_aus_name_ohne_titel():
    assert email_vorlagen.anrede_aus_name("Herr Michael Probe") == "Herr Probe"


def test_anrede_aus_name_mit_doktortitel():
    assert email_vorlagen.anrede_aus_name("Frau Dr. Pia Muster") == "Frau Dr. Muster"


def test_anrede_aus_name_leer_bei_leerem_namen():
    assert email_vorlagen.anrede_aus_name("") == ""
    assert email_vorlagen.anrede_aus_name(None) == ""


def test_anrede_aus_name_einzelnes_wort_bleibt_unveraendert():
    assert email_vorlagen.anrede_aus_name("Praxis") == "Praxis"


# ---------- therapieform_aus_profil() ----------

def test_therapieform_aus_profil_entfernt_klammerzusatz():
    therapeut = {"therapieverfahren": ["Verhaltenstherapie (Richtlinie)"]}
    assert email_vorlagen.therapieform_aus_profil(therapeut) == "Verhaltenstherapie"


def test_therapieform_aus_profil_nimmt_erstes_nicht_leeres():
    therapeut = {"therapieverfahren": ["", "Tiefenpsychologisch fundierte Psychotherapie"]}
    assert email_vorlagen.therapieform_aus_profil(therapeut) == "Tiefenpsychologisch fundierte Psychotherapie"


def test_therapieform_aus_profil_standardwert_ohne_verfahren():
    assert email_vorlagen.therapieform_aus_profil({}) == "Einzeltherapie"
    assert email_vorlagen.therapieform_aus_profil(None) == "Einzeltherapie"


# ---------- zufaellige_anfrage() ----------

class _FesterZufall:
    """Test-Double fuer den zufallsgenerator-Parameter: waehlt immer den
    Eintrag am uebergebenen Index statt echt zufaellig."""
    def __init__(self, index):
        self.index = index

    def choice(self, sequenz):
        return sequenz[self.index]


_SITUATION = "Bei mir wurde eine Angststoerung diagnostiziert."


def test_zufaellige_anfrage_befuellt_alle_platzhalter():
    therapeut = {"name": "Frau Dipl.-Psych. Anna Beispiel", "therapieverfahren": ["Verhaltenstherapie (Richtlinie)"]}
    email_text, anrede, therapieform = email_vorlagen.zufaellige_anfrage(
        therapeut, "Erika Mustermann", _SITUATION, zufallsgenerator=_FesterZufall(0)
    )
    assert anrede == "Frau Dipl.-Psych. Beispiel"
    assert therapieform == "Verhaltenstherapie"
    assert "Frau Dipl.-Psych. Beispiel" in email_text
    assert "Verhaltenstherapie" in email_text
    assert "Erika Mustermann" in email_text
    assert _SITUATION in email_text
    assert "{" not in email_text


def test_zufaellige_anfrage_nutzt_eigene_daten_nicht_marcels():
    therapeut = {"name": "Herr Probe"}
    email_text, _, _ = email_vorlagen.zufaellige_anfrage(
        therapeut, "Erika Mustermann", _SITUATION, zufallsgenerator=_FesterZufall(0)
    )
    assert "Marcel" not in email_text
    assert "Welk" not in email_text
    assert "ADHS" not in email_text


def test_zufaellige_anfrage_nutzt_verschiedene_vorlagen_je_nach_index():
    therapeut = {"name": "Herr Probe"}
    text_a, _, _ = email_vorlagen.zufaellige_anfrage(
        therapeut, "Erika Mustermann", _SITUATION, zufallsgenerator=_FesterZufall(0)
    )
    text_b, _, _ = email_vorlagen.zufaellige_anfrage(
        therapeut, "Erika Mustermann", _SITUATION, zufallsgenerator=_FesterZufall(1)
    )
    assert text_a != text_b


def test_jede_vorlage_laesst_sich_formatieren():
    for i, text in enumerate(email_vorlagen.VORLAGEN):
        ergebnis = text.format(
            anrede="Frau Dr. Mueller",
            therapieform="Verhaltenstherapie",
            name="Erika Mustermann",
            situation=_SITUATION,
        )
        assert "{" not in ergebnis and "}" not in ergebnis, f"Vorlage {i}: Platzhalter nicht ersetzt"
        assert "Frau Dr. Mueller" in ergebnis
        assert "Verhaltenstherapie" in ergebnis
        assert "Erika Mustermann" in ergebnis
        assert _SITUATION in ergebnis
