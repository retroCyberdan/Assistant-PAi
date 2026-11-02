"""Motore grafico Videotex per il display 240x280 del PiSugar Whisplay.

Riproduce le caratteristiche dei terminali Videotex/Teletext anni '80:
  - griglia a caratteri (20 colonne x 14 righe con celle 12x20 px);
  - font bitmap 5x7 raddoppiato con "character rounding" (come il chip SAA5050);
  - grafica a mosaico a sestanti (2x3 blocchi per cella), contigua o separata;
  - un solo colore di primo piano e uno di sfondo per cella;
  - palette a 8 colori CEPT/Teletext (o livelli di grigio per il Minitel);
  - effetto CRT opzionale (scanline e bagliore dei fosfori).
"""

import numpy as np
from PIL import Image, ImageFilter, ImageChops

from vtx_font import CELL_W, CELL_H, glyph, normalize_text

SCALE = 2
CW = CELL_W * SCALE   # 12 px
CH = CELL_H * SCALE   # 20 px

# Palette CEPT / Teletext a 8 colori
BLACK = (0, 0, 0)
RED = (255, 40, 40)
GREEN = (40, 255, 40)
YELLOW = (255, 255, 40)
BLUE = (40, 40, 255)
MAGENTA = (255, 40, 255)
CYAN = (40, 255, 255)
WHITE = (255, 255, 255)
CEPT_PALETTE = [BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE]


def _gray(v):
    return (v, v, v)


THEMES = {
    # Videotel (SIP, Italia 1985): pagine su fondo blu, testo azzurro chiaro
    "videotel": {
        "label": "VIDEOTEL",
        "bg": (28, 72, 160),
        "fg": (178, 220, 255),
        "dim": (110, 160, 225),
        "title": (255, 255, 255),
        "user": (255, 255, 120),
        "accent": (120, 255, 255),
        "rule": (150, 200, 255),
        "logo": (190, 230, 255),
        "error": (255, 120, 120),
        "palette": CEPT_PALETTE,
        "separated_logo": True,
    },
    # Minitel 1 (PTT, Francia 1982): monocromatico, i colori diventano grigi
    "minitel": {
        "label": "MINITEL",
        "bg": (8, 8, 10),
        "fg": (225, 228, 232),
        "dim": (140, 142, 146),
        "title": (255, 255, 255),
        "user": (190, 190, 190),
        "accent": (255, 255, 255),
        "rule": (160, 160, 160),
        "logo": (235, 235, 235),
        "error": (255, 255, 255),
        # ordine di luminanza del Minitel: nero, blu, rosso, magenta, verde, ciano, giallo, bianco
        "palette": [_gray(v) for v in (0, 60, 95, 130, 160, 190, 220, 255)],
        "separated_logo": False,
    },
    # Televideo / Teletext (RAI 1984, Ceefax): fondo nero, 8 colori saturi
    "televideo": {
        "label": "TELEVIDEO",
        "bg": BLACK,
        "fg": WHITE,
        "dim": CYAN,
        "title": YELLOW,
        "user": GREEN,
        "accent": CYAN,
        "rule": BLUE,
        "logo": CYAN,
        "error": RED,
        "palette": CEPT_PALETTE,
        "separated_logo": False,
        "header_band": BLUE,
    },
    # Monitor a fosfori verdi
    "fosfori": {
        "label": "TERMINALE",
        "bg": (2, 14, 4),
        "fg": (80, 255, 120),
        "dim": (40, 160, 70),
        "title": (170, 255, 190),
        "user": (140, 255, 160),
        "accent": (170, 255, 190),
        "rule": (50, 190, 80),
        "logo": (110, 255, 140),
        "error": (170, 255, 190),
        "palette": [(0, 10, 0), (20, 70, 30), (30, 100, 45), (40, 130, 60),
                    (50, 160, 75), (60, 190, 90), (70, 220, 105), (110, 255, 140)],
        "separated_logo": False,
    },
}


_MASK_CACHE = {}


def glyph_mask(ch, rounding=True):
    key = (ch, rounding)
    m = _MASK_CACHE.get(key)
    if m is not None:
        return m
    g = glyph(ch)
    src = np.zeros((CELL_H, CELL_W), dtype=bool)
    for r, row in enumerate(g):
        for c, on in enumerate(row[:5]):
            if on and r + 1 < CELL_H:
                src[r + 1, c] = True
    m = np.repeat(np.repeat(src, SCALE, axis=0), SCALE, axis=1)
    if rounding:
        # Character rounding stile SAA5050: smussa le diagonali quando si raddoppia
        for r in range(CELL_H - 1):
            for c in range(CELL_W - 1):
                a, b = src[r, c], src[r, c + 1]
                d, e = src[r + 1, c], src[r + 1, c + 1]
                if a and e and not b and not d:
                    m[2 * r + 1, 2 * c + 2] = True
                    m[2 * r + 2, 2 * c + 1] = True
                if b and d and not a and not e:
                    m[2 * r + 1, 2 * c + 1] = True
                    m[2 * r + 2, 2 * c + 2] = True
    _MASK_CACHE[key] = m
    return m


def sextant_mask(bits, separated=False):
    """Maschera 20x12 di un carattere a mosaico (6 bit: 2 colonne x 3 righe)."""
    key = ("sx", bits, separated)
    m = _MASK_CACHE.get(key)
    if m is not None:
        return m
    m = np.zeros((CH, CW), dtype=bool)
    xs = [(0, CW // 2), (CW // 2, CW)]
    ys = [(0, 7), (7, 13), (13, CH)]
    for i in range(6):
        if bits & (1 << i):
            x0, x1 = xs[i % 2]
            y0, y1 = ys[i // 2]
            if separated:
                x1 -= 2
                y1 -= 2
            m[y0:y1, x0:x1] = True
    _MASK_CACHE[key] = m
    return m


class Cell:
    __slots__ = ("ch", "fg", "bg", "mosaic", "separated", "flash")

    def __init__(self, ch=" ", fg=WHITE, bg=BLACK, mosaic=None, separated=False, flash=False):
        self.ch = ch
        self.fg = fg
        self.bg = bg
        self.mosaic = mosaic
        self.separated = separated
        self.flash = flash


class Screen:
    """Una pagina Videotex: griglia di celle disegnabile su un'immagine PIL."""

    def __init__(self, width=240, height=280, rounding=True):
        self.width = width
        self.height = height
        self.cols = width // CW
        self.rows = height // CH
        self.off_x = (width - self.cols * CW) // 2
        self.off_y = (height - self.rows * CH) // 2
        self.rounding = rounding
        self.clear()

    def clear(self, bg=BLACK, fg=WHITE):
        self.bg = bg
        self.cells = [[Cell(" ", fg, bg) for _ in range(self.cols)] for _ in range(self.rows)]

    def put(self, col, row, text, fg, bg=None, flash=False):
        """Scrive testo a partire da (col, row); il testo oltre il bordo viene tagliato."""
        if row < 0 or row >= self.rows:
            return
        for i, ch in enumerate(normalize_text(text)):
            c = col + i
            if 0 <= c < self.cols:
                cell = self.cells[row][c]
                cell.ch, cell.fg, cell.mosaic, cell.flash = ch, fg, None, flash
                cell.bg = bg if bg is not None else self.bg

    def put_center(self, row, text, fg, bg=None):
        text = normalize_text(text)
        self.put(max(0, (self.cols - len(text)) // 2), row, text, fg, bg)

    def put_right(self, row, text, fg, bg=None, margin=0):
        text = normalize_text(text)
        self.put(self.cols - len(text) - margin, row, text, fg, bg)

    def fill_row(self, row, bg):
        if 0 <= row < self.rows:
            for cell in self.cells[row]:
                cell.bg = bg

    def put_mosaic(self, col, row, bits, fg, bg=None, separated=False):
        if 0 <= row < self.rows and 0 <= col < self.cols:
            cell = self.cells[row][col]
            cell.ch, cell.mosaic, cell.fg, cell.separated = " ", bits, fg, separated
            cell.bg = bg if bg is not None else self.bg

    def put_bitmap(self, col, row, bitmap, fg, bg=None, separated=False, max_rows=None):
        """Disegna una bitmap booleana (in "sotto-pixel" 2x3 per cella) come mosaico."""
        h, w = bitmap.shape
        cell_rows = (h + 2) // 3
        cell_cols = (w + 1) // 2
        if max_rows is not None:
            cell_rows = min(cell_rows, max_rows)
        for cr in range(cell_rows):
            for cc in range(cell_cols):
                bits = 0
                for i in range(6):
                    y = cr * 3 + i // 2
                    x = cc * 2 + i % 2
                    if y < h and x < w and bitmap[y, x]:
                        bits |= 1 << i
                if bits:
                    self.put_mosaic(col + cc, row + cr, bits, fg, bg, separated)
        return cell_rows, cell_cols

    def put_color_mosaic(self, col, row, rgb, palette, separated=False):
        """Disegna un'immagine RGB (array h x w x 3, in sotto-pixel) come mosaico a colori.

        Rispetta il vincolo Videotex: ogni cella ha al massimo 2 colori.
        """
        pal = np.array(palette, dtype=np.float32)
        n = len(palette)
        pairs = [(i, j) for i in range(n) for j in range(i, n)]
        pi = np.array([p[0] for p in pairs])
        pj = np.array([p[1] for p in pairs])
        h, w, _ = rgb.shape
        rgbf = rgb.astype(np.float32)
        # distanza di ogni sotto-pixel da ogni colore della palette
        dist = ((rgbf[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
        for cr in range((h + 2) // 3):
            for cc in range((w + 1) // 2):
                block = dist[cr * 3:cr * 3 + 3, cc * 2:cc * 2 + 2]  # (<=3, <=2, n)
                if block.size == 0:
                    continue
                bh, bw = block.shape[:2]
                flat = block.reshape(-1, n)
                # per ogni coppia (i, j) l'errore minimo assegnando ogni sotto-pixel
                err = np.minimum(flat[:, pi], flat[:, pj]).sum(axis=0)
                k = int(err.argmin())
                i, j = int(pi[k]), int(pj[k])
                on = flat[:, j] < flat[:, i]
                # il colore più frequente fa da sfondo
                if on.sum() > on.size / 2:
                    i, j = j, i
                    on = ~on
                bits = 0
                for idx in range(on.size):
                    if on[idx]:
                        y, x = idx // bw, idx % bw
                        bits |= 1 << (y * 2 + x)
                self.put_mosaic(col + cc, row + cr, bits,
                                tuple(int(v) for v in pal[j]),
                                tuple(int(v) for v in pal[i]), separated)

    def render(self, flash_on=True, cursor=None, cursor_color=None):
        arr = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        arr[:, :] = self.bg
        for r in range(self.rows):
            y = self.off_y + r * CH
            for c in range(self.cols):
                x = self.off_x + c * CW
                cell = self.cells[r][c]
                block = arr[y:y + CH, x:x + CW]
                block[:, :] = cell.bg
                if cell.mosaic is not None:
                    if cell.mosaic:
                        block[sextant_mask(cell.mosaic, cell.separated)] = cell.fg
                elif cell.ch != " " and (flash_on or not cell.flash):
                    block[glyph_mask(cell.ch, self.rounding)] = cell.fg
        if cursor is not None:
            cc, cr = cursor
            if 0 <= cc < self.cols and 0 <= cr < self.rows:
                x = self.off_x + cc * CW
                y = self.off_y + cr * CH
                arr[y + CH - 4:y + CH - 2, x:x + CW - 2] = cursor_color or WHITE
        return Image.fromarray(arr, "RGB")


def crt_effect(img, strength=1.0):
    """Effetto monitor CRT: bagliore dei fosfori e scanline."""
    if strength <= 0:
        return img
    glow = img.filter(ImageFilter.GaussianBlur(1.6))
    out = ImageChops.lighter(img, Image.blend(img, glow, 0.6))
    arr = np.asarray(out).astype(np.float32)
    factor = 1.0 - 0.28 * strength
    arr[1::2] *= factor
    # leggera vignettatura ai bordi
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1.0 - 0.18 * strength * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    arr *= vig[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def wrap_text(text, width):
    """A capo per parola su una griglia a larghezza fissa."""
    lines = []
    for para in normalize_text(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for word in words:
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


def text_bitmap(text, scale=1):
    """Bitmap booleana di un testo col font 5x7 (per creare loghi a mosaico)."""
    text = normalize_text(text)
    if not text:
        return np.zeros((7, 1), dtype=bool)
    has_desc = any(len(glyph(ch)) > 7 for ch in text)
    h = 9 if has_desc else 7
    w = len(text) * 6 - 1
    bmp = np.zeros((h, w), dtype=bool)
    for i, ch in enumerate(text):
        for r, row in enumerate(glyph(ch)[:h]):
            for c, on in enumerate(row[:5]):
                if on:
                    bmp[r, i * 6 + c] = True
    if scale > 1:
        bmp = np.repeat(np.repeat(bmp, scale, axis=0), scale, axis=1)
    return bmp


def image_to_subpixels(path, max_w, max_h, mono=False, threshold=128):
    """Carica un'immagine e la riduce in sotto-pixel mosaico (2x3 per cella).

    I sotto-pixel non sono quadrati (6x6.7 px), quindi si compensa l'altezza.
    """
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("RGB")
    sub_aspect = (CH / 3) / (CW / 2)  # ~1.11
    w, h = img.size
    ratio = min(max_w / w, max_h * sub_aspect / h)
    nw = max(1, int(round(w * ratio)))
    nh = max(1, int(round(h * ratio / sub_aspect)))
    nw, nh = min(nw, max_w), min(nh, max_h)
    small = img.resize((nw, nh), Image.LANCZOS)
    arr = np.asarray(small)
    if mono:
        lum = arr.astype(np.float32) @ np.array([0.299, 0.587, 0.114])
        return lum >= threshold
    return arr
