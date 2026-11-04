"""Motore grafico del tema CYBERDECK.

Tutto viene disegnato su un array numpy RGB 240x280:
  - testo dot-matrix in più "pesi" (pixel, puntini, tratto sottile, blocchi);
  - card con angoli arrotondati, come nella dashboard di riferimento;
  - forme fatte di particelle (faccia, onda, anello, spettro...) che si
    trasformano l'una nell'altra in modo fluido;
  - immagini ricostruite a puntini, glitch digitali ed effetto monitor CRT.
"""

import math
import os

import numpy as np
from PIL import Image, ImageFilter, ImageChops, ImageOps

from deck_font import glyph, is_kana, normalize_text

W, H = 240, 280

# ------------------------------------------------------------------ palette

PALETTES = {
    # fosfori verdi del monitor CRT (default)
    "verde": {
        "bg": (3, 9, 6), "card": (8, 19, 13), "edge": (24, 52, 35),
        "faint": (20, 44, 30), "dim": (54, 110, 74), "mid": (92, 172, 114),
        "fg": (138, 240, 162), "hi": (214, 255, 228), "acc": (88, 255, 128),
        "err": (255, 112, 92),
    },
    "ambra": {
        "bg": (10, 6, 2), "card": (20, 12, 5), "edge": (56, 34, 12),
        "faint": (46, 28, 10), "dim": (120, 76, 28), "mid": (184, 120, 44),
        "fg": (255, 182, 82), "hi": (255, 232, 190), "acc": (255, 204, 96),
        "err": (255, 96, 80),
    },
    "ghiaccio": {
        "bg": (2, 7, 10), "card": (7, 16, 22), "edge": (22, 46, 60),
        "faint": (18, 38, 50), "dim": (52, 102, 130), "mid": (90, 160, 196),
        "fg": (140, 220, 255), "hi": (220, 246, 255), "acc": (96, 230, 255),
        "err": (255, 112, 92),
    },
}


def palette(name):
    return PALETTES.get((name or "").lower(), PALETTES["verde"])


def mix(a, b, t):
    """Interpola due colori (t=0 -> a, t=1 -> b)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def ease(t):
    """Easing morbido (in-out cubico)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


# ------------------------------------------------------------------ font

# modo: (passo, dimensione del puntino) -> cella = 6*passo x 10*passo
FONT_MODES = {
    "s": (1, 1),   # piccolo, pixel pieni (etichette)
    "d": (2, 1),   # puntini (titoli dot-matrix)
    "b": (2, 2),   # blocchi 2x (titoli pieni)
    "D": (3, 2),   # puntini grandi (logo, numeri grandi)
    "B": (4, 4),   # blocchi grandi ("ONLINE.")
}
_MASKS = {}


def _src(ch):
    g = glyph(ch)
    w = 7 if is_kana(ch) else 5
    src = np.zeros((9, w), dtype=bool)
    for r, row in enumerate(g[:9]):
        for c, on in enumerate(row[:w]):
            src[r, c] = on
    return src


def glyph_mask(ch, mode):
    key = (ch, mode)
    m = _MASKS.get(key)
    if m is not None:
        return m
    s = _src(ch)
    w = s.shape[1]
    if mode == "t":  # tratto sottile: punti a passo 2 uniti da linee di 1 px (cella 10x18)
        m = np.zeros((18, 2 * w + (2 if w > 5 else 0)), dtype=bool)
        for r in range(9):
            for c in range(w):
                if not s[r, c]:
                    continue
                y, x = 2 * r, 2 * c
                m[y, x] = True
                if c + 1 < w and s[r, c + 1]:
                    m[y, x + 1] = True
                if r + 1 < 9 and s[r + 1, c]:
                    m[y + 1, x] = True
                if r + 1 < 9 and c + 1 < w and s[r + 1, c + 1] and not s[r, c + 1] and not s[r + 1, c]:
                    m[y + 1, x + 1] = True
                if r + 1 < 9 and c >= 1 and s[r + 1, c - 1] and not s[r, c - 1] and not s[r + 1, c]:
                    m[y + 1, x - 1] = True
    else:
        p, k = FONT_MODES[mode]
        m = np.zeros((10 * p, (w + 1) * p), dtype=bool)
        for r in range(9):
            for c in range(w):
                if s[r, c]:
                    y, x = (r + 1) * p, c * p
                    m[y:y + k, x:x + k] = True
    _MASKS[key] = m
    return m


def advance(ch, mode):
    """Larghezza in pixel di un carattere (i katakana sono più larghi delle lettere latine)."""
    if is_kana(ch):
        return 16 if mode == "t" else 8 * FONT_MODES[mode][0]
    return cell_size(mode)[0]


def cell_size(mode):
    if mode == "t":
        return 10, 18
    p, _k = FONT_MODES[mode]
    return 6 * p, 10 * p


def text_width(s, mode):
    return sum(advance(c, mode) for c in s)


# ------------------------------------------------------------------ canvas

_RR = {}


def _rrect_mask(w, h, r):
    key = (w, h, r)
    m = _RR.get(key)
    if m is None:
        yy, xx = np.mgrid[0:h, 0:w]
        cx = np.clip(xx, r, w - 1 - r)
        cy = np.clip(yy, r, h - 1 - r)
        m = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        _RR[key] = m
    return m


class Canvas:
    def __init__(self, pal, w=W, h=H):
        self.p = pal
        self.w, self.h = w, h
        self.a = np.empty((h, w, 3), dtype=np.uint8)
        self.a[:, :] = pal["bg"]

    # --- primitive
    def rect(self, x, y, w, h, col):
        x0, y0, x1, y1 = max(0, int(x)), max(0, int(y)), min(self.w, int(x + w)), min(self.h, int(y + h))
        if x1 > x0 and y1 > y0:
            self.a[y0:y1, x0:x1] = col

    def card(self, x, y, w, h, r=8, fill=None, edge=None):
        """Card con angoli arrotondati e bordo di 1 px."""
        x, y, w, h = int(x), int(y), int(w), int(h)
        if w < 4 or h < 4:
            return
        r = min(r, w // 2, h // 2)
        outer = _rrect_mask(w, h, r)
        inner = np.zeros_like(outer)
        inner[1:-1, 1:-1] = _rrect_mask(w - 2, h - 2, max(0, r - 1))
        self._paint(x, y, outer, edge or self.p["edge"])
        self._paint(x, y, inner, fill or self.p["card"])

    def _paint(self, x, y, mask, col):
        h, w = mask.shape
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        self.a[y0:y1, x0:x1][mask[y0 - y:y1 - y, x0 - x:x1 - x]] = col

    def disc(self, cx, cy, r, col):
        """Disco perfettamente rotondo, centrato in (cx, cy) con raggio r (anche frazionario)."""
        key = ("disc", r)
        m = _RR.get(key)
        if m is None:
            n = int(math.ceil(2 * r))
            c = n / 2.0
            yy, xx = np.mgrid[0:n, 0:n]
            m = (xx + 0.5 - c) ** 2 + (yy + 0.5 - c) ** 2 <= r * r
            _RR[key] = m
        n = m.shape[0]
        self._paint(int(round(cx - n / 2.0)), int(round(cy - n / 2.0)), m, col)

    def dot(self, x, y, col, size=2):
        x, y = int(round(x)) - size // 2, int(round(y)) - size // 2
        self.rect(x, y, size, size, col)

    def hdots(self, x, y, w, col, step=3):
        for i in range(int(x), int(x + w), step):
            self.rect(i, y, 1, 1, col)

    def vdots(self, x, y, h, col, step=3):
        for i in range(int(y), int(y + h), step):
            self.rect(x, i, 1, 1, col)

    def brackets(self, x, y, w, h, col, n=10):
        """Angoli "mirino" (come nella card Vision AI)."""
        for cx, cy, dx, dy in ((x, y, 1, 1), (x + w - 1, y, -1, 1), (x, y + h - 1, 1, -1),
                               (x + w - 1, y + h - 1, -1, -1)):
            self.rect(cx if dx > 0 else cx - n + 1, cy, n, 1, col)
            self.rect(cx, cy if dy > 0 else cy - n + 1, 1, n, col)

    def text(self, x, y, s, col, mode="s"):
        x0 = x = int(x)
        y = int(y)
        for c in s:
            if c != " ":
                self._paint(x, y, glyph_mask(c, mode), col)
            x += advance(c, mode)
        return x - x0

    def text_right(self, xr, y, s, col, mode="s"):
        self.text(xr - text_width(s, mode), y, s, col, mode)

    def text_center(self, y, s, col, mode="s", x0=0, x1=W):
        self.text(x0 + (x1 - x0 - text_width(s, mode)) // 2, y, s, col, mode)

    def blit(self, arr, x, y):
        h, w = arr.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 > x0 and y1 > y0:
            self.a[y0:y1, x0:x1] = arr[y0 - y:y1 - y, x0 - x:x1 - x]

    def battery(self, xr, y, level, col, low):
        x = xr - 17
        self.rect(x, y, 15, 1, col)
        self.rect(x, y + 7, 15, 1, col)
        self.rect(x, y, 1, 8, col)
        self.rect(x + 14, y, 1, 8, col)
        self.rect(x + 15, y + 2, 2, 4, col)
        try:
            lvl = max(0, min(100, int(level)))
        except (TypeError, ValueError):
            return
        n = (lvl + 19) // 25
        for i in range(n):
            self.rect(x + 2 + i * 3, y + 2, 2, 4, low if lvl <= 15 else col)


# ------------------------------------------------------------------ testo

def prep(text, upper=False):
    t = normalize_text(text)
    return t.upper() if upper else t


def wrap(text, width):
    lines = []
    for para in normalize_text(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            if not word:
                continue
            while len(word) > width:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:width])
                word = word[width:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+=<>/"


def scramble(target, k, seed):
    """Effetto "decodifica": i caratteri si risolvono da sinistra a destra (k da 0 a 1)."""
    if k >= 1:
        return target
    n = len(target)
    solved = int(n * k)
    rng = np.random.default_rng(seed)
    out = list(target[:solved])
    for c in target[solved:]:
        out.append(" " if c == " " else SCRAMBLE_CHARS[int(rng.integers(0, len(SCRAMBLE_CHARS)))])
    return "".join(out)


# ------------------------------------------------------------------ particelle
# Ogni forma restituisce N posizioni (in pixel) e N colori. Cambiando forma le
# particelle scivolano dalla vecchia alla nuova posizione: transizione fluida.

N = 384


def _box(box):
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0


def _noise(i, t, f=1.0):
    return (math.sin(i * 1.7 + t * 6.1 * f) * 0.5 + math.sin(i * 0.63 - t * 3.7 * f) * 0.3
            + math.sin(i * 2.9 + t * 9.3 * f) * 0.2)


def shape_wave(t, box, p):
    """Forma d'onda a barre verticali di puntini (mentre si parla tenendo premuto il tasto)."""
    cx, cy, hw, hh = _box(box)
    cols = 48
    per = N // cols
    pos = np.zeros((N, 2))
    col = np.zeros((N, 3))
    hi, acc, mid = np.array(p["hi"], float), np.array(p["acc"], float), np.array(p["mid"], float)
    for j in range(cols):
        u = -1 + 2 * j / (cols - 1)
        env = max(0.0, 1 - abs(u) ** 1.6)
        lvl = abs(_noise(j, t))
        amp = env * (0.08 + 0.92 * lvl) * hh * 0.92
        x = cx + u * hw * 0.96
        ys = cy + np.linspace(-amp, amp, per)
        k = slice(j * per, (j + 1) * per)
        pos[k, 0] = x
        pos[k, 1] = ys
        c = mid + (acc - mid) * (env ** 2 * (0.3 + 0.7 * lvl))
        col[k] = c
        # le punte delle barre più luminose
        col[j * per] = col[(j + 1) * per - 1] = hi if lvl * env > 0.6 else c
    return pos, col


def shape_spectrum(t, box, p):
    """Barre di puntini che "parlano" (risposta vocale)."""
    cx, cy, hw, hh = _box(box)
    ncol, nrow = 16, 6
    pos = np.zeros((N, 2))
    col = np.zeros((N, 3))
    for k in range(N):
        c, r = (k // nrow) % ncol, k % nrow
        u = -1 + 2 * c / (ncol - 1)
        lvl = (0.35 + 0.65 * abs(_noise(c, t, 0.8))) * (1 - 0.35 * abs(u)) * nrow
        pos[k] = (cx + u * hw * 0.92, cy + hh * 0.85 - r * (hh * 1.7 / (nrow - 1)))
        if r < lvl:
            col[k] = p["hi"] if r + 1 >= lvl else (p["acc"] if c >= ncol - 3 else p["fg"])
        else:
            col[k] = p["faint"]
    order = np.argsort(pos[:, 0], kind="stable")
    return pos[order], col[order]


def shape_scatter(t, box, p):
    """Particelle disperse che tremolano (errore)."""
    cx, cy, hw, hh = _box(box)
    rng = np.random.default_rng(7)
    base = rng.uniform(-1, 1, size=(N, 2))
    base = base[np.argsort(base[:, 0])]
    jit = np.stack([np.sin(t * 13 + np.arange(N)), np.cos(t * 11 + np.arange(N) * 1.3)], axis=1) * 0.04
    pos = np.stack([cx + (base[:, 0] + jit[:, 0]) * hw * 0.9, cy + (base[:, 1] + jit[:, 1]) * hh * 0.9], axis=1)
    col = np.tile(np.array(p["err"], float), (N, 1))
    return pos, col


def shape_dog(t, box, p, dog=None):
    """Rocky, il Jack Russell (vedi deck_dog)."""
    return dog.points(t, box, p)


SHAPES = {"wave": shape_wave, "spectrum": shape_spectrum, "scatter": shape_scatter, "dog": shape_dog}


class Morph:
    """Gestisce il passaggio fluido tra una forma e l'altra."""

    DURATION = 0.8

    def __init__(self, shape="dog"):
        self.cur = shape
        self.prev = shape
        self.t0 = -10.0

    def set(self, shape, now):
        if shape != self.cur:
            self.prev, self.cur, self.t0 = self.cur, shape, now

    def active(self, now):
        return now - self.t0 < self.DURATION + 0.3

    def weight(self, now, shape):
        """Quanto la forma indicata è "presente" (0..1): utile per far comparire gli accessori."""
        k = ease((now - self.t0) / self.DURATION)
        if self.cur == shape and self.prev == shape:
            return 1.0
        if self.cur == shape:
            return k
        if self.prev == shape:
            return 1 - k
        return 0.0

    def points(self, now, box, p, **kw):
        pos_b, col_b = SHAPES[self.cur](now, box, p, **kw.get(self.cur, {}))
        k = (now - self.t0) / self.DURATION
        if k >= 1.3 or self.prev == self.cur:
            return pos_b, col_b
        pos_a, col_a = SHAPES[self.prev](now, box, p, **kw.get(self.prev, {}))
        # ritardo progressivo per particella (da sinistra a destra): la forma "scorre"
        delay = np.linspace(0, 0.3, N)
        kk = np.clip((k - delay) / 0.7, 0, 1)
        e = kk * kk * (3 - 2 * kk)
        lift = np.sin(e * math.pi) * 5
        pos = pos_a + (pos_b - pos_a) * e[:, None]
        pos[:, 1] -= lift
        col = col_a + (col_b - col_a) * e[:, None]
        return pos, col

    @staticmethod
    def draw(cv, pos, col, size=2):
        """Disegna i puntini (vettoriale: veloce anche con centinaia di puntini)."""
        xs = np.floor(pos[:, 0] + 0.5).astype(int) - size // 2   # arrotondamento uniforme
        ys = np.floor(pos[:, 1] + 0.5).astype(int) - size // 2
        c = np.clip(col, 0, 255).astype(np.uint8)
        for dy in range(size):
            for dx in range(size):
                x, y = xs + dx, ys + dy
                ok = (x >= 0) & (x < cv.w) & (y >= 0) & (y < cv.h)
                cv.a[y[ok], x[ok]] = c[ok]


# ------------------------------------------------------------------ immagini a puntini

BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16.0


def dot_image(src, w, h, p, pitch=3, dot=2, fit="cover"):
    """Ricostruisce un'immagine come matrice di puntini nei colori del tema."""
    img = Image.open(src) if isinstance(src, str) else src
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("L")
    gw, gh = max(1, w // pitch), max(1, h // pitch)
    if fit == "cover":
        img = ImageOps.fit(img, (gw, gh), Image.LANCZOS)
    else:
        img.thumbnail((gw, gh), Image.LANCZOS)
        c = Image.new("L", (gw, gh), 0)
        c.paste(img, ((gw - img.width) // 2, (gh - img.height) // 2))
        img = c
    img = ImageOps.autocontrast(img, cutoff=1)
    lum = np.asarray(img, dtype=np.float32) / 255.0
    ramp = [p["card"], p["faint"], p["dim"], p["mid"], p["fg"], p["hi"]]
    th = np.tile(BAYER4, (gh // 4 + 1, gw // 4 + 1))[:gh, :gw]
    idx = np.clip(np.floor(lum * (len(ramp) - 1) + th).astype(int), 0, len(ramp) - 1)
    out = np.empty((h, w, 3), dtype=np.uint8)
    out[:, :] = p["card"]
    pal = np.array(ramp, dtype=np.uint8)
    for gy in range(gh):
        for gx in range(gw):
            i = idx[gy, gx]
            if i:
                out[gy * pitch:gy * pitch + dot, gx * pitch:gx * pitch + dot] = pal[i]
    return out


# ------------------------------------------------------------------ effetti

def glitch(arr, amount, rng, p):
    """Glitch digitale: bande spostate, sdoppiamento, blocchi e righe di rumore."""
    if amount <= 0:
        return arr
    a = arr.copy()
    h, w = a.shape[:2]
    for _ in range(int(1 + amount * 8)):
        y = int(rng.integers(0, h))
        bh = int(rng.integers(1, 3 + int(amount * 18)))
        dx = int(rng.integers(-int(3 + amount * 34), int(4 + amount * 34)))
        a[y:y + bh] = np.roll(a[y:y + bh], dx, axis=1)
    d = int(1 + amount * 4)
    lit = a.max(axis=2) > 90
    ghost = np.roll(lit, d, axis=1) & ~lit
    a[ghost] = (a[ghost] * 0.4 + np.array(p["hi"]) * 0.6).astype(np.uint8)
    ghost2 = np.roll(lit, -d, axis=1) & ~lit
    a[ghost2] = (a[ghost2] * 0.4 + np.array(p["dim"]) * 0.6).astype(np.uint8)
    for _ in range(int(amount * 4)):
        bw, bh = int(rng.integers(12, 90)), int(rng.integers(3, 18))
        sx, sy = int(rng.integers(0, w - bw)), int(rng.integers(0, h - bh))
        tx, ty = int(rng.integers(0, w - bw)), int(rng.integers(0, h - bh))
        a[ty:ty + bh, tx:tx + bw] = a[sy:sy + bh, sx:sx + bw]
    for _ in range(int(amount * 6)):
        y = int(rng.integers(0, h))
        a[y, ::2] = p["mid"] if rng.random() < 0.5 else p["hi"]
    return a


def static_noise(rng, p, density):
    g = rng.random((H // 2, W // 2)) < density
    lv = rng.random((H // 2, W // 2))
    out = np.empty((H // 2, W // 2, 3), dtype=np.uint8)
    out[:, :] = p["bg"]
    out[g & (lv > 0.7)] = p["mid"]
    out[g & (lv <= 0.7)] = p["dim"]
    return np.repeat(np.repeat(out, 2, axis=0), 2, axis=1)


_VIG = {}


def crt(arr, strength):
    """Effetto monitor CRT: bagliore dei fosfori, scanline e vignettatura."""
    if strength <= 0:
        return arr
    img = Image.fromarray(arr, "RGB")
    glow = img.filter(ImageFilter.GaussianBlur(1.8))
    out = ImageChops.lighter(img, Image.blend(img, glow, 0.7))
    a = np.asarray(out).astype(np.float32)
    a[1::2] *= 1.0 - 0.3 * strength
    v = _VIG.get(strength)
    if v is None:
        yy, xx = np.mgrid[0:H, 0:W]
        d = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
        v = (1.0 - 0.22 * strength * d / 2)[:, :, None].astype(np.float32)
        _VIG[strength] = v
    a *= v
    return np.clip(a, 0, 255).astype(np.uint8)


def to_rgb565(arr):
    a = arr.astype(np.uint16)
    v = ((a[:, :, 0] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 2] >> 3)
    out = np.empty(v.shape + (2,), dtype=np.uint8)
    out[:, :, 0] = v >> 8
    out[:, :, 1] = v & 0xFF
    return out.tobytes()


def crt_collapse(arr, k, p):
    """Spegnimento del tubo catodico: l'immagine si schiaccia in una riga, poi in un punto."""
    out = np.empty_like(arr)
    out[:, :] = (0, 0, 0)
    if k < 0.6:
        hh = max(1, int(H * (1 - k / 0.6)))
        small = np.asarray(Image.fromarray(arr).resize((W, hh), Image.BILINEAR))
        y = (H - hh) // 2
        out[y:y + hh] = np.clip(small.astype(np.int32) + int(120 * k), 0, 255).astype(np.uint8)
    elif k < 1.0:
        ww = max(2, int(W * (1 - (k - 0.6) / 0.4)))
        x = (W - ww) // 2
        out[H // 2 - 1:H // 2 + 1, x:x + ww] = p["hi"]
    return out


def file_exists(path):
    return bool(path) and os.path.exists(path)
