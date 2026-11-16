"""Orakel-Tests der Prüfung gegen python-chess (nur im Test): Zufallspartien als Formular, Störungen, erfundene Züge, Begründungen."""
import random

import chess
import pytest

import pf_brett as B
import pf_logik as L
import pf_pruefung as P
from pf_notation import lese


from zufall import zeilen, zufallsspiel  # noqa: E402  (tools/zufall.py, von conftest.py auf den Suchpfad gesetzt)


SEEDS = list(range(30))


@pytest.mark.parametrize("sprache", ["en", "de"])
def test_zufallspartien_werden_ohne_befund_gelesen(sprache):
    for seed in SEEDS:
        sans, ref = zufallsspiel(seed)
        zellen = [L.in_schreibweise(s, sprache) for s in sans]
        p = P.pruefe(zeilen(zellen))
        assert [e.status for e in p.zuege] == ["ok"] * len(sans), (seed, sprache, [(e.roh, e.status) for e in p.zuege if e.status != "ok"][:3])
        assert [e.san for e in p.zuege] == sans, seed
        assert p.datenbanktauglich(), seed
        ende = "matt" if ref.is_checkmate() else "patt" if ref.is_stalemate() else "material" if ref.is_insufficient_material() else None
        assert p.ende == ende, (seed, ref.fen())


def test_zufallspartien_gleiche_pgn_wie_python_chess():
    """Das exportierte PGN liest python-chess ohne Fehler und mit denselben Zügen und Kopfzeilen zurück."""
    import io

    import chess.pgn

    import pf_pgn as G
    for seed in SEEDS[:12]:
        sans, ref = zufallsspiel(seed)
        p = P.pruefe(zeilen([L.in_schreibweise(s, "de") for s in sans]))
        text, _ = L.pgn_text({"White": "Muster, Max", "Black": "Beispiel, Berta", "Date": "15.11.2026", "Result": ""}, p, L.EXPORT_SAUBER)
        partie = chess.pgn.read_game(io.StringIO(text))
        assert not partie.errors, (seed, partie.errors)
        assert [partie.board().variation_san([m]) if False else m.uci() for m in partie.mainline_moves()] == [m.uci() for m in ref.move_stack], seed
        assert partie.headers["White"] == "Muster, Max" and partie.headers["Date"] == "2026.11.15"
        assert all(len(zeile) <= G.UMBRUCH for zeile in text.splitlines())


def test_ohne_schlag_und_schachzeichen_gleiche_zuege():
    for seed in SEEDS:
        sans, _ = zufallsspiel(seed)
        zellen = [s.replace("x", "").replace("+", "").replace("#", "") for s in sans]
        p = P.pruefe(zeilen(zellen))
        bad = [(e.roh, e.status, e.san) for e in p.zuege if e.status not in ("ok", "hinweis") or e.san != sans[e.ply]]
        # Ohne x können zwei Bauern oder Figuren verwechselbar werden; dann muss die App „unklar“ sagen, aber nie still einen falschen Zug nehmen.
        for e in p.zuege:
            if e.san != sans[e.ply]:
                assert e.status == "unklar", (seed, bad[:3])
                assert sans[e.ply] in [k.san for k in e.kandidaten], (seed, e.roh)
                break
        else:
            assert not bad, (seed, bad[:3])


def test_ausfuehrliche_schreibweise():
    for seed in SEEDS:
        ref, zellen = chess.Board(), []
        for san in zufallsspiel(seed)[0]:
            m = ref.parse_san(san)
            kurz = "" if m.promotion or ref.piece_type_at(m.from_square) == chess.PAWN else ref.san(m)[0]
            if ref.is_castling(m):
                zellen.append(san.rstrip("+#"))
            else:
                zellen.append(f"{'' if ref.piece_type_at(m.from_square) == chess.PAWN else kurz.replace('N', 'S').replace('B', 'L')}{chess.square_name(m.from_square)}-{chess.square_name(m.to_square)}"
                              + (f"={chess.piece_symbol(m.promotion).upper()}" if m.promotion else ""))
            ref.push(m)
        sans = zufallsspiel(seed)[0]
        p = P.pruefe(zeilen(zellen))
        assert all(e.status in ("ok", "hinweis") for e in p.zuege), (seed, [(e.roh, e.status) for e in p.zuege if e.status not in ("ok", "hinweis")][:3])
        assert [e.san for e in p.zuege] == sans, seed


def test_fehlende_zusaetze_werden_unklar_und_nennen_den_richtigen_zug():
    gesehen = 0
    for seed in SEEDS:
        sans, _ = zufallsspiel(seed)
        for i, s in enumerate(sans):
            kern = s.rstrip("+#")
            if len(kern) >= 4 and kern[0] in "NBRQ" and kern[1] in "abcdefgh12345678" and kern[2] in "abcdefgh12345678x" and not kern.endswith(("O-O", "O-O-O")) and "=" not in kern:
                ohne = list(sans)
                ohne[i] = kern[0] + kern[2:] if kern[2] != "x" else kern[0] + kern[2:]
                if kern[1] in "abcdefgh" and kern[2] in "12345678":
                    ohne[i] = kern[0] + kern[2:]          # Nb1d2 -> Nd2
                p = P.pruefe(zeilen(ohne))
                e = p.zuege[i]
                assert all(x.status in ("ok", "hinweis") for x in p.zuege[:i]), (seed, i)
                assert e.status == "unklar", (seed, i, ohne[i])
                assert s in [k.san for k in e.kandidaten], (seed, i)
                assert not any(x.status in ("illegal", "nach_ende") for x in p.zuege[i:]) or p.zuege[i].kandidaten[0].san != s, (seed, i)
                gesehen += 1
                break
    assert gesehen >= 5


def figurzug_legal(b: chess.Board, fig: str, feld: int) -> bool:
    return any(b.piece_type_at(m.from_square) == chess.PIECE_SYMBOLS.index(fig.lower()) and m.to_square == feld for m in b.legal_moves)


def test_gefundene_zuege_stimmen_mit_den_legalen_zuegen_ueberein():
    """Für jede Figur und jedes Feld: ein legaler Zug passt genau dann, wenn python-chess einen solchen legalen Zug kennt."""
    geprueft = 0
    lesungen = {(fig, feld): lese(fig + chess.square_name(feld)) for fig in "NBRQK" for feld in range(64)}
    for seed in range(8):
        sans, _ = zufallsspiel(seed, 80)
        ref, st = chess.Board(), B.Stellung.start()
        for s in sans:
            for (fig, feld), les in lesungen.items():
                assert bool(P.passende(st, les)[0]) == figurzug_legal(ref, fig, feld), (seed, ref.fen(), fig, chess.square_name(feld))
                geprueft += 1
            for rochade in ("O-O", "O-O-O"):
                gibt = any(ref.is_castling(m) and (ref.is_kingside_castling(m) == (rochade == "O-O")) for m in ref.legal_moves)
                assert bool(P.passende(st, lese(rochade))[0]) == gibt, (seed, ref.fen(), rochade)
            m = ref.parse_san(s)
            ref.push(m)
            st = st.ausfuehren(B.zug_aus_uci(m.uci()))
    assert geprueft > 40000


def test_erfundene_zuege_sind_regelverstoesse_mit_begruendung():
    rng = random.Random(7)
    getestet = 0
    for seed in range(40):
        sans, _ = zufallsspiel(seed, 60)
        if len(sans) < 12:
            continue
        i = rng.randrange(6, len(sans))
        ref = chess.Board()
        for s in sans[:i]:
            ref.push_san(s)
        versuche = [(f, sq) for f in "NBRQK" for sq in range(64) if not figurzug_legal(ref, f, sq)]
        fig, sq = rng.choice(versuche)
        falsch = list(sans[:i]) + [fig + chess.square_name(sq)] + list(sans[i + 1:])
        p = P.pruefe(zeilen(falsch))
        e = p.zuege[i]
        assert all(x.status in ("ok", "hinweis") for x in p.zuege[:i]), (seed, i)
        assert e.status == "illegal", (seed, i, falsch[i], ref.fen())
        assert e.meldungen and e.meldungen[0].stufe == "fehler" and len(e.meldungen[0].text) > 20
        assert all(x.status == "nicht_pruefbar" for x in p.zuege[i + 1:]), seed
        for k in e.kandidaten:                                  # jeder Vorschlag ist wirklich legal
            assert ref.parse_san(k.san) in ref.legal_moves
        assert not p.datenbanktauglich()
        getestet += 1
    assert getestet >= 20


def test_begruendungen_im_einzelnen():
    def grund(fen: str, zelle: str) -> str:
        st = B.Stellung.aus_fen(fen)
        les = lese(zelle)
        assert not P.passende(st, les)[0], (fen, zelle)            # der Zug geht wirklich nicht
        return P.begruendung(st, les)

    assert "Auf h1 steht kein Turm" in grund("r3k2r/8/8/8/8/8/8/R3K1N1 w KQkq - 0 1", "0-0")
    assert "bedrohtes Feld ziehen (f1)" in grund("r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1", "0-0")
    assert "König steht im Schach" in grund("r3k2r/8/8/8/8/4r3/8/R3K2R w KQkq - 0 1", "0-0")
    assert "nicht mehr auf e1" in grund("r3k2r/8/8/8/8/8/8/R4K1R w KQkq - 0 1", "0-0")
    assert "Recht ist verfallen" in grund("r3k2r/8/8/8/8/8/8/R3K2R w Kkq - 0 1", "0-0-0")
    assert "Zwischen König und Turm steht noch eine Figur (b1)" in grund("r3k2r/8/8/8/8/8/8/RN2K2R w KQkq - 0 1", "0-0-0")
    assert "Weg von a1 nach a5 ist versperrt: Auf a2" in grund("4k3/8/8/8/8/8/PP6/RB2K3 w - - 0 1", "Ta5")
    assert "Springer ist gefesselt" in grund("4r3/8/8/8/8/8/4N3/4K3 w - - 0 1", "Sc3")
    assert "Ein König darf nicht ins Schach ziehen" in grund("4k3/8/8/8/8/8/r7/4K3 w - - 0 1", "Ke2")
    assert "steht im Schach, und dieser Zug beendet das Schach nicht" in grund("k3r3/8/8/8/8/8/8/R3K3 w - - 0 1", "Ta5")
    assert "eigene Figur" in grund("4k3/8/8/8/8/8/3P4/3QK3 w - - 0 1", "Dd2")
    assert "gehört Schwarz" in grund(B.START_FEN, "Sc6")
    assert "Springer von b1 und g1 kann d5 nicht" in grund(B.START_FEN, "Sd5")
    assert "Doppelschritt" in grund("4k3/8/8/8/8/4P3/8/4K3 w - - 0 1", "e5")
    assert "schlägt nicht geradeaus" in grund("4k3/8/8/4p3/4P3/8/8/4K3 w - - 0 1", "e5")
    assert "keine gegnerische Figur" in grund(B.START_FEN, "exd3")
    assert "Weiß hat keine Dame mehr" in grund("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "Da4")
    assert "Weiß hat keinen Springer mehr" in grund("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "Sc3")
    assert "Umwandlung gibt es nur" in grund("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "Ta4=D")


def test_wirklich_kein_zug_nach_matt_und_patt():
    kurz = ["f3", "e5", "g4", "Qh4#", "Nc3"]
    p = P.pruefe(zeilen(kurz))
    assert [e.status for e in p.zuege] == ["ok"] * 4 + ["nach_ende"] and p.ende == "matt"
    patt = "e3 a5 Qh5 Ra6 Qxa5 h5 h4 Rah6 Qxc7 f6 Qxd7+ Kf7 Qxb7 Qd3 Qxb8 Qh7 Qxc8 Kg6 Qe6".split()
    p = P.pruefe(zeilen(patt))
    assert p.ende == "patt" and all(e.status == "ok" for e in p.zuege) and p.datenbanktauglich()
    p = P.pruefe(zeilen(patt + ["Kf5"]))
    assert p.zuege[-1].status == "nach_ende" and "Patt" in p.zuege[-1].meldungen[0].text


def test_fuenffache_wiederholung_warnt_wie_python_chess():
    hin_und_her = ["Nf3", "Nf6", "Ng1", "Ng8"] * 4
    ref = chess.Board()
    for s in hin_und_her:
        ref.push_san(s)
    assert ref.is_fivefold_repetition()
    p = P.pruefe(zeilen(hin_und_her))
    assert all(e.status == "ok" for e in p.zuege)
    warn = [m.text for e in p.zuege for m in e.meldungen if m.stufe == "warnung"]
    assert len(warn) == 1 and "fünften Mal" in warn[0]


def test_lueckenzug_wird_aus_den_folgezuegen_ergaenzt():
    sans, _ = zufallsspiel(3, 30)
    for i in (4, 7, 10):
        luecke = list(sans)
        luecke[i] = ""
        p = P.pruefe(zeilen(luecke))
        e = p.zuege[i]
        assert e.status == "unklar" and "fehlt" in e.meldungen[0].text
        assert sans[i] in [k.san for k in e.kandidaten[:8]] or any(k.ganz for k in e.kandidaten), (i, [k.san for k in e.kandidaten])
        assert e.kandidaten[0].fortsetzung >= len(sans) - i - 1 or e.kandidaten[0].fortsetzung >= 40


def test_umwandlung_ohne_figur_fragt_nach():
    fen_zellen = ["a4", "b5", "axb5", "a6", "bxa6", "Nc6", "a7", "Nb8", "axb8"]
    p = P.pruefe(zeilen(fen_zellen))
    e = p.zuege[-1]
    assert e.status == "unklar" and {k.san.split("=")[1][0] for k in e.kandidaten if "=" in k.san} == {"Q", "R", "B", "N"}
    assert "Umwandlungsfigur" in e.meldungen[0].text


def test_schachzeichen_stimmt_nicht():
    p = P.pruefe(zeilen(["e4", "e5", "Nf3+"]))
    assert p.zuege[-1].status == "hinweis" and any(m.stufe == "warnung" and "kein Schach" in m.text for m in p.zuege[-1].meldungen)
    p = P.pruefe(zeilen(["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7+"]))
    assert p.zuege[-1].san == "Qxf7#" and any("matt" in m.text for m in p.zuege[-1].meldungen)


def test_ergebnis_gegen_endstellung():
    matt = P.pruefe(zeilen(["f3", "e5", "g4", "Qh4#"]))
    assert not any(b.stufe == "fehler" for b in P.ergebnis_befunde(matt, "0-1"))
    assert any(b.stufe == "fehler" and "0-1" in b.text for b in P.ergebnis_befunde(matt, "1-0"))
    assert any(b.stufe == "fehler" and "Matt" in b.text and "0-1" in b.text and "1/2-1/2" in b.text for b in P.ergebnis_befunde(matt, "1/2-1/2"))
    offen = P.pruefe(zeilen(["e4", "e5"]))
    assert all(b.stufe == "info" for b in P.ergebnis_befunde(offen, "1-0"))
    patt = P.pruefe(zeilen("e3 a5 Qh5 Ra6 Qxa5 h5 h4 Rah6 Qxc7 f6 Qxd7+ Kf7 Qxb7 Qd3 Qxb8 Qh7 Qxc8 Kg6 Qe6".split()))
    assert any(b.stufe == "fehler" for b in P.ergebnis_befunde(patt, "1-0")) and not any(b.stufe == "fehler" for b in P.ergebnis_befunde(patt, "1/2-1/2"))
    zelle = P.pruefe(zeilen(["f3", "e5", "g4", "Qh4#", "1-0"]))
    assert zelle.ergebnis_zelle == "1-0" and any(b.stufe == "fehler" for b in P.ergebnis_befunde(zelle, "0-1"))


def test_ergebnis_in_der_zelle_ist_kein_zug():
    p = P.pruefe(zeilen(["e4", "e5", "Nf3", "1-0"]))
    assert [e.status for e in p.zuege] == ["ok", "ok", "ok", "ergebnis"] and p.ergebnis_zelle == "1-0" and p.datenbanktauglich()
    assert [e.san for e in p.san_liste()] == ["e4", "e5", "Nf3"]


def test_buchstabensystem_einstellung():
    p = P.pruefe(zeilen(["e4", "e5", "Sf3", "Nc6"]), "auto")
    assert p.system == "gemischt" and any("mischt" in b.text for b in p.befunde)
    p = P.pruefe(zeilen(["e4", "e5", "Sf3", "Nc6"]), "de")
    assert any("englischen" in b.text and "1 Zelle" in b.text for b in p.befunde)
    p = P.pruefe(zeilen(["e4", "e5", "Sf3", "Sc6"]), "en")
    assert any("deutschen" in b.text and "2 Zelle" in b.text for b in p.befunde)
    assert not P.pruefe(zeilen(["e4", "e5", "Sf3", "Sc6"]), "de").befunde


def test_fortsetzungstest_unterscheidet_zwei_springer():
    """Aus „Sd7“ wird der Zug, nach dem die Partie weitergeht, und der Gleichstand wird als Gleichstand gemeldet."""
    sans = "e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O-O Rd8 Rxd7 Rxd7 Rd1 Qe6 Bxd7+ Nxd7 Qb8+ Nxb8 Rd8#".split()
    mit = sans[:21] + ["Nd7"] + sans[22:]
    e = P.pruefe(zeilen(mit)).zuege[21]
    assert e.status == "unklar" and e.san == "Nbd7" and [k.san for k in e.kandidaten] == ["Nbd7", "Nfd7"]
    assert e.kandidaten[0].ganz and not e.kandidaten[1].ganz and e.kandidaten[1].fortsetzung == 1


def test_vorschlaege_sind_legal_und_aehnlich():
    p = P.pruefe(zeilen(["e4", "e5", "Nf3", "d6", "Bb5+", "Nf6"]))
    e = p.zuege[-1]
    assert e.status == "illegal" and [k.san for k in e.kandidaten] == ["Nc6"]


def test_fruehere_ursache_wird_gefunden():
    sans = "e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O Rd8 Rxd7".split()
    p = P.pruefe(zeilen(sans))
    e = p.zuege[-1]
    assert e.status == "illegal" and p.zuege[-3].san == "O-O"
    assert [(j, k.san) for j, k in e.frueher][:1] == [(22, "O-O-O")]
