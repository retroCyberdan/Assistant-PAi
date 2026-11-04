"""Rocky: il Jack Russell a puntini del CYBERDECK.

Rocky è disegnato in pixel art (griglia 32x22, vista di profilo) con i tratti
tipici del Jack Russell: corpo bianco, macchie marroni su orecchie e occhi e
una sul dorso, orecchio piegato in avanti, coda corta e dritta, collare.

Le animazioni sono sequenze di "segmenti":
  - fotogramma (o funzione del tempo che lo sceglie: zampe, coda, lingua...);
  - trasformazione continua (spostamento, specchio, schiacciamento, rotazione);
  - morph iniziale: i puntini della posa precedente scivolano nella nuova.
Così ogni passaggio è fluido, anche tra pose molto diverse.

A riposo Rocky scodinzola, sbatte gli occhi e respira; ogni tanto, a caso, si
siede e ansima con la lingua di fuori, va a fare un giro o schiaccia un
pisolino. Mentre l'assistente elabora sceglie a caso cosa fare: scavare,
saltare o rotolarsi a pancia in su (mai la stessa cosa due volte di fila).
"""

import math

import numpy as np

SPR_W, SPR_H = 32, 22
M = 384                     # numero fisso di puntini (condiviso con le altre forme)
PIVOT = np.array([0.0, -6.0])  # centro di rotazione (circa il centro del corpo)

# Legenda: W pelo bianco, B macchia marrone, D ombra / zampe lontane, C collare, T lingua
LEGEND = {"W": "hi", "B": "mid", "D": "dim", "C": "acc", "T": "err"}

SPRITES = {
    "stand": [
        "................................",
        ".......................BB.......",
        "......................BBBB......",
        ".....................BBBBBB.....",
        ".....WW.............DBBBBBBW....",
        ".....WW.............DDBBBBWWW...",
        ".....WW............WWBB.BBWWWWW.",
        "......WW...........WWBBBBWWWWWDD",
        "......WW..........WWWWWBWWWWWWDD",
        "......WWW.........WWWWWWWWWWWWW.",
        ".......WWWWWWWWWWWCCWWWWWWW.....",
        "......WWWWWBBBWWWWCCWWWWW.......",
        "......WWWWBBBBBWWWCCWWWWW.......",
        "......WWWWWBBBWWWWWWWWWWW.......",
        "......WWWWWWWWWWWWWWWWWWW.......",
        ".......WWWWWWWWWWWWWWWWW........",
        "........WWWWDD....DDWWWW........",
        "........WWW.DD....DD.WWW........",
        ".......WWW..DD....DD..WW........",
        ".......WW...DD....DD..WW........",
        ".......WW...DDD...DDD.WW........",
        "......WWW...............WWW.....",
    ],
    "sit": [
        "................................",
        ".......................BB.......",
        "......................BBBB......",
        ".....................BBBBBB.....",
        "....................DBBBBBBW....",
        "....................DDBBBBWWW...",
        "...................WWBB.BBWWWWW.",
        "...................WWBBBBWWWWWDD",
        "..................WWWWWBWWWWWWDD",
        "..................WWWWWWWWWWWWW.",
        "..................WCCWWWWWWWW...",
        ".................WWCCWWWWW......",
        "................WWWCCWWWWW......",
        "...............WWWWWWWWWWW......",
        "..............WWBBBWWWWWWW......",
        ".............WWBBBBBWWWWWW......",
        "............WWWWBBBWWWDDWW......",
        "...........WWWWWWWWWWWDDWW......",
        "..........WWWWWWWWWWWWDDWW......",
        ".....WW...WWWWWWWWWWWWDDWW......",
        "......WWWWWWWWWWDWWWWDDDWWW.....",
        ".......WWWWWWWWDDWWWDDD.WWW.....",
    ],
    "lie": [
        "................................",
        "................................",
        "................................",
        "................................",
        "................................",
        "................................",
        "................................",
        "........................BB......",
        ".......................BBBB.....",
        "......................BBBBBB....",
        ".....................DBBBBBBW...",
        "....WW...............DDBBBBWWW..",
        ".....WW.............WWBB.BBWWWWW",
        "......WW............WWBBBBWWWWWD",
        ".......WWWWWWWWWWWWWWWWWWBWWWWWD",
        "......WWWWWBBBWWWWWCCWWWWWWWWWW.",
        ".....WWWWBBBBBWWWWWCCWWWWWWWW...",
        ".....WWWWWBBBWWWWWWWWWWWWWWWWWWW",
        ".....WWWWWWWWWWWWWWWWWWWWWWWWWWW",
        "....WWWWWWWWWWWWWWWWWWDDDDDDDDD.",
        "...WWWWW..........WWWWWWWWWWWWWW",
        "................................",
    ],
    "back": [
        "................................",
        "................................",
        "................................",
        "................................",
        ".......WW..WW.......WW...WW.....",
        ".......WW..WW.......WW...WW.....",
        "........WW.WW.......WW..WW......",
        "........WW.WW.......WW..WW......",
        ".........WWWW.......WWWWW.......",
        "....WW...WWWWWWWWWWWWWWWW.......",
        "....WWW.WWWWWWWWWWWWWWWWWW......",
        ".....WWWWWWWWWWWWWWWWWWWWWWW....",
        "......WWWWWBBBWWWWWWCCWWWWWWW...",
        "......WWWWBBBBBWWWWWCCWWWWWWWW..",
        ".......WWWWBBBWWWWWWCCWWWBBWWWDD",
        "........WWWWWWWWWWWWWWWWBBBBWWDD",
        "..........WWWWWWWWWWWWWBBB.BBWW.",
        ".......................BBBBBB...",
        "........................BBBB....",
        ".........................BB.....",
        "................................",
        "................................",
    ],
    "dig_a": [
        "................................",
        "................................",
        "................................",
        ".....WW.........................",
        ".....WW.........................",
        ".....WW.........................",
        "......WW........................",
        "......WW........................",
        "......WWW.......................",
        ".......WWWWWWWWWWWW.............",
        "......WWWWWBBBWWWWWW...BB.......",
        "......WWWWBBBBBWWWWWW.BBBB......",
        "......WWWWWBBBWWWWWWCDBBBBB.....",
        "......WWWWWWWWWWWWWWCDDBBBBW....",
        ".......WWWWWWWWWWWWWCWWBB.BBWW..",
        "........WWWWDD.....WWWWBBBBWWWW.",
        "........WWW.DD.....DDWWWWWBWWWDD",
        ".......WWW..DD....DD.WWWWWWWWWDD",
        ".......WW...DD...DD...WW.WWWWW..",
        ".......WW...DDD.DD.....WW.......",
        "......WWW...............WWW.....",
        "................................",
    ],
    "dig_b": [
        "................................",
        "................................",
        "................................",
        ".....WW.........................",
        ".....WW.........................",
        ".....WW.........................",
        "......WW........................",
        "......WW........................",
        "......WWW.......................",
        ".......WWWWWWWWWWWW.............",
        "......WWWWWBBBWWWWWW...BB.......",
        "......WWWWBBBBBWWWWWW.BBBB......",
        "......WWWWWBBBWWWWWWCDBBBBB.....",
        "......WWWWWWWWWWWWWWCDDBBBBW....",
        ".......WWWWWWWWWWWWWCWWBB.BBWW..",
        "........WWWWDD.....WWWWBBBBWWWW.",
        "........WWW.DD.....DDWWWWWBWWWDD",
        ".......WWW..DD.....DDWWWWWWWWWDD",
        ".......WW...DD......DDWW.WWWWW..",
        ".......WW...DDD.....WWDD........",
        "......WWW..........WWW.DDD......",
        "................................",
    ],
}

# Patch (colonna, riga, righe) applicate sopra uno sprite; '?' = lascia invariato
PATCHES = {
    "tail_b": (4, 4, [
        "...WW.",
        "..WW..",
        "..WW..",
        "..WW..",
        "..WW..",
        "..WWW.",
    ]),
    "mouth_open": (25, 9, [
        "W.TT...",
        "WWTTW..",
        "??TT???",
    ]),
    "mouth_pant": (25, 9, [
        "W.TT...",
        "WWTTW..",
        "??TT???",
        "???T???",
    ]),
    "blink": (23, 6, [
        "B",
    ]),
    "blink_lie": (25, 12, [
        "B",
    ]),
    "legs_walk_a": (0, 16, [
        "........WWWWDD....DDWWWW........",
        "........WWW.DD....DD..WWW.......",
        ".......WWW..DD....DD...WW.......",
        "......WWW...DD....DD....WW......",
        ".....WWW....DDD...DDD...WW......",
        "....WWW..................WWW....",
    ]),
    "legs_walk_b": (0, 16, [
        "........WWWWDD....DDWWWW........",
        "........WWW..DD..DD..WWW........",
        "........WW....DD.DD...WW........",
        "........WW.....DDD....WW........",
        "........WW....DD.DD...WW........",
        ".......WWW..DDD...DDD.WWW.......",
    ]),
    "legs_jump": (0, 16, [
        "........WWWWDD....DDWWWW........",
        ".......WWW...DD..DD...WWW.......",
        ".....WWW......DDDD......WWW.....",
        "...WWW.......DD..DD.......WWW...",
        "..WW........DD....DD.......WW...",
        "................................",
    ]),
    "back_b": (0, 4, [
        "......WW....WW......WW..WW......",
        "......WW....WW.......WW.WW......",
        ".......WW..WW........WW.WW......",
        "........WW.WW.......WW..WW......",
        ".........WWWW.......WWWWW.......",
    ]),
}


def _grid(name):
    return [list(r) for r in SPRITES[name]]


def _patch(g, name):
    x0, y0, rows = PATCHES[name]
    g = [r[:] for r in g]
    for dy, row in enumerate(rows):
        for dx, c in enumerate(row):
            if c != "?":
                g[y0 + dy][x0 + dx] = c
    return g


def _points(g):
    """Griglia -> (posizioni, chiavi colore). Origine: centro dei piedi; y verso l'alto negativo."""
    pos, keys = [], []
    for y, row in enumerate(g):
        for x, c in enumerate(row):
            if c in LEGEND:
                pos.append((x - SPR_W // 2, y - (SPR_H - 1)))  # coordinate intere: griglia regolare
                keys.append(LEGEND[c])
    order = np.argsort(np.array(pos)[:, 0], kind="stable")  # da sinistra a destra
    return np.array(pos, dtype=float)[order], [keys[i] for i in order]


def _build():
    st, sit, lie, back = _grid("stand"), _grid("sit"), _grid("lie"), _grid("back")
    f = {
        "stand": st,
        "stand_tail": _patch(st, "tail_b"),
        "stand_blink": _patch(st, "blink"),
        "stand_pant": _patch(st, "mouth_open"),
        "stand_pant2": _patch(st, "mouth_pant"),
        "walk_a": _patch(st, "legs_walk_a"),
        "walk_b": _patch(st, "legs_walk_b"),
        "jump": _patch(st, "legs_jump"),
        "sit": sit,
        "sit_blink": _patch(sit, "blink"),
        "sit_pant": _patch(sit, "mouth_open"),
        "sit_pant2": _patch(sit, "mouth_pant"),
        "lie": lie,
        "lie_sleep": _patch(lie, "blink_lie"),
        "back": back,
        "back_b": _patch(back, "back_b"),
        "dig_a": _grid("dig_a"),
        "dig_b": _grid("dig_b"),
    }
    out = {k: _points(v) for k, v in f.items()}
    for k in ("back", "back_b"):  # a pancia in su la schiena poggia sul pavimento
        out[k][0][:, 1] += 2
    return out


FRAMES = _build()


# ------------------------------------------------------------------ utilità

def _smooth(u):
    u = 0.0 if u < 0 else 1.0 if u > 1 else u
    return u * u * (3 - 2 * u)


def _transform(pos, tf):
    dx, dy, sx, sy, rot = tf
    p = pos * np.array([sx, sy])
    if rot:
        c, s = math.cos(rot), math.sin(rot)
        q = p - PIVOT
        p = np.stack([q[:, 0] * c - q[:, 1] * s, q[:, 0] * s + q[:, 1] * c], axis=1) + PIVOT
    return p + np.array([dx, dy])


def _match(a, b, rng):
    """Abbina i puntini di due pose (ogni puntino trova il più vicino ancora libero).

    Restituisce due array di indici della stessa lunghezza che coprono entrambe le pose.
    """
    swap = len(a) > len(b)
    if swap:
        a, b = b, a
    n, m = len(a), len(b)
    d = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    used = np.zeros(m, dtype=bool)
    ia, ib = [], []
    for i in rng.permutation(n):
        row = np.where(used, np.inf, d[i])
        j = int(np.argmin(row))
        used[j] = True
        ia.append(i)
        ib.append(j)
    for j in np.nonzero(~used)[0]:  # i puntini in più si dividono dal vicino più prossimo
        ia.append(int(np.argmin(d[:, j])))
        ib.append(int(j))
    ia, ib = np.array(ia), np.array(ib)
    order = np.argsort(b[ib][:, 0], kind="stable")
    ia, ib = ia[order], ib[order]
    return (ib, ia) if swap else (ia, ib)


IDENT = (0.0, 0.0, 1.0, 1.0, 0.0)


class Seg:
    """Un segmento di animazione."""

    def __init__(self, dur, frame, tf=None, morph=0.0, fx=None):
        self.dur = dur
        self.frame = frame          # nome oppure funzione(t) -> nome
        self.tf = tf                # funzione(u, t) -> (dx, dy, sx, sy, rot), u da 0 a 1
        self.morph = morph          # secondi di morph dalla posa precedente
        self.fx = fx                # funzione(dog, t, u, tf) per effetti (terra, z, ombra)

    def frame_at(self, t):
        return self.frame(t) if callable(self.frame) else self.frame

    def tf_at(self, u, t):
        return self.tf(u, t) if self.tf else IDENT


def _cycle(names, period):
    return lambda t: names[int(t / period) % len(names)]


# ------------------------------------------------------------------ Rocky


class Dog:
    def __init__(self, rng=None):
        self.rng = rng or np.random.default_rng()
        self.mode = None
        self.clip = []
        self.loop = False
        self.i = 0
        self.t0 = 0.0
        self.next_blink = 0.0
        self.last = None            # (posizioni, colori) dell'ultimo fotogramma
        self.morph_from = None      # (posizioni A, colori A, ia, ib)
        self.dirt = []              # terra che vola mentre scava
        self.mound = 0
        self.last_dirt = 0.0
        self.last_idle = None
        self.last_busy = None
        self.p = None
        self.extras = []
        self.clip_kind = "base"

    # -------------------------------------------------------------- scelta delle animazioni
    def set_mode(self, mode, now):
        """mode: "idle" (attesa), "busy" (elaborazione), "sit" (seduto e tranquillo),
        "hidden" (Rocky non è sullo schermo: la prossima animazione riparte da capo)."""
        if mode == self.mode:
            return
        if self.mode == "hidden":
            self.last = None  # Rocky ricompare dal morph generale (onda -> cane), senza doppio morph
        self.mode = mode
        if mode == "hidden":
            self.last = None  # al ritorno Rocky compare dal morph generale, non da qui
            return
        self._start(self._pick(), now)

    def _pick(self):
        if self.mode == "busy":
            options = [n for n in ("dig", "jump", "roll") if n != self.last_busy]
            name = options[int(self.rng.integers(0, len(options)))]
            self.last_busy = name
            self.loop = True
            return getattr(self, "_clip_" + name)()
        self.loop = False
        if self.mode == "sit":
            self.loop = True
            return self._clip_sit_calm()
        return self._clip_idle_base()

    def _start(self, clip, now):
        self.clip, self.i, self.t0 = clip, 0, now
        self._enter(now)

    def _enter(self, now):
        seg = self.clip[self.i]
        self.morph_from = None
        if seg.morph > 0 and self.last is not None:
            b_pos, b_col = self._sample(seg, 0.0, 0.0)
            a_pos, a_col = self.last
            ia, ib = _match(a_pos, b_pos, self.rng)
            self.morph_from = (a_pos, a_col, ia, ib)

    def _advance(self, now):
        while now - self.t0 >= self.clip[self.i].dur:
            self.t0 += self.clip[self.i].dur
            self.i += 1
            if self.i >= len(self.clip):
                if self.loop:
                    self.i = 0
                else:
                    # fine di un'animazione a riposo: si alterna base / comportamento casuale
                    nxt = self._clip_idle_behavior() if self.clip_kind == "base" else self._clip_idle_base()
                    self.clip, self.i = nxt, 0
            self._enter(now)

    # -------------------------------------------------------------- campionamento
    def _colors(self, keys):
        p = self.p
        return np.array([p[k] for k in keys], dtype=float)

    def _sample(self, seg, t, u):
        name = seg.frame_at(t)
        pos, keys = FRAMES[name]
        tf = seg.tf_at(u, t)
        return _transform(pos, tf), self._colors(keys)

    def sample(self, now, p):
        """Posizioni (unità sprite) e colori del fotogramma corrente, più gli effetti."""
        self.p = p
        if not self.clip:
            self.set_mode("idle", now)
        self._advance(now)
        seg = self.clip[self.i]
        t = now - self.t0
        u = min(1.0, t / seg.dur) if seg.dur > 0 else 1.0
        pos, col = self._sample(seg, t, u)
        if self.morph_from is not None and t < seg.morph:
            a_pos, a_col, ia, ib = self.morph_from
            n = len(ia)
            delay = np.linspace(0, 0.25, n)
            k = np.clip((t / seg.morph - delay) / 0.75, 0, 1)
            e = (k * k * (3 - 2 * k))[:, None]
            pa, pb = a_pos[ia], pos[ib]
            pos = pa + (pb - pa) * e
            pos[:, 1] -= np.sin(e[:, 0] * math.pi) * 1.2   # piccolo arco: movimento organico
            col = a_col[ia] + (col[ib] - a_col[ia]) * e
        self.last = (pos, col)
        self.extras = []
        if seg.fx:
            seg.fx(self, t, u, seg.tf_at(u, t))
        return pos, col

    def points(self, now, box, p):
        """Puntini in pixel dentro box (x, y, w, h), sempre M elementi."""
        pos, col = self.sample(now, p)
        x, y, w, h = box
        pitch = self.pitch(box)
        cx, gy = self.anchor(box)
        px = np.stack([cx + pos[:, 0] * pitch, gy + pos[:, 1] * pitch], axis=1)
        idx = np.arange(M) % len(px)
        order = np.argsort(px[:, 0], kind="stable")
        px, col = px[order][idx], col[order][idx]
        return px, col

    @staticmethod
    def pitch(box):
        """Passo dei puntini: segue con continuità la grandezza del riquadro (niente scatti
        mentre le card si ridimensionano) e si aggancia a un valore intero (3, 2, 1 px) quando
        ci è vicino, così da fermo la griglia di puntini è perfettamente regolare."""
        _x, _y, w, h = box
        p = max(1.0, min(3.0, h / (SPR_H + 3), w / (SPR_W + 6)))
        r = round(p)
        return float(r) if abs(p - r) < 0.12 else p

    @classmethod
    def anchor(cls, box):
        """Punto (in pixel interi) dove poggiano le zampe di Rocky."""
        x, y, w, h = box
        p = cls.pitch(box)
        return int(x + w // 2), int(y + h - p)

    def draw_extras(self, cv, box, p):
        """Effetti attorno a Rocky (terra, z del sonnellino, ombra del salto, cumulo)."""
        pitch = self.pitch(box)
        cx, gy = self.anchor(box)
        size = 2 if pitch >= 2.5 else 1
        for kind, ex, ey, extra in self.extras:
            sx, sy = cx + ex * pitch, gy + ey * pitch
            if kind == "dot":
                cv.dot(sx, sy, extra, size)
            elif kind == "text" and pitch >= 2:
                cv.text(sx, sy - 8, extra[0], extra[1], "s")

    # -------------------------------------------------------------- animazioni a riposo
    def _clip_idle_base(self):
        self.clip_kind = "base"
        dur = float(self.rng.uniform(4.5, 8.0))
        blinks = sorted(self.rng.uniform(0.8, dur - 0.3, size=2))

        def frame(t):
            for b in blinks:
                if b <= t < b + 0.14:
                    return "stand_blink"
            return "stand_tail" if int(t / 0.22) % 2 else "stand"

        def tf(u, t):
            return (0.0, 0.0, 1.0, 1.0 + 0.012 * math.sin(t * 2 * math.pi / 1.7), 0.0)

        return [Seg(dur, frame, tf, morph=0.55)]

    def _clip_idle_behavior(self):
        self.clip_kind = "behavior"
        options = [n for n in ("sit_pant", "walk", "nap") if n != self.last_idle]
        name = options[int(self.rng.integers(0, len(options)))]
        self.last_idle = name
        return getattr(self, "_clip_" + name)()

    def _clip_sit_pant(self):
        def breathe(rate, amp):
            return lambda u, t: (0.0, 0.0, 1.0, 1.0 + amp * math.sin(t * 2 * math.pi * rate), 0.0)
        return [
            Seg(0.7, "sit", morph=0.6),
            Seg(0.25, "sit_blink"),
            Seg(2.8, _cycle(["sit_pant", "sit_pant2"], 0.16), breathe(3.0, 0.02), morph=0.2),
            Seg(0.9, "sit", breathe(0.6, 0.01), morph=0.25),
            Seg(0.6, "stand", morph=0.55),
        ]

    def _clip_walk(self):
        far = -float(self.rng.uniform(10, 15))
        legs = _cycle(["walk_a", "stand", "walk_b", "stand"], 0.12)

        def turn(x, start):
            """Si gira: la larghezza passa da start (+1 / -1) al segno opposto, come una rotazione."""
            def tf(u, t):
                s = start * math.cos(math.pi * _smooth(u))
                s = math.copysign(max(0.18, abs(s)), s if s != 0 else -start)
                return (x, 0.0, s, 1.0, 0.0)
            return tf

        def walk(x0, x1, sx):
            def tf(u, t):
                bob = -0.35 * abs(math.sin(t * math.pi / 0.24))
                return (x0 + (x1 - x0) * _smooth(u), bob, sx, 1.0, 0.0)
            return tf

        return [
            Seg(0.45, "stand", turn(0.0, 1.0)),
            Seg(1.6, legs, walk(0.0, far, -1.0)),
            Seg(0.8, _cycle(["stand", "stand_tail"], 0.2), lambda u, t: (far, 0.0, -1.0, 1.0, 0.0)),
            Seg(0.45, "stand", turn(far, -1.0)),
            Seg(1.6, legs, walk(far, 0.0, 1.0)),
        ]

    def _clip_nap(self):
        def zz(dog, t, u, tf):
            for k in range(3):
                ph = (t * 0.6 + k / 3.0) % 1.0
                if t > 0.6:
                    col = dog.p["mid"] if ph < 0.7 else dog.p["dim"]
                    dog.extras.append(("text", 10 + ph * 4 + k * 1.5, -15 - ph * 6, ("z" if k % 2 else "Z", col)))

        return [
            Seg(0.9, "lie", morph=0.7),
            Seg(3.2, "lie_sleep", lambda u, t: (0.0, 0.0, 1.0, 1.0 + 0.02 * math.sin(t * 2 * math.pi / 2.2), 0.0),
                fx=zz),
            Seg(0.35, "lie"),
            Seg(0.2, "lie_sleep"),
            Seg(0.5, "lie"),
            Seg(0.7, "stand", morph=0.6),
        ]

    def _clip_sit_calm(self):
        return [Seg(3.0, _cycle(["sit"] * 12 + ["sit_blink"], 0.2), morph=0.6)]

    # -------------------------------------------------------------- animazioni durante l'elaborazione
    def _clip_dig(self):
        def dirt(dog, t, u, tf):
            now_k = int(t / 0.12)
            if now_k != dog.last_dirt:
                dog.last_dirt = now_k
                for _ in range(3):
                    dog.dirt.append([float(dog.rng.uniform(4, 8)), -0.5,
                                     float(dog.rng.uniform(-20, -9)), float(dog.rng.uniform(-16, -7)), t])
            alive = []
            for d in dog.dirt:
                age = t - d[4]
                if age < 0:
                    continue
                xx = d[0] + d[2] * age
                yy = d[1] + d[3] * age + 30 * age * age
                if yy < 0 and age < 1.2:
                    alive.append(d)
                    dog.extras.append(("dot", xx, yy, dog.p["fg"] if age < 0.35 else dog.p["mid"]))
                else:
                    dog.mound = min(14, dog.mound + 0.25)
            dog.dirt = alive
            # cumulo di terra dietro Rocky
            m = int(dog.mound)
            for i in range(m):
                hx = -12 - (i % 5) * 0.9
                hy = -(i // 5) * 0.9
                dog.extras.append(("dot", hx + (i // 5) * 0.45, hy, dog.p["mid"]))

        self.dirt, self.mound = [], 0
        return [
            Seg(0.6, "dig_a", morph=0.55),
            Seg(4.0, _cycle(["dig_a", "dig_b"], 0.12), fx=dirt),
            Seg(0.3, "dig_a", fx=dirt),
        ]

    def _clip_jump(self):
        def shadow(dog, t, u, tf):
            hgt = -tf[1]
            n = max(3, int(9 - hgt * 0.5))
            for i in range(n):
                dog.extras.append(("dot", (i - (n - 1) / 2) * 1.6 + tf[0], 0.6, dog.p["dim"]))

        def crouch(u, t):
            e = _smooth(u)
            return (0.0, 0.0, 1.0 + 0.07 * e, 1.0 - 0.16 * e, 0.0)

        def air(u, t):
            h = 4.0 * math.sin(math.pi * u)
            return (0.0, -h, 1.0 - 0.03 * math.sin(math.pi * u), 1.0 + 0.06 * math.sin(math.pi * u), 0.0)

        def land(u, t):
            e = math.sin(math.pi * u)
            return (0.0, 0.0, 1.0 + 0.07 * e, 1.0 - 0.14 * e, 0.0)

        return [
            Seg(0.5, "stand", morph=0.45, fx=shadow),
            Seg(0.18, "stand", crouch, fx=shadow),
            Seg(0.55, "jump", air, fx=shadow),
            Seg(0.18, "stand", land, fx=shadow),
            Seg(0.12, "stand_tail", fx=shadow),
            Seg(0.18, "stand", crouch, fx=shadow),
            Seg(0.55, "jump", air, fx=shadow),
            Seg(0.18, "stand", land, fx=shadow),
        ]

    def _clip_roll(self):
        def wiggle(u, t):
            # si struscia la schiena a terra: piccolo dondolio laterale
            return (0.7 * math.sin(t * 2 * math.pi * 2.2), 0.0, 1.0, 1.0, 0.0)

        def hop(u, t):
            return (0.0, -1.5 * math.sin(math.pi * u), 1.0, 1.0, 0.0)

        return [
            Seg(0.8, "lie", morph=0.6),
            Seg(0.45, "back", hop, morph=0.45),
            Seg(2.0, _cycle(["back", "back_b"], 0.14), wiggle),
            Seg(0.45, "lie", hop, morph=0.45),
            Seg(0.4, "lie"),
            Seg(0.6, "stand", morph=0.55),
            Seg(0.5, _cycle(["stand", "stand_tail"], 0.18)),
        ]
