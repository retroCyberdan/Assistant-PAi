"""Stile "pixel cyberpunk" per l'interfaccia Videotex.

Pannelli a linee sottili, font a pixel a tratto singolo, immagini ricostruite
in pixel con retinatura ordinata (Bayer) su una rampa di 6 tinte, glitch
digitali (spostamento di bande, separazione RGB, rumore) e avvio animato con
il logo dell'utente.

Variabili d'ambiente specifiche (oltre a quelle di videotex_ui.py):
  VTX_CYBER_PALETTE  teal | verde | ambra | viola        (default teal)
  VTX_UNIT_ID        sigla grande nella pagina iniziale    (default PAi-01)
  VTX_TAGLINE        frase mostrata sotto il logo all'avvio
  VTX_FOOTER_LINES   due righe del piè di pagina separate da |
  VTX_GLITCH         0..1 intensità dei glitch a riposo   (default 0.5)
  VTX_PIXEL          dimensione del "pixel" delle immagini (default 2)
  VTX_UPPERCASE      1 = testi in maiuscolo come nei terminali (default 1)
"""

import os
import socket
import time

import numpy as np
from PIL import Image, ImageOps

from vtx_font import glyph, normalize_text

# ------------------------------------------------------------------ palette

PALETTES = {
    # dal più scuro al più chiaro
    "teal": [(5, 13, 15), (12, 36, 40), (22, 70, 76), (44, 128, 134), (96, 200, 196), (186, 248, 238)],
    "verde": [(4, 10, 8), (9, 38, 40), (18, 78, 76), (34, 136, 116), (66, 200, 140), (160, 244, 176)],
    "ambra": [(12, 7, 3), (40, 20, 6), (86, 44, 10), (150, 84, 18), (226, 146, 40), (255, 214, 130)],
    "viola": [(10, 6, 16), (34, 14, 48), (76, 30, 104), (140, 60, 176), (214, 120, 232), (255, 206, 255)],
}
GLITCH_A = (255, 40, 160)   # magenta per le aberrazioni cromatiche
GLITCH_B = (40, 230, 255)   # ciano
ALERT = (255, 80, 90)


def _env(name, default):
    v = os.getenv(name)
    return v if v not in (None, "") else default


PALETTE_NAME = _env("VTX_CYBER_PALETTE", "teal").lower()
RAMP = PALETTES.get(PALETTE_NAME, PALETTES["teal"])
BG, DARK, MID, LINE, FG, HI = RAMP
UNIT_ID = _env("VTX_UNIT_ID", "PAi-01")
TAGLINE = _env("VTX_TAGLINE", "SISTEMA NEURALE ONLINE")
FOOTER_LINES = _env("VTX_FOOTER_LINES", "PROPRIETA' DI PAi SYSTEMS|UNITA' DI ASSISTENZA VOCALE").split("|")
try:
    GLITCH = max(0.0, min(1.0, float(_env("VTX_GLITCH", "0.5"))))
except ValueError:
    GLITCH = 0.5
try:
    PIXEL = max(1, int(_env("VTX_PIXEL", "2")))
except ValueError:
    PIXEL = 2
UPPER = _env("VTX_UPPERCASE", "1") == "1"

# ------------------------------------------------------------------ font

_CACHE = {}


def _src(ch):
    g = glyph(ch)
    src = np.zeros((9, 5), dtype=bool)
    for r, row in enumerate(g[:9]):
        for c, on in enumerate(row[:5]):
            src[r, c] = on
    return src


def mask_small(ch):
    """Font 5x7 a dimensione reale (cella 6x10): etichette e didascalie."""
    key = ("s", ch)
    if key not in _CACHE:
        m = np.zeros((10, 6), dtype=bool)
        m[1:10, 0:5] = _src(ch)
        _CACHE[key] = m
    return _CACHE[key]


def mask_thin(ch):
    """Font "a tratto sottile": griglia 5x7 a passo 2 unita da linee di 1 px (cella 10x18)."""
    key = ("t", ch)
    if key in _CACHE:
        return _CACHE[key]
    s = _src(ch)
    m = np.zeros((18, 10), dtype=bool)
    for r in range(9):
        for c in range(5):
            if not s[r, c]:
                continue
            y, x = 2 * r, 2 * c
            if y < 18:
                m[y, x] = True
            if c + 1 < 5 and s[r, c + 1]:
                m[y, x + 1] = True
            if r + 1 < 9 and s[r + 1, c] and y + 1 < 18:
                m[y + 1, x] = True
            # diagonali solo se non c'è già un percorso ortogonale
            if r + 1 < 9 and c + 1 < 5 and s[r + 1, c + 1] and not s[r, c + 1] and not s[r + 1, c]:
                m[y + 1, x + 1] = True
            if r + 1 < 9 and c - 1 >= 0 and s[r + 1, c - 1] and not s[r, c - 1] and not s[r + 1, c]:
                m[y + 1, x - 1] = True
    _CACHE[key] = m
    return m


def mask_bold(ch):
    """Font 5x7 raddoppiato a blocchi (cella 12x20): titoli grandi."""
    key = ("b", ch)
    if key not in _CACHE:
        s = _src(ch)
        m = np.zeros((20, 12), dtype=bool)
        m[2:20, 0:10] = np.repeat(np.repeat(s, 2, axis=0), 2, axis=1)
        _CACHE[key] = m
    return _CACHE[key]


FONTS = {"small": (mask_small, 6, 10), "thin": (mask_thin, 10, 18), "bold": (mask_bold, 12, 20)}


def prep(text):
    text = normalize_text(text)
    return text.upper() if UPPER else text


def wrap(text, width):
    lines = []
    for para in prep(text).split("\n"):
        cur = ""
        for word in para.split(" "):
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


# ------------------------------------------------------------------ disegno


class Canvas:
    def __init__(self, w=240, h=280, bg=BG):
        self.w, self.h = w, h
        self.a = np.zeros((h, w, 3), dtype=np.uint8)
        self.a[:, :] = bg

    def rect(self, x, y, w, h, col):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 > x0 and y1 > y0:
            self.a[y0:y1, x0:x1] = col

    def hline(self, x, y, w, col, dash=0):
        if dash:
            for i in range(x, x + w, dash * 2):
                self.rect(i, y, dash, 1, col)
        else:
            self.rect(x, y, w, 1, col)

    def vline(self, x, y, h, col):
        self.rect(x, y, 1, h, col)

    def frame(self, x, y, w, h, col):
        self.hline(x, y, w, col)
        self.hline(x, y + h - 1, w, col)
        self.vline(x, y, h, col)
        self.vline(x + w - 1, y, h, col)

    def corners(self, x, y, w, h, col, n=5):
        """Angoli "a mirino" come nei pannelli HUD."""
        for cx, cy, dx, dy in ((x, y, 1, 1), (x + w - 1, y, -1, 1),
                               (x, y + h - 1, 1, -1), (x + w - 1, y + h - 1, -1, -1)):
            for i in range(n):
                self.rect(cx + dx * i, cy, 1, 1, col)
                self.rect(cx, cy + dy * i, 1, 1, col)

    def text(self, x, y, s, col, size="thin", spacing=0):
        fn, cw, ch = FONTS[size]
        for i, c in enumerate(s):
            if c == " ":
                continue
            m = fn(c)
            xx = x + i * (cw + spacing)
            if xx >= self.w or xx + cw <= 0:
                continue
            mh, mw = m.shape
            y0, y1 = max(0, y), min(self.h, y + mh)
            x0, x1 = max(0, xx), min(self.w, xx + mw)
            if y1 <= y0 or x1 <= x0:
                continue
            sub = m[y0 - y:y1 - y, x0 - xx:x1 - xx]
            self.a[y0:y1, x0:x1][sub] = col
        return len(s) * (cw + spacing)

    def text_right(self, xr, y, s, col, size="thin"):
        cw = FONTS[size][1]
        self.text(xr - len(s) * cw, y, s, col, size)

    def text_center(self, y, s, col, size="thin", x0=0, x1=None):
        x1 = self.w if x1 is None else x1
        cw = FONTS[size][1]
        self.text(x0 + (x1 - x0 - len(s) * cw) // 2, y, s, col, size)

    def blit(self, arr, x, y):
        h, w = arr.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 > x0 and y1 > y0:
            self.a[y0:y1, x0:x1] = arr[y0 - y:y1 - y, x0 - x:x1 - x]

    def battery(self, xr, y, level):
        """Icona batteria a 5 segmenti (allineata a destra in xr)."""
        x = xr - 22
        self.frame(x, y, 20, 9, FG)
        self.rect(x + 20, y + 2, 2, 5, FG)
        if level is None:
            return
        try:
            lvl = int(level)
        except (TypeError, ValueError):
            return
        segs = max(0, min(5, (lvl + 10) // 20))
        col = ALERT if lvl <= 15 else HI
        for i in range(segs):
            self.rect(x + 2 + i * 3, y + 2, 2, 5, col)

    def emblem(self, x, y, col, dark):
        """Piccolo stemma a barre (decorazione del piè di pagina)."""
        for i, hgt in enumerate((14, 10, 14, 6)):
            self.rect(x + i * 3, y + (14 - hgt), 2, hgt, col if i % 2 == 0 else dark)
        self.rect(x - 2, y + 15, 16, 1, dark)

    def barcode(self, x, y, h, seed, col):
        rng = np.random.default_rng(seed)
        xx = x
        for _ in range(14):
            w = int(rng.integers(1, 3))
            self.rect(xx, y, w, h, col)
            xx += w + int(rng.integers(1, 3))

    def image(self):
        return Image.fromarray(self.a, "RGB")


# ------------------------------------------------------------------ immagini in pixel

BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16.0


def pixelize(img, w, h, ramp=None, pixel=None, fit="cover", lo=0):
    """Ricostruisce un'immagine in pixel art: riduzione, contrasto, retinatura Bayer su rampa.

    Restituisce un array (h, w, 3). `lo` = primo indice della rampa da usare
    (1 evita il nero puro, utile per far risaltare il soggetto).
    """
    ramp = RAMP if ramp is None else ramp
    pixel = PIXEL if pixel is None else pixel
    if isinstance(img, str):
        img = Image.open(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("L")
    sw, sh = max(1, w // pixel), max(1, h // pixel)
    if fit == "cover":
        img = ImageOps.fit(img, (sw, sh), Image.LANCZOS)
    else:
        img.thumbnail((sw, sh), Image.LANCZOS)
        canvas = Image.new("L", (sw, sh), 0)
        canvas.paste(img, ((sw - img.width) // 2, (sh - img.height) // 2))
        img = canvas
    img = ImageOps.autocontrast(img, cutoff=1)
    lum = np.asarray(img, dtype=np.float32) / 255.0
    levels = len(ramp) - lo
    th = np.tile(BAYER4, (sh // 4 + 1, sw // 4 + 1))[:sh, :sw]
    v = lum * (levels - 1)
    idx = np.floor(v + th).astype(np.int32)
    idx = np.clip(idx, 0, levels - 1) + lo
    pal = np.array(ramp, dtype=np.uint8)
    out = pal[idx]
    out = np.repeat(np.repeat(out, pixel, axis=0), pixel, axis=1)
    full = np.zeros((h, w, 3), dtype=np.uint8)
    full[:, :] = ramp[0]
    full[:out.shape[0], :out.shape[1]] = out[:h, :w]
    return full


def default_logo(size):
    """Logo di ripiego: il testo VTX_LOGO_TEXT in grande, sfumato con retinatura."""
    from vtx_render import text_bitmap
    text = _env("VTX_LOGO_TEXT", "PAi")
    bmp = text_bitmap(text, 1)
    h, w = bmp.shape
    scale = max(1, min(size[0] // (w + 2), size[1] // (h + 2)))
    big = np.repeat(np.repeat(bmp, scale, axis=0), scale, axis=1).astype(np.float32)
    # sfumatura verticale + bagliore
    grad = np.linspace(1.0, 0.45, big.shape[0])[:, None]
    lum = big * grad
    img = Image.fromarray((lum * 255).astype(np.uint8), "L")
    canvas = Image.new("L", size, 0)
    canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return canvas


def load_logo(w, h):
    path = _env("VTX_LOGO_IMAGE", "")
    if path and os.path.exists(path):
        try:
            return pixelize(path, w, h, fit="contain")
        except Exception as e:
            print(f"[Cyber] Logo non leggibile: {e}")
    return pixelize(default_logo((w, h)), w, h, pixel=1, fit="contain")


# ------------------------------------------------------------------ glitch


def glitch(arr, amount, rng):
    """Applica un glitch digitale a un array RGB (in place su una copia)."""
    if amount <= 0:
        return arr
    a = arr.copy()
    h, w = a.shape[:2]
    # 1. bande orizzontali spostate
    for _ in range(int(1 + amount * 7)):
        y = int(rng.integers(0, h))
        bh = int(rng.integers(1, 4 + int(amount * 16)))
        dx = int(rng.integers(-int(4 + amount * 30), int(5 + amount * 30)))
        a[y:y + bh] = np.roll(a[y:y + bh], dx, axis=1)
    # 2. separazione RGB (aberrazione cromatica magenta/ciano)
    d = int(1 + amount * 4)
    lum = a.mean(axis=2) > 90
    ghost_r = np.roll(lum, d, axis=1) & ~lum
    ghost_b = np.roll(lum, -d, axis=1) & ~lum
    a[ghost_r] = (a[ghost_r] * 0.3 + np.array(GLITCH_A) * 0.7).astype(np.uint8)
    a[ghost_b] = (a[ghost_b] * 0.3 + np.array(GLITCH_B) * 0.7).astype(np.uint8)
    # 3. blocchi duplicati
    for _ in range(int(amount * 4)):
        bw, bh = int(rng.integers(10, 80)), int(rng.integers(3, 20))
        sx, sy = int(rng.integers(0, w - bw)), int(rng.integers(0, h - bh))
        tx, ty = int(rng.integers(0, w - bw)), int(rng.integers(0, h - bh))
        a[ty:ty + bh, tx:tx + bw] = a[sy:sy + bh, sx:sx + bw]
    # 4. righe di rumore
    for _ in range(int(amount * 5)):
        y = int(rng.integers(0, h))
        noise = rng.integers(0, len(RAMP), size=w)
        a[y] = np.array(RAMP, dtype=np.uint8)[noise]
    return a


def static_noise(h, w, rng, density=0.5):
    idx = rng.integers(0, len(RAMP), size=(h // 2, w // 2))
    idx = np.where(rng.random((h // 2, w // 2)) < density, idx, 0)
    out = np.array(RAMP, dtype=np.uint8)[idx]
    return np.repeat(np.repeat(out, 2, axis=0), 2, axis=1)[:h, :w]


# ------------------------------------------------------------------ informazioni di sistema


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "0.0.0.0"


def glitch_wav(path):
    """Suono di avvio: rumore digitale "bitcrushed", sweep e cinguettii."""
    import wave
    sr = 16000
    rng = np.random.default_rng(7)
    parts = []
    for i in range(6):
        n = int(sr * rng.uniform(0.04, 0.12))
        burst = rng.uniform(-1, 1, n)
        step = int(rng.integers(4, 30))
        burst = np.repeat(burst[::step], step)[:n]  # bitcrush
        parts.append(burst * 0.25)
        parts.append(np.zeros(int(sr * rng.uniform(0.03, 0.2))))
    t = np.arange(int(sr * 0.9)) / sr
    sweep = np.sin(2 * np.pi * (60 + 900 * t ** 2) * t) * np.linspace(0.05, 0.3, t.size)
    parts.append(np.sign(sweep) * 0.12 + sweep * 0.3)
    for f in (1760, 2349, 3136):
        tt = np.arange(int(sr * 0.06)) / sr
        parts.append(np.sign(np.sin(2 * np.pi * f * tt)) * 0.12)
        parts.append(np.zeros(int(sr * 0.04)))
    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
