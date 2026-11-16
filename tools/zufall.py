"""Zufallspartien mit python-chess (nur Test und Messung, nicht die App): gemeinsame Quelle für tests/ und tools/messung.py."""
import random

import chess


def zufallsspiel(seed: int, laenge: int = 90) -> tuple[list[str], chess.Board]:
    """SAN-Liste einer Zufallspartie (mit Vorliebe für Bauernzüge, sonst kommen Umwandlung und en passant kaum vor) und das Brett am Ende."""
    rng, b, sans = random.Random(seed), chess.Board(), []
    for _ in range(laenge):
        zuege = sorted(b.legal_moves, key=lambda m: m.uci())
        if not zuege or b.is_insufficient_material():
            break
        bauern = [m for m in zuege if b.piece_type_at(m.from_square) == chess.PAWN]
        m = rng.choice(bauern) if bauern and rng.random() < 0.4 else rng.choice(zuege)
        sans.append(b.san(m))
        b.push(m)
    return sans, b


def zeilen(zellen: list[str]) -> list[list[str]]:
    z = [zellen[i:i + 2] for i in range(0, len(zellen), 2)]
    return [r + [""] * (2 - len(r)) for r in z]
