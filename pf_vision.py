"""Zugliste aus einem Foto mit einem Vision-Sprachmodell (Claude, Anthropic-API) lesen: der generische Weg für Formulare beliebiger Spieler und Vorlagen.

Das Schach-Modell in `pf_erkenner` ist klein, schnell und lokal, aber auf englische Notation und wenige Handschriften trainiert. Ein Vision-Sprachmodell liest dagegen auch
fremde Handschriften, deutsche Buchstaben (S, L, T, D) und andere Vorlagen und liest die gedruckten Zugnummern mit, die die Zeilen eindeutig zuordnen.
Es schreibt ab, was dasteht, und verbessert nichts: Die Regelprüfung (`pf_pruefung`) kommt danach wie bei abgetipptem Text, und unleserliche Zeichen kommen als „?“.

**Datenschutz:** Das Bild verlässt den Rechner und geht an Anthropic. Auf Formularen stehen Namen der Spieler. Ist das Raster gefunden, wird nur die Zugtabelle geschickt (Kopfzeile mit Namen
abgeschnitten), sonst das ganze Foto. Der API-Schlüssel gehört dem Nutzer, steht nur in der Sitzung und wird nirgends gespeichert.
"""
from __future__ import annotations

import base64
import io
import json
import os

from PIL import Image

import pf_raster as R

MODELL = "claude-opus-5-5"
MAX_SEITE = 1568                 # längste Bildseite je Bild (größere Bilder werden serverseitig verkleinert)
MAX_TOKENS = 16000
BETA_FALLBACK = "server-side-fallback-2026-07-01"

SCHEMA = {
    "type": "object",
    "properties": {
        "zeilen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nr": {"type": "integer"},
                    "weiss": {"type": "string"},
                    "schwarz": {"type": "string"},
                },
                "required": ["nr", "weiss", "schwarz"],
                "additionalProperties": False,
            },
        },
        "hinweise": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["zeilen", "hinweise"],
    "additionalProperties": False,
}

ANWEISUNG = """Transcribe the handwritten chess moves from the attached scoresheet image(s).
The sheet has numbered rows (the printed move number is in the narrow first column of each block) and, per row, one column for White and one for Black.
{blocks}
Rules:
- Copy each cell exactly as written. Keep the notation of the writer: German letters (K D T L S) or English letters (K Q R B N), "x" for captures, "+" and "#", "0-0" or "O-O" for castling. Do not translate letters, do not add or remove characters.
- Do NOT correct anything and do NOT use chess knowledge to guess a move: the moves are checked by a rules engine afterwards. If a character is illegible, write "?" in its place (for example "S?3"); if a whole cell is illegible, write "?".
- Empty cells are empty strings. Crossed-out or overwritten moves: give the final valid reading, and mention it in "hinweise".
- "nr" is the printed move number of the row. Include every row that has at least one move. Ignore header, footer and any result circles.
- If the result (1-0, 0-1, 1/2-1/2) or other remarks are written next to the moves, mention them in "hinweise" rather than as a move.
Return only the JSON."""


class VisionFehler(Exception):
    """Fehler, dessen Text dem Nutzer gezeigt werden kann."""


def schluessel_aus_umgebung() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def sdk_vorhanden() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def als_jpeg(bild: Image.Image, max_seite: int = MAX_SEITE, qualitaet: int = 90) -> bytes:
    b = bild.convert("RGB")
    if max(b.size) > max_seite:
        f = max_seite / max(b.size)
        b = b.resize((max(1, round(b.width * f)), max(1, round(b.height * f))), Image.LANCZOS)
    puffer = io.BytesIO()
    b.save(puffer, format="JPEG", quality=qualitaet)
    return puffer.getvalue()


def bilder_fuer_anfrage(bild: Image.Image, raster: R.Raster | None) -> tuple[list[Image.Image], str]:
    """Bilder, die an das Modell gehen, und die Beschreibung für die Anweisung. Mit gefundenem Raster: je Block ein Bild der entzerrten Tabelle (ohne Kopfzeile, ohne Namen);
    sonst das ganze Foto."""
    if raster is not None and raster.ecken is not None:
        tabelle = R.zugeschnitten(R.vorbereiten(bild), raster)
        n = raster.bloecke
        teile = [tabelle.crop((round(i * tabelle.width / n), 0, round((i + 1) * tabelle.width / n), tabelle.height)) for i in range(n)]
        text = (f"There are {n} image(s), one per block of rows, from left to right; the blocks continue the move numbers (for example rows 1 to {raster.zeilen} in the first block). "
                "The table was cropped: names and header are not included.")
        return teile, text
    return [R.vorbereiten(bild)], "There is one image: the whole sheet, which may include a header and other printed text. Only transcribe the moves."


def inhalt(bilder: list[Image.Image], beschreibung: str) -> list[dict]:
    blocks: list[dict] = []
    for b in bilder:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(als_jpeg(b)).decode("ascii")}})
    blocks.append({"type": "text", "text": ANWEISUNG.format(blocks=beschreibung)})
    return blocks


def anfrage(bilder: list[Image.Image], beschreibung: str) -> dict:
    """Parameter der Anfrage an die Nachrichten-API (mit Rückfall bei Ablehnung, wie für dieses Modell üblich)."""
    return {
        "model": MODELL,
        "max_tokens": MAX_TOKENS,
        "betas": [BETA_FALLBACK],
        "fallbacks": "default",
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        "messages": [{"role": "user", "content": inhalt(bilder, beschreibung)}],
    }


def zeilen_aus_antwort(daten: dict) -> tuple[list[list[str]], list[str]]:
    """Zeilen (Weiß, Schwarz) nach der gedruckten Zugnummer geordnet; fehlende Nummern bleiben als leere Zeilen stehen, doppelte Nummern werden gemeldet."""
    hinweise = [str(h) for h in daten.get("hinweise", [])]
    nach_nr: dict[int, list[str]] = {}
    for z in daten["zeilen"]:
        nr = int(z["nr"])
        if nr < 1 or nr > 200:
            hinweise.append(f"Zeile mit unplausibler Nummer {nr} ignoriert.")
            continue
        if nr in nach_nr:
            hinweise.append(f"Die Zugnummer {nr} kam doppelt vor; die erste Lesung gilt.")
            continue
        nach_nr[nr] = [str(z.get("weiss", "")).strip(), str(z.get("schwarz", "")).strip()]
    if not nach_nr:
        return [], hinweise
    zeilen = [nach_nr.get(i, ["", ""]) for i in range(1, max(nach_nr) + 1)]
    luecken = [i for i in range(1, max(nach_nr) + 1) if i not in nach_nr]
    if luecken:
        hinweise.append("Keine Zeile gelesen für Zug " + ", ".join(map(str, luecken[:10])) + (" …" if len(luecken) > 10 else "") + ".")
    return zeilen, hinweise


def lies_zeilen(bild: Image.Image, raster: R.Raster | None, schluessel: str, client=None) -> tuple[list[list[str]], list[str]]:
    """Liest die Zugliste. `client` kann für Tests ein Ersatz sein; sonst wird der Client des SDK mit dem Schlüssel des Nutzers gebaut.
    Gibt Zeilen und Hinweise zurück; Fehler (kein Schlüssel, Netz, Ablehnung, unlesbare Antwort) kommen als VisionFehler mit lesbarem Text."""
    if client is None:
        if not schluessel:
            raise VisionFehler("Es fehlt ein API-Schlüssel.")
        try:
            import anthropic
        except ImportError as e:
            raise VisionFehler("Das Paket `anthropic` ist nicht installiert.") from e
        client = anthropic.Anthropic(api_key=schluessel)
    bilder, beschreibung = bilder_fuer_anfrage(bild, raster)
    try:
        antwort = client.beta.messages.create(**anfrage(bilder, beschreibung))
    except Exception as e:                       # SDK-Fehler: Klasse bestimmt den Text, der Rest ist ein Netz- oder Dienstproblem
        raise VisionFehler(_fehlertext(e)) from e
    if getattr(antwort, "stop_reason", "") == "refusal":
        raise VisionFehler("Das Modell hat die Anfrage abgelehnt.")
    if getattr(antwort, "stop_reason", "") == "max_tokens":
        raise VisionFehler("Die Antwort wurde abgeschnitten (zu viele Zeilen für eine Anfrage). Teile das Foto in einzelne Blöcke.")
    text = next((b.text for b in antwort.content if getattr(b, "type", "") == "text"), "")
    try:
        daten = json.loads(text)
        return zeilen_aus_antwort(daten)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise VisionFehler("Die Antwort des Modells war nicht lesbar.") from e


def _fehlertext(e: Exception) -> str:
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    if name == "AuthenticationError" or status == 401:
        return "Der API-Schlüssel wurde nicht akzeptiert."
    if name == "PermissionDeniedError" or status == 403:
        return "Der API-Schlüssel hat keine Berechtigung für dieses Modell."
    if name == "RateLimitError" or status == 429:
        return "Zu viele Anfragen oder das Limit des Schlüssels ist erreicht. Versuche es später noch einmal."
    if name == "BadRequestError" or status == 400:
        return f"Die Anfrage wurde abgelehnt: {getattr(e, 'message', e)}"
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Keine Verbindung zur Anthropic-API."
    return f"Fehler bei der Anfrage ({name})."
