"""Orakel-Test der Schachregeln gegen python-chess (nur im Test): bekannte Zählungen (Perft), Zuglisten, SAN, FEN und Partieende in Zufallspartien."""
import random

import chess
import pytest

import pf_brett as B

PERFT = [
    ("Grundstellung", B.START_FEN, [20, 400, 8902]),
    ("Kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039, 97862]),
    ("Stellung 3", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812]),
    ("Stellung 4", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467]),
    ("Stellung 5", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]),
    ("Stellung 6", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", [46, 2079, 89890]),
]


def perft(st: B.Stellung, tiefe: int) -> int:
    zuege = st.legale_zuege()
    if tiefe == 1:
        return len(zuege)
    return sum(perft(st.ausfuehren(z), tiefe - 1) for z in zuege)


@pytest.mark.parametrize("name,fen,zahlen", PERFT, ids=[p[0] for p in PERFT])
def test_perft_bekannte_zaehlungen(name, fen, zahlen):
    st = B.Stellung.aus_fen(fen)
    for tiefe, soll in enumerate(zahlen, start=1):
        assert perft(st, tiefe) == soll, (name, tiefe)


def uci_menge(zuege) -> set[str]:
    return {z.uci for z in zuege}


def waehle(rng, zuege, ist_bauer):
    """Zufallszug, mit Vorliebe für Bauernzüge: sonst kommen en passant und Umwandlung in Zufallspartien kaum vor."""
    bauern = [z for z in zuege if ist_bauer(z)]
    return rng.choice(bauern) if bauern and rng.random() < 0.5 else rng.choice(zuege)


def zufallspartie(seed: int, laenge: int = 140):
    """Spielt eine Zufallspartie in beiden Implementierungen parallel und vergleicht nach jedem Zug."""
    rng = random.Random(seed)
    ref, mein = chess.Board(), B.Stellung.start()
    for ply in range(laenge):
        ref_zuege = sorted(m.uci() for m in ref.legal_moves)
        assert sorted(uci_menge(mein.legale_zuege())) == ref_zuege, (seed, ply, ref.fen())
        assert mein.im_schach() == ref.is_check(), (seed, ply)
        ende_ref = "matt" if ref.is_checkmate() else "patt" if ref.is_stalemate() else "material" if ref.is_insufficient_material() else None
        assert mein.ende() == ende_ref, (seed, ply, ref.fen())
        if not ref_zuege or ende_ref:
            return ply
        m = waehle(rng, sorted(ref.legal_moves, key=lambda x: x.uci()), lambda x: ref.piece_type_at(x.from_square) == chess.PAWN)
        zug = B.zug_aus_uci(m.uci())
        assert mein.san(zug) == ref.san(m), (seed, ply, ref.fen(), m.uci())
        ref.push(m)
        mein = mein.ausfuehren(zug)
        assert mein.fen() == ref.fen(), (seed, ply)
        assert mein.platzierung() == ref.board_fen()
    return laenge


def test_zufallspartien_gleich_python_chess():
    laengen = [zufallspartie(seed) for seed in range(60)]
    assert sum(laengen) > 2000          # die Zufallspartien sind lang genug, um Rochade, en passant und Umwandlung zu treffen


def test_zufallspartien_treffen_die_sonderfaelle():
    """Die Zufallsläufe berühren Rochade, en passant, Umwandlung, Schach und Matt; sonst wäre der Vergleich zu schwach."""
    gesehen = {"rochade": 0, "ep": 0, "umw": 0, "matt": 0, "mehrdeutig": 0}
    for seed in range(150):
        rng, mein = random.Random(seed), B.Stellung.start()
        for _ in range(160):
            zuege = mein.legale_zuege()
            if not zuege:
                gesehen["matt"] += mein.im_schach()
                break
            z = waehle(rng, zuege, lambda x: mein.figuren[x.von][1] == "P")
            art = mein.figuren[z.von][1]
            gesehen["rochade"] += art == "K" and abs(z.nach - z.von) == 2
            gesehen["ep"] += art == "P" and z.nach == mein.ep and z.von % 8 != z.nach % 8
            gesehen["umw"] += bool(z.umw)
            gesehen["mehrdeutig"] += sum(1 for y in zuege if y.nach == z.nach and y != z and mein.figuren[y.von][1] == art and art != "P") > 0
            mein = mein.ausfuehren(z)
    assert all(v > 0 for v in gesehen.values()), gesehen


@pytest.mark.parametrize("fen,erwartet", [
    ("8/8/8/8/8/8/8/K1k5 w - - 0 1", True),                       # König gegen König
    ("8/8/8/8/8/8/8/KBk5 w - - 0 1", True),                       # ein Läufer
    ("8/8/8/8/8/8/8/KNk5 w - - 0 1", True),                       # ein Springer
    ("8/8/8/8/8/8/8/KNNk4 w - - 0 1", False),                     # zwei Springer können (mit Hilfe des Gegners) mattsetzen
        ("8/8/8/8/8/8/1b6/K1k5 w - - 0 1", True),
    ("8/8/8/8/8/8/8/KPk5 w - - 0 1", False),
])
def test_zu_wenig_material_wie_python_chess(fen, erwartet):
    ref = chess.Board(fen)
    mein = B.Stellung.aus_fen(fen)
    assert mein.zu_wenig_material() == ref.is_insufficient_material()


def test_gleichfarbige_laeufer_gegen_python_chess():
    for fen in ["8/8/8/8/8/8/8/KB1bk3 w - - 0 1", "8/8/8/8/8/8/8/KBb1k3 w - - 0 1", "8/8/8/8/8/8/8/K1B1kb2 w - - 0 1"]:
        ref = chess.Board(fen)
        assert B.Stellung.aus_fen(fen).zu_wenig_material() == ref.is_insufficient_material(), fen


def test_wiederholung_und_75_zuege_wie_python_chess():
    # fünfmal Springer hin und her: die Stellung der Grundstellung kehrt nach je vier Halbzügen wieder
    ref, mein = chess.Board(), B.Stellung.start()
    zaehler = {mein.schluessel(): 1}
    for i, uci in enumerate(["g1f3", "g8f6", "f3g1", "f6g8"] * 4):
        ref.push_uci(uci)
        mein = mein.ausfuehren(B.zug_aus_uci(uci))
        zaehler[mein.schluessel()] = zaehler.get(mein.schluessel(), 0) + 1
        assert (zaehler[mein.schluessel()] >= 5) == ref.is_fivefold_repetition(), i
    assert ref.is_fivefold_repetition() and B.partieende(mein, zaehler[mein.schluessel()]) == "fuenffach"
    assert B.partieende(B.Stellung.aus_fen("8/8/8/8/8/8/8/KRk5 w - - 149 90"), 1) is None
    assert B.partieende(B.Stellung.aus_fen("4k3/8/8/8/8/8/8/KR6 w - - 150 90"), 1) == "75"


def test_san_beispiele():
    st = B.Stellung.start()
    assert st.san(B.zug_aus_uci("e2e4")) == "e4"
    assert st.san(B.zug_aus_uci("g1f3")) == "Nf3"
    # Zwei Springer können nach d2: Zusatz nach Spalte; Matt-Zeichen
    st = B.Stellung.aus_fen("4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1")
    assert st.san(B.zug_aus_uci("b1d2")) == "Nbd2" and st.san(B.zug_aus_uci("f3d2")) == "Nfd2"
    # Zwei Türme auf derselben Spalte: Zusatz nach Reihe; Umwandlung mit Schach
    st = B.Stellung.aus_fen("4k3/8/8/R7/8/8/8/R3K3 w - - 0 1")
    assert st.san(B.zug_aus_uci("a1a3")) == "R1a3" and st.san(B.zug_aus_uci("a5a3")) == "R5a3"
    st = B.Stellung.aus_fen("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert st.san(B.zug_aus_uci("a7a8q")) == "a8=Q+" and st.san(B.zug_aus_uci("a7a8n")) == "a8=N"
    # Drei Damen: Zusatz Feld
    st = B.Stellung.aus_fen("4k3/8/8/8/Q2Q3Q/8/8/K7 w - - 0 1")
    ref = chess.Board(st.fen())
    for m in ref.legal_moves:
        assert st.san(B.zug_aus_uci(m.uci())) == ref.san(m)


def test_en_passant_und_rochade_gegen_python_chess():
    ref, mein = chess.Board(), B.Stellung.start()
    for uci in ["e2e4", "a7a6", "e4e5", "d7d5"]:
        ref.push_uci(uci)
        mein = mein.ausfuehren(B.zug_aus_uci(uci))
    assert mein.fen() == ref.fen() and "d6" in mein.fen()
    assert mein.san(B.zug_aus_uci("e5d6")) == ref.san(chess.Move.from_uci("e5d6")) == "exd6"
    nach = mein.ausfuehren(B.zug_aus_uci("e5d6"))
    assert nach.platzierung() == "rnbqkbnr/1pp1pppp/p2P4/8/8/8/PPPP1PPP/RNBQKBNR"      # der Bauer d5 ist geschlagen
    # Rochade unter Schach, durch ein bedrohtes Feld und mit verlorenem Recht
    for fen in ["r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1", "r3k2r/8/8/8/8/3r4/8/R3K2R w KQkq - 0 1",
                "r3k2r/8/8/8/8/8/8/R3K2R w Kkq - 0 1", "r3k2r/8/8/8/8/8/8/Rn2K2R w KQkq - 0 1", "4k3/8/8/8/8/8/8/R3K2r w Q - 0 1"]:
        assert sorted(z.uci for z in B.Stellung.aus_fen(fen).legale_zuege()) == sorted(m.uci() for m in chess.Board(fen).legal_moves), fen
