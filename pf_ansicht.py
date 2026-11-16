"""Schachbrett im Lichess-Stil als SVG (nur Standardbibliothek).

Aussehen wie bei Lichess: braune Felder, Koordinaten in den Randfeldern, Figuren des Satzes „cburnett“ (pf_pieces.py), halbdurchsichtige Pfeile,
gelbgrün hinterlegter letzter Zug, Ringe auf Zielfeldern. Die Figuren sind gezeichnete Pfade und keine Schriftzeichen und sehen auf jedem Gerät gleich
aus. Das Brett steht aus Sicht der ziehenden Seite (flip=True: Schwarz unten).
"""
from __future__ import annotations

import math
from html import escape

import pf_brett as tb
from pf_pieces import PIECE_SIZE, PIECE_SVG

CELL = PIECE_SIZE          # ein Feld ist so groß wie eine Figur (45 Einheiten)
SIZE = 8 * CELL
LIGHT, DARK = "#f0d9b5", "#b58863"
LAST_MOVE = "rgba(155,199,0,0.41)"
RING = "rgba(20,85,30,0.5)"
ARROW = "#15781b"


def _zelle(sq: int, flip: bool) -> tuple[int, int]:
    """Spalte und Zeile des Feldes im Bild (0 = links/oben); gedreht für das Brett aus Sicht von Schwarz."""
    col, zeile = sq % 8, 7 - sq // 8
    return (7 - col, 7 - zeile) if flip else (col, zeile)


def _mitte(sq: int, flip: bool = False) -> tuple[float, float]:
    col, zeile = _zelle(sq, flip)
    return col * CELL + CELL / 2, zeile * CELL + CELL / 2


def _f(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def brett_svg(figuren: dict, pfeile=(), markiert=(), letzter: tuple[int, int] | None = None, label: str = "Schachstellung", flip: bool = False) -> str:
    """figuren: Feld -> (Farbe, Buchstabe PNBRQK); pfeile: (von, nach)-Felder; markiert: Felder mit Ring; letzter: (von, nach) des letzten Zugs;
    flip: Brett aus Sicht von Schwarz."""
    out = [f'<svg viewBox="0 0 {SIZE} {SIZE}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escape(label, quote=True)}" '
           'style="max-width:30rem;width:100%;height:auto">']
    for sq in range(64):
        col, zeile = _zelle(sq, flip)
        fill = LIGHT if (sq % 8 + sq // 8) % 2 == 1 else DARK
        out.append(f'<rect x="{col * CELL}" y="{zeile * CELL}" width="{CELL}" height="{CELL}" fill="{fill}"/>')
    for sq in (letzter or ()):
        col, zeile = _zelle(sq, flip)
        out.append(f'<rect class="last-move" x="{col * CELL}" y="{zeile * CELL}" width="{CELL}" height="{CELL}" fill="{LAST_MOVE}"/>')
    out.append('<g font-family="sans-serif" font-size="10" font-weight="bold">')   # Koordinaten in den Randfeldern, Farbe des anderen Feldtyps
    for z in range(8):
        rank_idx = z if flip else 7 - z
        file_idx = 7 if flip else 0
        farbe = DARK if (file_idx + rank_idx) % 2 == 1 else LIGHT
        out.append(f'<text x="2" y="{z * CELL + 11}" fill="{farbe}">{rank_idx + 1}</text>')
    for c in range(8):
        file_idx = 7 - c if flip else c
        rank_idx = 7 if flip else 0
        farbe = DARK if (file_idx + rank_idx) % 2 == 1 else LIGHT
        out.append(f'<text x="{c * CELL + CELL - 2}" y="{SIZE - 3}" text-anchor="end" fill="{farbe}">{tb.FILES[file_idx]}</text>')
    out.append("</g>")
    for sq in markiert:
        x, y = _mitte(sq, flip)
        out.append(f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(CELL * 0.42)}" fill="none" stroke="{RING}" stroke-width="{_f(CELL * 0.1)}"/>')
    for sq, (farbe, art) in sorted(figuren.items()):
        col, zeile = _zelle(sq, flip)
        out.append(f'<g class="piece" transform="translate({col * CELL} {zeile * CELL})">{PIECE_SVG[farbe + art]}</g>')
    for a, b in pfeile:                                  # Pfeile über den Figuren, halb durchsichtig
        (x1, y1), (x2, y2) = _mitte(a, flip), _mitte(b, flip)
        d = math.hypot(x2 - x1, y2 - y1)
        if d == 0:
            continue
        ux, uy = (x2 - x1) / d, (y2 - y1) / d
        px, py = -uy, ux
        sx, sy = x1 + ux * 8, y1 + uy * 8
        tx, ty = x2 - ux * 3, y2 - uy * 3
        bx, by = tx - ux * 15, ty - uy * 15
        kopf = f"{_f(tx)},{_f(ty)} {_f(bx + px * 9)},{_f(by + py * 9)} {_f(bx - px * 9)},{_f(by - py * 9)}"
        out.append(f'<g opacity="0.8" fill="{ARROW}" stroke="{ARROW}"><line x1="{_f(sx)}" y1="{_f(sy)}" x2="{_f(bx + ux * 2)}" y2="{_f(by + uy * 2)}" '
                   f'stroke-width="6.5" stroke-linecap="round"/><polygon points="{kopf}" stroke="none"/></g>')  # lint-ok: dezimalpunkt
    out.append("</svg>")
    return "\n".join(out)
