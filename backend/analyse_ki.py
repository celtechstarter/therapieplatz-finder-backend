"""Bewertung eines Praxisprofils durch Claude.

Sicherheit: Der Profiltext stammt von fremden Websites. Ein präparierter
Text könnte versuchen, die KI zu zusätzlichen Feldern zu verleiten, etwa
einer anderen E-Mail-Adresse ("Prompt Injection"). Deshalb wird aus jeder
Antwort nur übernommen, was in `ERLAUBTE_FELDER` steht. Den Text der
Anfrage-Mail schreibt die KI nicht, der kommt aus festen Vorlagen.
"""
import json
import os
import re
import time

import anthropic

MODELL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")
ERLAUBTE_FELDER = {"GKV_akzeptiert", "Freie_Plaetze", "Notiz"}
ERLAUBTE_WERTE = (True, False, "unklar")
VOLLTEXT_MAX = 1500  # Zeichen; spart Kosten, mehr bringt der KI nichts

SYSTEM_PROMPT = """Du bist ein Assistent, der Therapeutenprofile analysiert.
Antworte ausschließlich mit einem validen JSON-Objekt, ohne Markdown, ohne Erklärungen."""

_client = None


def ki_client():
    """Baut den API-Client erst beim ersten Gebrauch. So brauchen Tests und
    der Modus --ohne-ki keinen API-Schlüssel."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def baue_prompt(profil):
    kompakt = {k: v for k, v in profil.items() if k != "volltext"}
    kompakt["volltext_auszug"] = (profil.get("volltext") or "")[:VOLLTEXT_MAX]
    profil_text = json.dumps(kompakt, ensure_ascii=False, indent=1)
    return f"""Analysiere dieses Therapeutenprofil und antworte mit einem JSON-Objekt mit exakt diesen Feldern:

{{
  "GKV_akzeptiert": true | false | "unklar",
  "Freie_Plaetze": true | false | "unklar",
  "Notiz": "..."
}}

Regeln:
- GKV_akzeptiert: true wenn GKV/gesetzlich erwähnt (auch Kostenerstattungsverfahren); false wenn nur PKV/Privat; sonst "unklar"
- Freie_Plaetze: true wenn explizit freie Plätze; false wenn Warteliste/lange Wartezeit; sonst "unklar"
- Notiz: 1-2 Sätze, warum dieses Profil passt oder was zu beachten ist

Profil:
{profil_text}"""


def lies_ki_antwort(rohtext):
    """Holt das JSON-Objekt aus der Antwort, auch wenn Text oder ein
    Codeblock drumherum steht. Abgeschnittene oder kaputte Antworten
    ergeben None statt eines Absturzes."""
    if not rohtext:
        return None
    treffer = re.search(r"\{.*\}", rohtext.strip(), re.DOTALL)
    if not treffer:
        return None
    try:
        return json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return None


def pruefe_bewertung(daten):
    """Prüft die gelesene Antwort. None, wenn GKV_akzeptiert fehlt oder einen
    unerlaubten Wert hat. Ein unerlaubter Wert bei Freie_Plaetze wird zu
    "unklar". Zurück kommen nur die erlaubten Felder."""
    if not isinstance(daten, dict) or daten.get("GKV_akzeptiert", "fehlt") not in ERLAUBTE_WERTE:
        return None
    bewertung = {k: v for k, v in daten.items() if k in ERLAUBTE_FELDER}
    if "Freie_Plaetze" in bewertung and bewertung["Freie_Plaetze"] not in ERLAUBTE_WERTE:
        bewertung["Freie_Plaetze"] = "unklar"
    return bewertung


def frage_ki(profil, versuche=3, client=None, warten=time.sleep):
    """Fragt Claude nach einer Bewertung. Bis zu `versuche` Anläufe, dazwischen
    wachsende Pausen. Eine abgeschnittene Antwort (max_tokens) zählt als
    Fehlversuch. Gibt die geprüfte Bewertung oder None zurück."""
    client = client or ki_client()
    prompt = baue_prompt(profil)
    for versuch in range(1, versuche + 1):
        try:
            antwort = client.messages.create(
                model=MODELL, max_tokens=2048, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if antwort.stop_reason == "max_tokens":
                raise ValueError("Antwort abgeschnitten (max_tokens)")
            rohtext = antwort.content[0].text
            bewertung = pruefe_bewertung(lies_ki_antwort(rohtext))
            if bewertung is None:
                raise ValueError(f"Antwort ungültig: {rohtext[:200]!r}")
            return bewertung
        except Exception as fehler:
            print(f"  Fehler (Versuch {versuch}/{versuche}): {fehler}")
        if versuch < versuche:
            warten(5 * versuch)
    return None
