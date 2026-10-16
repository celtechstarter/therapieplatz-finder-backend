"""
40 vorformulierte Anfrage-Emails fuer den Erstkontakt mit Praxen.

Warum 40 statt einer Vorlage: wenn viele Praxen dieselbe Email bekommen,
faellt das als Serienbrief auf und die Bitte um eine kurze Rueckmeldung
zur Wartezeit (siehe Hinweis eines Psychotherapeuten, 14.8.2026) wirkt
weniger persoenlich. Die 40 Texte sagen inhaltlich dasselbe, sind aber
unterschiedlich formuliert, damit beim Rotieren durch viele Praxen kein
erkennbares Muster entsteht.

AENDERUNG (26.8.2026): die Vorlagen enthielten bis eben fest eingebaut
einen festen Absendernamen und eine feste Situationsbeschreibung. Das wurde in diesem Modul auf die Platzhalter {name}/
{situation} umgestellt, ausgeloest durch den (bei genauerem Hinsehen
FALSCHEN) Verdacht, die live deployte Webapp wuerde diesen Text ungefiltert
an alle eingeloggten Personen ausliefern.
KLARSTELLUNG: dieser Verdacht war falsch. Die Webapp baut die tatsaechlich
gesendete Anfrage NICHT aus diesen Vorlagen, sondern komplett unabhaengig
client-seitig ueber buildEmail() in webapp/app/app-utils.js -- und dort
werden bereits seit laengerem echte, im Onboarding-Wizard pro Person
erfasste Werte verwendet (state.name, state.themen -> THEMA_DIAGNOSE),
nicht die festen Werte. Es gab also nie eine Vermischung fremder Identitaeten.
Die 40 Vorlagen hier UND profiles.eigener_name/eigene_situation in
Supabase (siehe Migration profiles_eigener_name_und_situation) sind
dementsprechend aktuell NICHT an die Webapp angeschlossen -- sie werden nur
von analyzer.py fuer das Referenzfeld Email_generiert in
results_analyzed.json verwendet (siehe REFERENZ_NAME/REFERENZ_SITUATION
in analyzer.py). Falls diese Vorlagen kuenftig doch die
EMAIL_EINSTIEG/EMAIL_BITTE/EMAIL_GRUSSFORMEL-Rotation in app-utils.js
ersetzen sollen, ist das eine bewusste, separate Entscheidung.

Regeln, an die sich JEDE Vorlage haelt:
  - einfache, alltagsnahe Sprache, keine Schachtelsaetze
  - keine Bindestriche und keine Gedankenstriche (Projekt-Stilregel)
  - "gesetzlich versichert" und "ambulante Psychotherapie fuer
    Erwachsene gesucht" bleiben als feste Fakten stehen, weil das fuer
    JEDE Person gilt, die dieses Tool ueberhaupt nutzt (die Suche ist von
    vornherein auf GKV-Praxen gefiltert)
  - die eigentliche Diagnose/Situation ist NICHT mehr fest eingebaut,
    sondern der Platzhalter {situation}, den jede Person selbst als
    vollstaendigen Satz in ihrem Profil hinterlegt
  - fragt konkret nach einer ungefaehren Wartezeit statt allgemein nach
    "Kapazitaeten oder Warteliste" (Vorschlag aus diesem Hinweis), weil Krankenkassen
    wie die TK ein "nicht erreicht" nicht als Nachweis akzeptieren
  - endet mit dem eigenen Namen der Person ({name}), keine anonyme Vorlage

Platzhalter zum Befuellen mit .format():
  {anrede}       z.B. "Frau Dr. Müller" (ohne "Guten Tag" davor, das
                 steht schon in jeder Vorlage)
  {therapieform} z.B. "Verhaltenstherapie" (aus dem Profil, faellt sonst
                 auf "Einzeltherapie" zurueck, siehe analyzer.py)
  {name}         eigener Name der absendenden Person, z.B. "Max Mustermann"
  {situation}     eigener, vollstaendiger Situationssatz der absendenden
                 Person, z.B. "Bei mir wurde eine Angststoerung
                 festgestellt." -- MUSS als
                 abgeschlossener Satz mit Punkt geschrieben sein, da er
                 mitten im Absatz eingesetzt wird (siehe Vorlagen unten).

Nutzung: vorlage = VORLAGEN[i % len(VORLAGEN)].format(anrede=..., therapieform=..., name=..., situation=...)

Ab jetzt (siehe zufaellige_anfrage() unten) wird nicht mehr durchrotiert,
sondern pro Profil eine zufaellige Vorlage gezogen. In der Webapp
passiert das client-seitig mit den eigenen Profildaten der eingeloggten
Person (siehe app-actions.js). analyzer.py nutzt zufaellige_anfrage()
weiterhin, aber NUR fuer einen Referenztext in results_analyzed.json --
dieser Text wird nicht mehr direkt versendet, siehe Docstring dort.
Anrede und Therapieform werden dabei direkt aus dem Profil abgeleitet
(anrede_aus_name(), therapieform_aus_profil()), nicht mehr per Regex aus
dem fertigen Email-Text zurueckgewonnen.
"""
import random
import re

_PREFIX_MUSTER = re.compile(
    r"^((?:(?:Frau|Herr|Herrn|Dr\.?|Prof\.?|Dipl\.-?Psych\.?|Diplom-?Psycho\w+|"
    r"M\.?\s?Sc\.?|M\.?\s?A\.?|B\.?\s?Sc\.?|Univ\.?|rer\.?|nat\.?|phil\.?|medic\.?)\.?\s*)+)",
    re.IGNORECASE,
)


def anrede_aus_name(name):
    """Leitet aus einem vollen Profilnamen (Frau Dipl.-Psych. Anna Beispiel)
    eine Anrede ab (Frau Dipl.-Psych. Beispiel): Anrede und Titel bleiben
    stehen, der Vorname faellt weg. Grobe Heuristik ohne Anspruch auf
    hundert Prozent Treffsicherheit bei ungewoehnlichen Namen, der Text
    kann vor dem Versand ohnehin noch angepasst werden."""
    name = (name or "").strip()
    if not name:
        return ""
    treffer = _PREFIX_MUSTER.match(name)
    if treffer:
        praefix = treffer.group(1).strip()
        rest = name[len(treffer.group(1)):].strip()
    else:
        praefix = ""
        rest = name
    teile = rest.split()
    nachname = teile[-1] if teile else ""
    if praefix and nachname:
        return f"{praefix} {nachname}"
    return nachname or name


def therapieform_aus_profil(therapeut):
    """Nimmt das erste nicht leere Therapieverfahren aus dem Profil, zum
    Beispiel Verhaltenstherapie (Richtlinie) wird zu Verhaltenstherapie,
    sonst denselben Standardwert, den app/app.js clientseitig sowieso
    verwendet, wenn nichts bekannt ist."""
    for verfahren in (therapeut or {}).get("therapieverfahren") or []:
        v = (verfahren or "").strip()
        v = re.sub(r"\s*\(.*?\)\s*$", "", v).strip()
        if v:
            return v
    return "Einzeltherapie"


def zufaellige_anfrage(therapeut, name, situation, zufallsgenerator=random):
    """Waehlt zufaellig eine der vierzig Vorlagen und befuellt sie mit
    Anrede/Therapieform aus dem Profil sowie dem EIGENEN Namen und
    Situationssatz der absendenden Person (name/situation sind absichtlich
    Pflichtparameter ohne Standardwert -- das verhindert, dass irgendwo
    versehentlich wieder feste Absender-Werte einschleichen, siehe
    Modul-Docstring). Gibt ein Dreiertupel zurueck (email_text, anrede,
    therapieform), damit der Aufrufer anrede/therapieform separat
    speichern kann statt sie spaeter per Regex aus dem Text
    zurueckzugewinnen. zufallsgenerator ist injizierbar fuer deterministische
    Tests (z.B. ein Objekt mit fester choice()-Rueckgabe)."""
    anrede = anrede_aus_name((therapeut or {}).get("name"))
    therapieform = therapieform_aus_profil(therapeut)
    vorlage = zufallsgenerator.choice(VORLAGEN)
    email_text = vorlage.format(anrede=anrede, therapieform=therapieform, name=name, situation=situation)
    return email_text, anrede, therapieform


VORLAGEN = [

"""Guten Tag {anrede},

ich melde mich bei Ihnen, weil ich einen Therapieplatz suche. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls Sie {therapieform} anbieten, waere das genau das Richtige fuer mich.

Ich waere Ihnen sehr dankbar, wenn Sie mir kurz sagen koennten, wie lange die Wartezeit bei Ihnen ungefaehr ist. Auch eine grobe Einschaetzung hilft mir schon weiter.

Mit freundlichen Gruessen
{name}""",

"""Hallo {anrede},

mein Name ist {name} und ich bin auf der Suche nach einem Therapieplatz. {situation} Versichert bin ich gesetzlich, gesucht wird ambulante Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer mich besonders passend.

Koennten Sie mir kurz mitteilen, mit welcher Wartezeit ich bei Ihnen ungefaehr rechnen muesste? Eine kurze Antwort reicht mir schon vollkommen.

Freundliche Gruesse
{name}""",

"""Sehr geehrte {anrede},

ich schreibe Ihnen, weil ich auf der Suche nach einem Therapieplatz bin. {situation} Ich bin gesetzlich versichert und moechte gerne ambulante Psychotherapie als Erwachsener beginnen.

Sollten Sie {therapieform} anbieten, waere das fuer mich ideal.

Ich waere Ihnen dankbar, wenn Sie mir eine kurze Einschaetzung zur Wartezeit geben koennten, auch eine ungefaehre Angabe genuegt mir voellig.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

{situation} Ich bin gesetzlich versichert und suche einen Platz fuer ambulante Psychotherapie.

Falls {therapieform} zu Ihrem Angebot gehoert, waere das sehr gut fuer mich geeignet.

Wuerden Sie mir kurz schreiben, wie lange man bei Ihnen momentan etwa warten muss? Selbst eine grobe Zahl waere fuer mich schon hilfreich.

Viele Gruesse
{name}""",

"""Hallo {anrede},

ich bin auf Therapieplatzsuche und wende mich deshalb an Sie. {situation} Da ich gesetzlich versichert bin, suche ich eine ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich besonders passend, falls Sie das anbieten.

Koennten Sie mir bitte kurz mitteilen, wie hoch die Wartezeit bei Ihnen aktuell ungefaehr ist? Schon eine kurze Info hilft mir bei der weiteren Suche.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

mit dieser Nachricht moechte ich mich nach einem freien Therapieplatz erkundigen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer meine Behandlung sehr passend.

Da ich fuer meine Krankenkasse eine konkrete Angabe brauche, waere ich Ihnen dankbar, wenn Sie mir kurz sagen koennten, wie lange die Wartezeit bei Ihnen etwa ausfaellt.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich suche derzeit nach einem Therapieplatz und melde mich deshalb bei Ihnen. {situation} Ich bin gesetzlich versichert und moechte ambulante Psychotherapie als Erwachsener beginnen.

Sollten Sie {therapieform} anbieten, waere das fuer mich genau richtig.

Ich waere froh, wenn Sie mir kurz eine ungefaehre Wartezeit nennen koennten, egal ob wenige Wochen oder mehrere Monate.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

mein Name ist {name}. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls {therapieform} zu Ihrem Angebot zaehlt, waere das fuer mich ein guter Ansatzpunkt.

Waere es moeglich, dass Sie mir kurz schreiben, wie lange die Wartezeit bei Ihnen momentan ist? Auch eine grobe Schaetzung reicht mir.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich befinde mich auf der Suche nach einem Therapieplatz und moechte mich deshalb bei Ihnen melden. {situation} Ich bin gesetzlich versichert und suche eine ambulante Behandlung fuer Erwachsene.

{therapieform} waere fuer mich sehr geeignet, sofern Sie das anbieten.

Fuer meine Krankenkasse benoetige ich eine kurze Angabe zur Wartezeit. Ich waere Ihnen dankbar, wenn Sie mir dazu ein paar Worte schreiben koennten.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

{situation} Da ich gesetzlich versichert bin, suche ich einen Platz fuer ambulante Psychotherapie und wende mich deshalb an Sie.

Wenn Sie {therapieform} anbieten, waere das fuer mich besonders interessant.

Koennten Sie mir kurz sagen, wie lange die aktuelle Wartezeit bei Ihnen ungefaehr betraegt? Auch eine kurze Schaetzung hilft mir weiter.

Viele Gruesse
{name}""",

"""Hallo {anrede},

ich suche gerade nach einem Therapieplatz. {situation} Da ich gesetzlich versichert bin, suche ich ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich eine gute Wahl, falls Sie das im Angebot haben.

Ich waere Ihnen dankbar fuer eine kurze Rueckmeldung dazu, wie lange man bei Ihnen momentan etwa warten muss.

Freundliche Gruesse
{name}""",

"""Sehr geehrte {anrede},

ich schreibe Ihnen, da ich einen Therapieplatz suche. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Sollte {therapieform} zu Ihrem Angebot gehoeren, waere das fuer mich passend.

Damit ich das gegenueber meiner Krankenkasse belegen kann, waere eine kurze Angabe zur ungefaehren Wartezeit sehr hilfreich.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich bin auf der Suche nach einem freien Therapieplatz und moechte mich deshalb kurz vorstellen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie als Erwachsener.

{therapieform} waere fuer mich ideal, sofern Sie das anbieten.

Wie lange muss man bei Ihnen aktuell etwa auf einen Platz warten? Eine kurze Antwort dazu wuerde mir schon viel helfen.

Mit freundlichen Gruessen
{name}""",

"""Hallo {anrede},

ich moechte mich bei Ihnen nach einem Therapieplatz erkundigen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer mich sehr gut geeignet.

Ich waere froh ueber eine kurze Rueckmeldung, wie lange die Wartezeit bei Ihnen momentan ungefaehr ist.

Viele Gruesse
{name}""",

"""Sehr geehrte {anrede},

mit dieser Email moechte ich mich um einen Therapieplatz bemuehen. {situation} Ich bin gesetzlich versichert und suche eine ambulante Behandlung fuer Erwachsene.

{therapieform} waere fuer mich besonders relevant, falls Sie das anbieten.

Eine kurze Angabe zur ungefaehren Wartezeit waere sehr hilfreich fuer mich, da ich das gegenueber meiner Kasse nachweisen muss.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich suche einen Therapieplatz und melde mich deshalb bei Ihnen. {situation} Ich bin gesetzlich versichert und moechte ambulante Psychotherapie fuer Erwachsene beginnen.

Falls {therapieform} zu Ihrem Angebot gehoert, waere das fuer mich der passende Weg.

Wenn Sie mir kurz sagen koennten, wie lange die Wartezeit aktuell etwa ist, waere mir sehr geholfen.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

ich bin {name} und suche momentan nach einem Therapieplatz. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich passend, sofern Sie das anbieten.

Koennten Sie mir kurz eine ungefaehre Wartezeit nennen? Auch eine grobe Angabe hilft mir schon sehr.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich befinde mich derzeit auf Therapieplatzsuche. {situation} Da ich gesetzlich versichert bin, suche ich ambulante Psychotherapie fuer Erwachsene.

Sollten Sie {therapieform} anbieten, waere das fuer meine Situation sehr gut geeignet.

Ich waere Ihnen dankbar, wenn Sie mir kurz mitteilen koennten, wie lange die Wartezeit bei Ihnen momentan etwa dauert.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich melde mich, weil ich auf der Suche nach einem Therapieplatz bin. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie als Erwachsener.

Wenn {therapieform} zu Ihrem Angebot gehoert, waere das genau das Richtige fuer mich.

Fuer meine Krankenkasse waere eine kurze Angabe zur Wartezeit sehr wichtig. Ich waere Ihnen dankbar, wenn Sie mir dazu kurz antworten koennten.

Viele Gruesse
{name}""",

"""Hallo {anrede},

ich suche einen Platz fuer ambulante Psychotherapie und schreibe Ihnen deshalb. {situation} Ich bin gesetzlich versichert.

{therapieform} waere fuer mich eine gute Option, falls Sie das anbieten.

Ich waere Ihnen dankbar fuer eine kurze Rueckmeldung, wie lange die Wartezeit bei Ihnen aktuell in etwa ist.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich moechte mich bei Ihnen wegen eines Therapieplatzes melden. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls Sie {therapieform} anbieten, waere das fuer mich besonders relevant.

Ich waere Ihnen dankbar, wenn Sie mir kurz mitteilen koennten, wie lange die Wartezeit bei Ihnen ungefaehr betraegt.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

{situation} Ich bin gesetzlich versichert und auf der Suche nach ambulanter Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer mich der passende Weg.

Damit ich das meiner Krankenkasse zeigen kann, waere eine kurze Angabe zur ungefaehren Wartezeit sehr hilfreich fuer mich.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

ich bin auf der Suche nach einem Therapieplatz und wende mich deshalb an Sie. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich sehr passend, falls das zu Ihrem Angebot gehoert.

Koennten Sie mir kurz sagen, mit welcher Wartezeit ich bei Ihnen etwa rechnen muss? Eine grobe Angabe reicht mir voellig.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich moechte mich nach einem Therapieplatz bei Ihnen erkundigen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Sofern Sie {therapieform} anbieten, waere das fuer mich sehr geeignet.

Ich waere Ihnen dankbar, wenn Sie mir eine kurze Einschaetzung zur Wartezeit geben koennten, auch nur ungefaehr.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich suche einen Therapieplatz und melde mich deshalb bei Ihnen. {situation} Ich bin gesetzlich versichert und suche eine ambulante Behandlung fuer Erwachsene.

{therapieform} waere fuer mich eine gute Wahl, falls Sie das im Angebot haben.

Wuerden Sie mir bitte kurz sagen, wie lange die Wartezeit bei Ihnen momentan etwa ist? Das wuerde mir sehr helfen.

Viele Gruesse
{name}""",

"""Hallo {anrede},

ich schreibe Ihnen, weil ich einen Therapieplatz suche. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie als Erwachsener.

Falls {therapieform} zu Ihrem Angebot gehoert, waere das fuer mich besonders passend.

Ich waere Ihnen dankbar fuer eine kurze Angabe zur ungefaehren Wartezeit, da ich das fuer meine Krankenkasse brauche.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich bin auf Therapieplatzsuche und melde mich deshalb bei Ihnen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer mich der richtige Ansatz.

Koennten Sie mir kurz mitteilen, wie hoch die Wartezeit bei Ihnen aktuell ungefaehr ist? Ich waere Ihnen sehr dankbar.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich moechte mich bei Ihnen wegen eines freien Therapieplatzes melden. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich sehr relevant, sofern Sie das anbieten.

Ich waere Ihnen dankbar, wenn Sie mir kurz die ungefaehre Wartezeit bei Ihnen nennen koennten.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

ich suche aktuell nach einem Therapieplatz. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls {therapieform} zu Ihrem Angebot gehoert, waere das genau das, was ich suche.

Waere es Ihnen moeglich, mir kurz zu schreiben, wie lange die Wartezeit bei Ihnen momentan etwa dauert?

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich moechte mich um einen Therapieplatz bei Ihnen bemuehen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Sollten Sie {therapieform} anbieten, waere das fuer mich sehr passend.

Fuer meine Krankenkasse brauche ich eine kurze, konkrete Angabe zur Wartezeit. Ich waere Ihnen dankbar, wenn Sie mir dazu antworten koennten.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich bin auf der Suche nach einem Therapieplatz und wende mich daher an Sie. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich eine passende Wahl, sofern Sie das anbieten.

Koennten Sie mir bitte kurz sagen, wie lange man bei Ihnen aktuell etwa warten muss? Auch eine grobe Zahl hilft mir schon.

Viele Gruesse
{name}""",

"""Hallo {anrede},

ich moechte mich nach einem Therapieplatz bei Ihnen erkundigen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls Sie {therapieform} anbieten, waere das fuer mich sehr gut geeignet.

Ich waere Ihnen dankbar fuer eine kurze Rueckmeldung zur ungefaehren Wartezeit bei Ihnen.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich suche derzeit einen Therapieplatz und schreibe Ihnen deshalb. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich besonders geeignet, falls das zu Ihrem Angebot gehoert.

Eine kurze Angabe dazu, wie lange die Wartezeit bei Ihnen ungefaehr ist, wuerde mir sehr helfen.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich melde mich, da ich einen Therapieplatz suche. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Bieten Sie {therapieform} an, waere das fuer mich der passende Ansatz.

Ich waere Ihnen sehr dankbar, wenn Sie mir kurz sagen koennten, wie lange die Wartezeit bei Ihnen momentan ist.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

ich bin auf der Suche nach ambulanter Psychotherapie fuer Erwachsene. {situation} Ich bin gesetzlich versichert.

Falls {therapieform} zu Ihrem Angebot gehoert, waere das fuer mich genau richtig.

Koennten Sie mir kurz mitteilen, wie lange die Wartezeit bei Ihnen aktuell ungefaehr ist? Das waere eine grosse Hilfe fuer mich.

Mit freundlichen Gruessen
{name}""",

"""Sehr geehrte {anrede},

ich moechte mich bei Ihnen wegen eines Therapieplatzes melden. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Sofern Sie {therapieform} anbieten, waere das fuer mich besonders passend.

Ich waere Ihnen dankbar, wenn Sie mir kurz eine ungefaehre Wartezeit nennen koennten, das hilft mir bei meiner Krankenkasse weiter.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich suche momentan nach einem Therapieplatz. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich eine sehr gute Option, falls Sie das anbieten.

Wuerden Sie mir bitte kurz schreiben, wie lange die Wartezeit bei Ihnen aktuell etwa dauert?

Viele Gruesse
{name}""",

"""Sehr geehrte {anrede},

ich moechte gerne bei Ihnen wegen eines Therapieplatzes anfragen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

{therapieform} waere fuer mich sehr passend, falls Sie das anbieten.

Da ich eine kurze, konkrete Angabe fuer meine Krankenkasse brauche, waere ich Ihnen dankbar, wenn Sie mir die ungefaehre Wartezeit bei Ihnen nennen koennten.

Mit freundlichen Gruessen
{name}""",

"""Guten Tag {anrede},

ich schreibe Ihnen, weil ich einen Therapieplatz suche und bei Ihnen anfragen moechte. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Falls {therapieform} zu Ihrem Angebot zaehlt, waere das fuer mich sehr gut geeignet.

Koennten Sie mir kurz eine ungefaehre Angabe zur Wartezeit geben? Auch eine grobe Schaetzung waere fuer mich schon hilfreich.

Freundliche Gruesse
{name}""",

"""Hallo {anrede},

ich bin auf der Suche nach einem Therapieplatz und melde mich deshalb bei Ihnen. {situation} Ich bin gesetzlich versichert und suche ambulante Psychotherapie fuer Erwachsene.

Sollten Sie {therapieform} anbieten, waere das fuer mich der passende Weg.

Ich waere Ihnen sehr dankbar, wenn Sie mir kurz mitteilen koennten, wie lange die Wartezeit bei Ihnen momentan ungefaehr ist.

Mit freundlichen Gruessen
{name}""",

]
