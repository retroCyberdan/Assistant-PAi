"""Rocky v2.0: il Jack Russell del tema CYBERDECK ROCKY Pi v2.0.

Ridisegnato dall'illustrazione di riferimento, in vista di tre quarti, con il muso
rivolto verso chi guarda:
  - orecchie cadenti marroni che si aprono ai lati della testa;
  - lista bianca al centro del muso, occhi grandi, naso nero e bocca;
  - petto e muso bianchi (con le ombre lavanda), corpo marrone con la sella scura;
  - coda alta e ricurva con la punta bianca;
  - quattro zampe: bianche quelle vicine, in ombra quelle lontane.

Le animazioni sono le stesse di Rocky v1.0 (deck_dog.Dog): cambia solo la grafica.
Lo sprite è una griglia 24x24 costruita a parti (testa, coda, corpo, zampe), così
ogni posa resta coerente con le altre.
"""

from deck_dog import Dog, _points

W_, H_ = 24, 24

# Legenda: W bianco, L ombra lavanda del bianco, B marrone, D marrone scuro,
# K nero (occhi, naso: puntini spenti), T lingua
LEGEND = {"W": "hi", "L": "fg", "B": "mid", "D": "dim", "T": "err"}

HEAD = [            # 13 x 9, centrata sulla lista bianca
    "DDB BBBBB BDD",
    "DDDBBBBBBBDDD",
    "DDBBBBWBBBBDD",
    "DBBBKBWBKBBBD",
    "DDBBKBWBKBBDD",
    " D BBWWWBB D ",
    " D BWKKKWB D ",
    "   BWWDWWB   ",
    "    LLLLL    ",
]

TAILS = [           # coda (riga di partenza 3): ferma / scodinzolo
    [(3, "W"), (2, "WL"), (1, "BLL"), (1, "BD"), (1, "BDD"), (1, "BDD"), (2, "DDD")],
    [(5, "W"), (4, "WL"), (3, "LLB"), (2, "DB"), (1, "DDB"), (1, "BDD"), (2, "DDD")],
]

BODY = {            # dorso con la sella scura e petto bianco
    9: [(12, "LWWWWWL")],
    10: [(3, "DDDDDDDDD"), (12, "LWWWWWL")],
    11: [(2, "DDDDDDDDDB"), (12, "WWWWWWW")],
    12: [(2, "BBBDDDDDBB"), (12, "WWWWWWW")],
    13: [(2, "BBBBDDDDBB"), (12, "BWWWWWWD")],
    14: [(2, "BBBBBDDBBB"), (12, "BWWWWWWD")],
    15: [(2, "BBBBBBDBBB"), (12, "BWWWWWBD")],
    16: [(2, "BBBWWLLDBB"), (12, "BWWWLLDD")],
}

LEGS = {
    "stand": {17: [(1, "DBWWL"), (7, "LLL"), (11, "WWW"), (16, "BDD")],
              18: [(1, "DWWL"), (7, "LL"), (11, "WWW"), (16, "BDD")],
              19: [(1, "WWL"), (7, "LL"), (11, "WWL"), (16, "BDL")],
              20: [(1, "WWL"), (7, "LL"), (11, "WWL"), (16, "LLL")],
              21: [(1, "WWL"), (7, "LL"), (11, "WWL"), (16, "LLL")],
              22: [(1, "WWL"), (7, "LL"), (11, "WWL"), (16, "LLL")],
              23: [(0, "WWWL"), (6, "LLL"), (11, "WWWW"), (16, "LLLL")]},
    "walk_a": {17: [(0, "DBWWL"), (8, "LLL"), (11, "WWW"), (16, "BDD")],
               18: [(0, "DWWL"), (8, "LL"), (11, "WWW"), (16, "BDD")],
               19: [(0, "WWL"), (8, "LL"), (11, "WWL"), (16, "BDL")],
               20: [(0, "WWL"), (9, "LL"), (11, "WWWL"), (16, "LLL")],
               21: [(0, "WWL"), (9, "LL"), (16, "LLL")],
               22: [(0, "WWL"), (9, "LL"), (16, "LLL")],
               23: [(0, "WWL"), (8, "LLL"), (16, "LLLL")]},
    "walk_b": {17: [(1, "DBWWL"), (6, "LLL"), (11, "WWW"), (16, "BDD")],
               18: [(2, "WWL"), (6, "LL"), (11, "WWW"), (17, "BDD")],
               19: [(2, "WWL"), (6, "LL"), (11, "WWL"), (17, "BDLL")],
               20: [(3, "WWL"), (5, "LL"), (11, "WWL")],
               21: [(3, "WWL"), (5, "LL"), (11, "WWL")],
               22: [(3, "WWL"), (5, "LL"), (11, "WWL")],
               23: [(3, "WWWL"), (4, "LLL"), (11, "WWWW")]},
    "jump": {17: [(1, "DBWWL"), (7, "LLL"), (11, "WWWW"), (16, "BDDL")],
             18: [(0, "DWWL"), (6, "LLL"), (12, "WWWW"), (17, "BDLL")],
             19: [(0, "WWL"), (5, "LL"), (13, "WWWL"), (18, "LLL")],
             20: [(0, "WL"), (14, "WWL"), (19, "LL")]},
}


# ------------------------------------------------------------------ costruzione

def _blank():
    return [["."] * W_ for _ in range(H_)]


def _put(g, y, x0, s):
    for i, ch in enumerate(s):
        if ch != " " and 0 <= y < H_ and 0 <= x0 + i < W_:
            g[y][x0 + i] = ch


def _place(g, rows, dy=0):
    for y, segs in rows.items():
        for x0, s in segs:
            _put(g, y + dy, x0, s)


def _head(eyes="open", mouth="closed"):
    h = [list(r) for r in HEAD]
    if eyes == "closed":
        h[3][4] = h[3][8] = "B"
        h[4][4] = h[4][8] = "D"
    if mouth in ("open", "pant"):          # bocca aperta con la lingua
        h[7] = list("   BWKKKWB   ")
        h[8] = list("    LLTLL    ")
    if mouth == "pant":                   # lingua più lunga mentre ansima
        h.append(list("      T      "))
    return ["".join(r) for r in h]


def _draw_head(g, hx, hy, flip=False, **kw):
    rows = _head(**kw)
    if flip:
        rows = rows[:9][::-1]
    for j, r in enumerate(rows):
        _put(g, hy + j, hx, r)


def _grid(g, dy=0):
    if dy:
        g = [["."] * W_ for _ in range(dy)] + g[:H_ - dy]
    return ["".join(r) for r in g]


def stand(eyes="open", mouth="closed", tail=0, legs="stand"):
    g = _blank()
    for j, (x0, s) in enumerate(TAILS[tail]):
        _put(g, 3 + j, x0, s)
    _place(g, BODY)
    _place(g, LEGS[legs])
    _draw_head(g, 9, 0, eyes=eyes, mouth=mouth)
    return _grid(g)


def sit(eyes="open", mouth="closed"):
    g = _blank()
    _place(g, {16: [(1, "W")], 17: [(0, "WL")], 18: [(0, "BD")], 19: [(1, "DD")], 20: [(1, "DDD")]})
    _place(g, {12: [(6, "DDDDDB")], 13: [(4, "DDDDDDBB")], 14: [(3, "BBBDDDDBB")],
               15: [(3, "BBBBDDDBB")], 16: [(3, "BBBBBDBBB")], 17: [(3, "BBBBBBBBB")],
               18: [(3, "BBBBBBBB")], 19: [(3, "BBWWWBBB")], 20: [(3, "BWWWWLL")],
               21: [(2, "WWWWWLL")], 22: [(2, "WWWWLL")]})
    _place(g, {11: [(12, "LWWWWWL")], 12: [(12, "WWWWWWW")], 13: [(12, "WWWWWWW")],
               14: [(12, "BWWWWWBD")], 15: [(12, "BWWWWWBD")], 16: [(12, "BWWWLLDD")],
               17: [(11, "WWW"), (16, "BDD")], 18: [(11, "WWW"), (16, "BDL")],
               19: [(11, "WWL"), (16, "LLL")], 20: [(11, "WWL"), (16, "LLL")],
               21: [(11, "WWL"), (16, "LLL")], 22: [(11, "WWL"), (16, "LLL")],
               23: [(11, "WWWW"), (16, "LLLL")]})
    _draw_head(g, 9, 2, eyes=eyes, mouth=mouth)
    return _grid(g)


def lie(eyes="open"):
    g = _blank()
    _place(g, {19: [(0, "WL")], 20: [(0, "BDD")]})
    _place(g, {13: [(4, "DDDDDD")], 14: [(2, "DDDDDDDD")], 15: [(1, "BBBDDDDDBB")],
               16: [(1, "BBBBDDDBBB")], 17: [(1, "BBBBBBBBBB")], 18: [(1, "BBBBBBBBBBB")],
               19: [(2, "BWWWWBBBB")], 20: [(3, "WWWWLLBB")], 21: [(2, "WWWWLL")]})
    _place(g, {18: [(11, "LWWWWWWL")], 19: [(10, "WWWWWWWWWW")], 20: [(10, "WWWWWWWWWWL")],
               21: [(9, "WWWWL"), (16, "WWWWL")], 22: [(8, "WWWWL"), (16, "WWWWL")]})
    _draw_head(g, 9, 10, eyes=eyes)
    return _grid(g, dy=1)                 # appoggiato al pavimento


def back(wiggle=0):
    g = _blank()
    a = ((3, 7, 11, 15), (2, 8, 10, 16))[wiggle]   # zampe che si agitano
    legs = {7: [(a[0], "WW"), (a[1], "LL"), (a[2], "WW"), (a[3], "LL")],
            8: [(a[0], "WW"), (a[1], "LL"), (a[2], "WW"), (a[3], "LL")],
            9: [(3, "WW"), (7, "LL"), (11, "WW"), (15, "LL")],
            10: [(3, "WWL"), (7, "LL"), (11, "WWL"), (15, "LL")],
            11: [(3, "BWL"), (7, "LB"), (11, "WWL"), (15, "BB")]}
    _place(g, legs)
    _place(g, {12: [(2, "BBWWWWWWWWWWWWBB")], 13: [(1, "DBWWWWWWWWWWWWWBD")],
               14: [(1, "DBBBWWWWWWWWWBBBD")], 15: [(1, "DDBBBBDDDDDBBBBDD")],
               16: [(2, "DDDDDDDDDDDDDD")], 17: [(0, "WLDDD")]})
    _draw_head(g, 11, 14, flip=True)       # testa capovolta, orecchie verso terra
    return _grid(g, dy=1)


def dig(paws=0):
    g = _blank()
    _place(g, {0: [(3, "W")], 1: [(2, "WL")], 2: [(1, "BLL")], 3: [(1, "BD")], 4: [(1, "BDD")],
               5: [(2, "DDD")]})
    hind = {y: [(2, "WWL"), (7, "LL")] for y in range(14, 23)}
    hind.update({13: [(2, "BWWL"), (7, "LLL")], 23: [(1, "WWWL"), (6, "LLL")]})
    _place(g, {6: [(3, "DDDD")], 7: [(2, "DDDDDDD")], 8: [(2, "BBDDDDDDD")], 9: [(2, "BBBDDDDDDDB")],
               10: [(2, "BBBBBDDDDDBBW")], 11: [(2, "BBBBBBDDDBBWWW")], 12: [(2, "BBWWLLBBBBWWWW")]})
    _place(g, hind)
    if paws == 0:
        _place(g, {19: [(10, "WW")], 20: [(10, "WW"), (20, "LL")], 21: [(9, "WW"), (20, "LL")],
                   22: [(9, "WW"), (20, "LLL")], 23: [(8, "WWW"), (20, "LLL")]})
    else:
        _place(g, {18: [(9, "WW")], 19: [(8, "WW")], 20: [(7, "WW"), (19, "LL")], 21: [(19, "LL")],
                   22: [(19, "LLL")], 23: [(19, "LLL")]})
    _draw_head(g, 10, 13)
    return _grid(g)


def _build():
    grids = {
        "stand": stand(), "stand_tail": stand(tail=1), "stand_blink": stand(eyes="closed"),
        "stand_pant": stand(mouth="open"), "stand_pant2": stand(mouth="pant"),
        "walk_a": stand(legs="walk_a"), "walk_b": stand(legs="walk_b"), "jump": stand(legs="jump"),
        "sit": sit(), "sit_blink": sit(eyes="closed"), "sit_pant": sit(mouth="open"),
        "sit_pant2": sit(mouth="pant"),
        "lie": lie(), "lie_sleep": lie(eyes="closed"),
        "back": back(0), "back_b": back(1),
        "dig_a": dig(0), "dig_b": dig(1),
    }
    return {k: _points(v, LEGEND) for k, v in grids.items()}


class Dog2(Dog):
    """Rocky v2.0: stesse animazioni di Rocky v1.0, nuova grafica."""
    FRAMES = _build()
    SPR_W, SPR_H = W_, H_
    ZZ = (8, -13)
    PAW_X = (-4, -1)
    MOUND_X = -12
    JUMP_H = 3.5
