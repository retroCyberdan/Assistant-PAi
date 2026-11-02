#!/usr/bin/env python3
"""Interfaccia Videotex per whisplay-ai-chatbot.

Sostituisce `chatbot-ui.py`: parla lo stesso protocollo socket (TCP 12345,
JSON per riga) con il processo Node del chatbot, ma disegna le pagine sul
display del Whisplay in stile Videotel / Minitel / Televideo.

Configurazione tramite variabili d'ambiente (nel file .env del chatbot):
  VTX_THEME          videotel | minitel | televideo | fosfori   (default videotel)
  VTX_SERVICE_NAME   nome del servizio in testata               (default PAiTEL)
  VTX_LOGO_TEXT      testo del logo a mosaico                   (default PAi)
  VTX_LOGO_IMAGE     percorso di un'immagine da usare come logo (PNG/JPG)
  VTX_LOGO_MONO      1 = logo immagine in un solo colore        (default 0)
  VTX_HOME_LINES     righe della home separate da |
  VTX_FOOTER         testo a destra nel piè di pagina           (default pai.local)
  VTX_BOOT           full | quick | off                         (default full)
  VTX_DIAL           numero composto all'avvio                  (default 165)
  VTX_MODEM_SOUND    1 = suono del modem all'avvio              (default 1)
  VTX_AUDIO_DEVICE   dispositivo ALSA per il suono del modem    (default: auto)
  VTX_BAUD           velocità di "trasmissione" delle pagine    (default 1200)
  VTX_CRT            0..1 intensità dell'effetto monitor CRT    (default 0.7)
  VTX_ROUNDING       1 = smussatura caratteri stile SAA5050     (default 1)
  VTX_IMAGE_MODE     mosaic | photo  (come mostrare le immagini generate)
  VTX_SYNC_SPEECH    1 = il testo della risposta segue la voce  (default 1)
  VTX_HOME_TIMEOUT   secondi dopo cui tornare alla home         (default 90)
  VTX_PAGE           numero di pagina in testata (Televideo)    (default 100)
  VTX_CORNER_MARGIN  colonne di margine negli angoli            (default 1)
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from vtx_font import normalize_text  # noqa: E402
from vtx_render import (  # noqa: E402
    THEMES, Screen, crt_effect, wrap_text, text_bitmap, image_to_subpixels,
)

# ---------------------------------------------------------------- config


def _env(name, default):
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _env_float(name, default):
    try:
        return float(_env(name, default))
    except ValueError:
        return float(default)


THEME_NAME = _env("VTX_THEME", "videotel").lower()
THEME = THEMES.get(THEME_NAME, THEMES["videotel"])
SERVICE_NAME = _env("VTX_SERVICE_NAME", "PAiTEL")
LOGO_TEXT = _env("VTX_LOGO_TEXT", "PAi")
LOGO_IMAGE = _env("VTX_LOGO_IMAGE", "")
LOGO_MONO = _env("VTX_LOGO_MONO", "0") == "1"
HOME_LINES = _env("VTX_HOME_LINES", "Tieni premuto il|tasto e parla").split("|")
FOOTER_TAG = _env("VTX_FOOTER", "pai.local")
BOOT_MODE = _env("VTX_BOOT", "full").lower()
DIAL = _env("VTX_DIAL", "165")
MODEM_SOUND = _env("VTX_MODEM_SOUND", "1") == "1"
AUDIO_DEVICE = _env("VTX_AUDIO_DEVICE", "")
BAUD = max(75.0, _env_float("VTX_BAUD", 1200))
CPS = BAUD / 10.0  # caratteri al secondo (8 bit + start/stop)
CRT = max(0.0, min(1.0, _env_float("VTX_CRT", 0.7)))
ROUNDING = _env("VTX_ROUNDING", "1") == "1"
IMAGE_MODE = _env("VTX_IMAGE_MODE", "mosaic").lower()
SYNC_SPEECH = _env("VTX_SYNC_SPEECH", "1") == "1"
HOME_TIMEOUT = _env_float("VTX_HOME_TIMEOUT", 90)
PAGE_NUMBER = _env("VTX_PAGE", "100")
# margine (in colonne) per testata e piè di pagina: il display ha gli angoli arrotondati
M = int(_env_float("VTX_CORNER_MARGIN", 1))

STATUS_LABELS = {
    "starting": "Avvio...",
    "idle": "Premi il tasto",
    "listening": "IN ASCOLTO",
    "detecting": "Rilevo la voce",
    "recognizing": "Trascrivo...",
    "thinking": "Elaboro...",
    "tool calling": "Consulto...",
    "answering": "Rispondo",
    "answering...": "Elaboro...",
    "error": "ERRORE",
    "camera": "Fotocamera",
    "music": "Musica",
    "confirm": "Confermi?",
    "queued": "In coda...",
    "success": "Fatto",
}

DEFAULT_HINT_PREFIXES = ("Long Press the button", "Waiting for message")
TOOL_TAG_RE = re.compile(r"(?<![A-Za-z0-9])[%％﹪]\s*[A-Za-z_][\w.-]*(?:\s+[0-9]+s)?")
PLACEHOLDER_RE = re.compile(r"\{tool:[A-Za-z0-9_-]+\}")
MARKDOWN_RE = re.compile(r"(\*\*|__|`+|^#+\s*)", re.MULTILINE)

# ---------------------------------------------------------------- stato


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.status = "starting"
        self.text = ""
        self.question = ""
        self.answer = ""
        self.battery = None
        self.network = None
        self.image_path = ""
        self.camera_mode = False
        self.sync_char_end = None
        self.last_activity = time.time()
        self.version = 0

    def clean(self, text):
        text = PLACEHOLDER_RE.sub("", text or "")
        text = TOOL_TAG_RE.sub("", text)
        text = MARKDOWN_RE.sub("", text)
        return text.strip()

    def update(self, msg):
        with self.lock:
            status = msg.get("status")
            text = msg.get("text")
            delta = msg.get("text_delta")
            if text is None and delta is not None:
                text = (self.text or "") + delta
            if status is not None:
                self.status = str(status)
            if text is not None:
                self.text = text
            st = self.status.lower()
            if status is not None and st in ("listening", "detecting"):
                self.question = ""
                self.answer = ""
                self.sync_char_end = None
            elif st == "recognizing" and text is not None:
                self.question = self.clean(text)
                self.answer = ""
                self.sync_char_end = None
            elif st not in ("idle", "starting", "camera", "listening", "detecting",
                            "recognizing") and text is not None:
                new_answer = self.clean(text)
                if not new_answer.startswith(self.answer[: max(0, len(self.answer) - 2)]):
                    self.sync_char_end = None
                self.answer = new_answer
            elif st == "idle" and text is not None and not self.is_default_hint(text):
                self.answer = self.clean(text)
            sync = msg.get("scroll_sync")
            if isinstance(sync, dict) and sync.get("char_end") is not None:
                try:
                    self.sync_char_end = int(sync["char_end"])
                except (TypeError, ValueError):
                    pass
            if msg.get("battery_level") is not None:
                self.battery = msg.get("battery_level")
            if msg.get("network_connected") is not None:
                self.network = bool(msg.get("network_connected"))
            if msg.get("image") is not None:
                self.image_path = msg.get("image") or ""
            self.last_activity = time.time()
            self.version += 1

    @staticmethod
    def is_default_hint(text):
        t = (text or "").strip()
        return (not t) or t.startswith(DEFAULT_HINT_PREFIXES)

    def snapshot(self):
        with self.lock:
            return {
                "status": self.status,
                "st": self.status.lower(),
                "text": self.text,
                "question": self.question,
                "answer": self.answer,
                "battery": self.battery,
                "network": self.network,
                "image_path": self.image_path,
                "sync_char_end": self.sync_char_end,
                "last_activity": self.last_activity,
                "camera_mode": self.camera_mode,
            }


# ---------------------------------------------------------------- pagine


class Pages:
    """Compone le pagine Videotex sulla griglia di caratteri."""

    def __init__(self, width=240, height=280):
        self.screen = Screen(width, height, rounding=ROUNDING)
        self.cols = self.screen.cols
        self.rows = self.screen.rows
        self.content_top = 2
        self.content_rows = self.rows - 4
        self._logo_cache = None
        self._image_cache = (None, None)

    # --- elementi comuni
    def header(self, s, connected, flash_on):
        t = THEME
        sc = self.screen
        if "header_band" in t:  # stile Televideo
            sc.put(M, 0, "P" + PAGE_NUMBER, t["fg"])
            sc.put(M + 5, 0, SERVICE_NAME[: self.cols - 11 - 2 * M], t["title"])
            sc.put_right(0, time.strftime("%H:%M"), t["title"], margin=M)
            sc.fill_row(1, t["header_band"])
            sc.put_center(1, " ASSISTENTE AI ", t["title"], t["header_band"])
        else:  # stile Videotel / Minitel
            sc.put_center(0, SERVICE_NAME, t["title"])
            indicator = "C" if connected else "F"
            if s["st"] == "listening" and not flash_on:
                indicator = " "
            sc.put_right(0, indicator, t["accent"], margin=M)
            sc.put(0, 1, "-" * self.cols, t["rule"])

    def footer(self, s, flash_on):
        t = THEME
        sc = self.screen
        sc.put(0, self.rows - 2, "-" * self.cols, t["rule"])
        label = STATUS_LABELS.get(s["st"], s["status"][: self.cols - 5])
        color = t["error"] if s["st"] == "error" else t["dim"]
        if s["st"] == "listening":
            color = t["user"]
            if not flash_on:
                label = ""
        right = ""
        rcol = t["dim"]
        if s["battery"] is not None:
            try:
                lvl = int(s["battery"])
                right = "%d%%" % lvl
                rcol = t["error"] if lvl <= 15 else t["dim"]
            except (TypeError, ValueError):
                right = ""
        elif FOOTER_TAG and s["st"] == "idle":
            right = FOOTER_TAG[:9]
        room = self.cols - 2 * M - (len(right) + 1 if right else 0)
        sc.put(M, self.rows - 1, label[:room], color)
        if right:
            sc.put_right(self.rows - 1, right, rcol, margin=M)

    # --- logo
    def logo_cells(self, max_cols, max_rows):
        """Restituisce una funzione che disegna il logo; calcolata una sola volta."""
        if self._logo_cache is not None:
            return self._logo_cache
        max_w, max_h = max_cols * 2, max_rows * 3
        if LOGO_IMAGE and os.path.exists(LOGO_IMAGE):
            if LOGO_MONO:
                bmp = image_to_subpixels(LOGO_IMAGE, max_w, max_h, mono=True)
                data = ("mono", bmp)
            else:
                rgb = image_to_subpixels(LOGO_IMAGE, max_w, max_h)
                data = ("color", rgb)
        else:
            # logo testuale con cornice, come nelle pagine Videotel
            scale = 1
            for s in (3, 2, 1):
                tb = text_bitmap(LOGO_TEXT, s)
                if tb.shape[1] + 2 * 3 <= max_w and tb.shape[0] + 2 * 2 <= max_h:
                    scale = s
                    break
            tb = text_bitmap(LOGO_TEXT, scale)
            if tb.shape[1] > max_w - 6:
                tb = tb[:, : max_w - 6]
            h, w = tb.shape
            pad_x, pad_y = 2, 1
            bmp = np.zeros((h + 2 * pad_y + 2, w + 2 * pad_x + 2), dtype=bool)
            bmp[0, :] = bmp[-1, :] = True
            bmp[:, 0] = bmp[:, -1] = True
            bmp[1 + pad_y:1 + pad_y + h, 1 + pad_x:1 + pad_x + w] = tb
            data = ("mono", bmp)
        self._logo_cache = data
        return data

    def draw_logo(self, top, max_rows):
        kind, data = self.logo_cells(self.cols, max_rows)
        t = THEME
        if kind == "mono":
            h, w = data.shape
            cols = (w + 1) // 2
            rows = (h + 2) // 3
            left = (self.cols - cols) // 2
            self.screen.put_bitmap(left, top + max(0, (max_rows - rows) // 2), data,
                                   t["logo"], separated=t.get("separated_logo", False))
        else:
            h, w, _ = data.shape
            cols = (w + 1) // 2
            rows = (h + 2) // 3
            left = (self.cols - cols) // 2
            self.screen.put_color_mosaic(left, top + max(0, (max_rows - rows) // 2), data,
                                         t["palette"])

    # --- pagine
    def home(self, s, flash_on, hint_extra=None):
        t = THEME
        sc = self.screen
        sc.clear(t["bg"], t["fg"])
        self.header(s, False, flash_on)
        logo_rows = self.content_rows - len(HOME_LINES) - 1
        self.draw_logo(self.content_top, logo_rows)
        row = self.content_top + logo_rows + 1
        for i, line in enumerate(HOME_LINES):
            sc.put_center(row + i, line, t["fg"])
        if hint_extra:
            sc.put_center(row + len(HOME_LINES), hint_extra, t["dim"])
        self.footer(s, flash_on)
        return sc

    def conversation(self, s, revealed, flash_on):
        """Pagina di dialogo. `revealed` = caratteri già "trasmessi"."""
        t = THEME
        sc = self.screen
        sc.clear(t["bg"], t["fg"])
        self.header(s, True, flash_on)
        lines = []  # (testo, colore)
        q = s["question"]
        if q:
            for ln in wrap_text("> " + q, self.cols):
                lines.append((ln, t["user"]))
            lines.append(("", t["fg"]))
        a = s["answer"]
        acolor = t["error"] if s["st"] == "error" else t["fg"]
        if a:
            for ln in wrap_text(a, self.cols):
                lines.append((ln, acolor))
        # rivela il testo carattere per carattere
        shown = []
        budget = revealed
        cursor = None
        for ln, col in lines:
            cost = len(ln) + 1
            if budget >= cost:
                shown.append((ln, col))
                budget -= cost
            else:
                shown.append((ln[: max(0, budget)], col))
                budget = -1
                break
        if s["st"] in ("listening", "detecting") and not q:
            shown = [("> ", t["user"])]
        visible = shown[-self.content_rows:]
        for i, (ln, col) in enumerate(visible):
            sc.put(0, self.content_top + i, ln, col)
        if visible:
            last_ln = visible[-1][0]
            cursor = (min(len(last_ln), self.cols - 1), self.content_top + len(visible) - 1)
        self.footer(s, flash_on)
        total = sum(len(ln) + 1 for ln, _ in lines)
        return sc, cursor, total

    def image_page(self, s, flash_on):
        t = THEME
        sc = self.screen
        sc.clear(t["bg"], t["fg"])
        self.header(s, True, flash_on)
        path = s["image_path"]
        if self._image_cache[0] != path:
            try:
                rgb = image_to_subpixels(path, self.cols * 2, self.content_rows * 3)
            except Exception as e:  # immagine non leggibile
                print(f"[Videotex] Immagine non leggibile {path}: {e}")
                rgb = None
            self._image_cache = (path, rgb)
        rgb = self._image_cache[1]
        if rgb is not None:
            h, w, _ = rgb.shape
            left = (self.cols - (w + 1) // 2) // 2
            sc.put_color_mosaic(left, self.content_top, rgb, t["palette"])
        self.footer(s, flash_on)
        return sc

    def boot_page(self, lines, connected=False):
        t = THEME
        sc = self.screen
        sc.clear(BLACKISH, t["fg"])
        for row, text, color in lines:
            sc.put(M, row, text, color)
        if connected:
            sc.put_right(0, "C", t["accent"], margin=M)
        else:
            sc.put_right(0, "F", t["dim"], margin=M)
        return sc


BLACKISH = (0, 0, 0)

# ---------------------------------------------------------------- suono del modem


def _find_audio_device():
    if AUDIO_DEVICE:
        return AUDIO_DEVICE
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                m = re.match(r"\s*\d+\s+\[(\S+)\s*\]", line)
                if m and re.search(r"whisplay|wm8960|es8389", line, re.I):
                    return "plughw:CARD=%s" % m.group(1)
    except OSError:
        pass
    return None


def modem_wav(path, dial):
    """Sintetizza il suono di un modem V.23 (DTMF + tono di risposta + FSK)."""
    sr = 16000
    parts = []

    def tone(freqs, dur, vol=0.3):
        tt = np.arange(int(sr * dur)) / sr
        s = sum(np.sin(2 * np.pi * f * tt) for f in freqs) / len(freqs)
        return (s * vol).astype(np.float32)

    def silence(dur):
        return np.zeros(int(sr * dur), dtype=np.float32)

    dtmf = {
        "1": (697, 1209), "2": (697, 1336), "3": (697, 1477),
        "4": (770, 1209), "5": (770, 1336), "6": (770, 1477),
        "7": (852, 1209), "8": (852, 1336), "9": (852, 1477),
        "*": (941, 1209), "0": (941, 1336), "#": (941, 1477),
    }
    parts.append(tone((350, 440), 0.6, 0.15))  # tono di linea
    parts.append(silence(0.15))
    for d in dial:
        if d in dtmf:
            parts.append(tone(dtmf[d], 0.12, 0.25))
            parts.append(silence(0.08))
    parts.append(silence(0.5))
    parts.append(tone((425,), 0.9, 0.15))     # squillo
    parts.append(silence(0.4))
    parts.append(tone((2100,), 1.0, 0.2))     # tono di risposta
    # FSK V.23: 1300/2100 Hz (1200 baud) + 390/450 Hz canale di ritorno (75 baud)
    rng = np.random.default_rng(165)
    n = int(sr * 1.4)
    bits = rng.integers(0, 2, size=n // (sr // 1200) + 1)
    f1 = np.repeat(np.where(bits, 1300, 2100), sr // 1200)[:n]
    phase1 = np.cumsum(2 * np.pi * f1 / sr)
    bits2 = rng.integers(0, 2, size=n // (sr // 75) + 1)
    f2 = np.repeat(np.where(bits2, 390, 450), sr // 75)[:n]
    phase2 = np.cumsum(2 * np.pi * f2 / sr)
    parts.append(((np.sin(phase1) * 0.16 + np.sin(phase2) * 0.08)).astype(np.float32))
    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    # tempi (in secondi) degli eventi, per sincronizzare lo schermo
    t_dial_end = 0.75 + len(dial) * 0.2
    t_answer = t_dial_end + 0.5 + 0.9 + 0.4
    t_connect = t_answer + 1.0 + 1.4
    return t_dial_end, t_answer, t_connect


def play_modem_sound(dial):
    path = os.path.join("/tmp", "vtx_modem.wav")
    timing = modem_wav(path, dial)
    if MODEM_SOUND:
        cmd = ["aplay", "-q"]
        dev = _find_audio_device()
        if dev:
            cmd += ["-D", dev]
        cmd.append(path)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"[Videotex] Impossibile riprodurre il suono del modem: {e}")
    return timing


# ---------------------------------------------------------------- output


def to_rgb565(img):
    arr = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((arr[:, :, 0] >> 3) << 11) | ((arr[:, :, 1] >> 2) << 5) | (arr[:, :, 2] >> 3)
    out = np.empty(v.shape + (2,), dtype=np.uint8)
    out[:, :, 0] = v >> 8
    out[:, :, 1] = v & 0xFF
    return out.tobytes()


class Renderer(threading.Thread):
    def __init__(self, whisplay, state):
        super().__init__(daemon=True)
        self.whisplay = whisplay
        self.state = state
        self.width = getattr(whisplay, "LCD_WIDTH", 240)
        self.height = getattr(whisplay, "LCD_HEIGHT", 280)
        self.pages = Pages(self.width, self.height)
        self.running = True
        self.event = threading.Event()
        self.last_frame = None
        # stato dell'animazione
        self.page_kind = None
        self.page_started = time.time()
        self.revealed = 0.0
        self.last_q = None
        self.last_a = ""
        self.last_tick = time.time()

    def wake(self):
        self.event.set()

    def show(self, img):
        if CRT > 0:
            img = crt_effect(img, CRT)
        data = to_rgb565(img)
        if data == self.last_frame:
            return
        self.last_frame = data
        self.whisplay.draw_image(0, 0, self.width, self.height, list(data))

    def paint_progressive(self, screen, elapsed, cursor=None):
        """Simula la ricezione della pagina a BAUD: le celle compaiono in ordine."""
        limit = int(elapsed * CPS)
        total = screen.rows * screen.cols
        if limit < total:
            k = 0
            for r in range(screen.rows):
                for c in range(screen.cols):
                    if k >= limit:
                        cell = screen.cells[r][c]
                        cell.ch, cell.mosaic, cell.bg = " ", None, screen.bg
                    k += 1
            cur = (limit % screen.cols, limit // screen.cols)
            return screen.render(cursor=cur, cursor_color=THEME["fg"]), True
        return screen.render(cursor=cursor, cursor_color=THEME["fg"]), False

    # --- sequenza di avvio
    def boot(self):
        if BOOT_MODE == "off":
            return
        if BOOT_MODE == "full":
            t = THEME
            p = self.pages
            try:
                t_dial, t_answer, t_connect = play_modem_sound(DIAL)
            except Exception as e:
                print(f"[Videotex] Errore suono modem: {e}")
                t_dial, t_answer, t_connect = 1.4, 3.2, 5.6
            start = time.time()
            script = [
                (0.0, 2, "ATDT " + DIAL, t["fg"]),
                (t_dial, 4, "Chiamata in corso", t["dim"]),
                (t_answer, 6, "Portante rilevata", t["dim"]),
                (t_connect, 8, "CONNESSO 1200/75", t["accent"]),
            ]
            end = t_connect + 0.8
            while self.running:
                el = time.time() - start
                if el > end:
                    break
                lines = []
                for t0, row, txt, col in script:
                    if el >= t0:
                        n = int((el - t0) * 20) if row == 2 else len(txt)
                        lines.append((row, txt[:n], col))
                connected = el >= t_connect
                sc = p.boot_page(lines, connected)
                blink = int(el * 3) % 2 == 0
                last_row = lines[-1][0] if lines else 2
                last_len = len(lines[-1][1]) if lines else 0
                self.show(sc.render(cursor=(last_len + M, last_row) if blink else None,
                                    cursor_color=t["fg"]))
                time.sleep(1 / 20)
        self.page_kind = None  # forza il ridisegno progressivo della home

    # --- ciclo principale
    def run(self):
        try:
            self.boot()
        except Exception as e:
            print(f"[Videotex] Errore durante l'avvio: {e}")
        while self.running:
            animating = self.render_once()
            if animating:
                time.sleep(1 / 25)
            else:
                self.event.wait(0.5)
                self.event.clear()

    def render_once(self):
        s = self.state.snapshot()
        if s["camera_mode"]:
            return False
        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now
        flash_on = int(now * 2) % 2 == 0
        st = s["st"]

        if s["image_path"]:
            kind = "image"
        elif st in ("idle", "starting") and (
                (not s["answer"] and not s["question"])
                or (HOME_TIMEOUT > 0 and now - s["last_activity"] > HOME_TIMEOUT)):
            kind = "home"
        else:
            kind = "conv"
        if kind != self.page_kind:
            self.page_kind = kind
            self.page_started = now
            self.revealed = 0.0
            self.last_q = None
        elapsed = now - self.page_started

        if kind == "image" and IMAGE_MODE == "photo":
            try:
                img = Image.open(s["image_path"]).convert("RGB")
                img = img.resize((self.width, self.height), Image.LANCZOS)
                self.show(img)
            except Exception as e:
                print(f"[Videotex] Immagine non leggibile: {e}")
            return False
        if kind == "image":
            sc = self.pages.image_page(s, flash_on)
            img, anim = self.paint_progressive(sc, elapsed)
            self.show(img)
            return anim
        if kind == "home":
            extra = None
            if "double click" in (s["text"] or ""):
                extra = "2 clic: foto"
            sc = self.pages.home(s, flash_on, extra)
            img, anim = self.paint_progressive(sc, elapsed)
            self.show(img)
            return anim or st == "listening"

        # pagina di conversazione: il testo viene "trasmesso" a BAUD
        q, a = s["question"], s["answer"]
        qlen = (sum(len(ln) + 1 for ln in wrap_text("> " + q, self.pages.cols)) + 1) if q else 0
        if q != self.last_q:
            self.revealed = 0.0
            self.last_q = q
            self.last_a = a
        elif not a.startswith(self.last_a[: max(0, len(self.last_a) - 2)]):
            # nuova risposta: ricomincia dalla fine della domanda
            self.revealed = min(self.revealed, float(qlen))
        self.last_a = a
        sc, cursor, total = self.pages.conversation(s, int(self.revealed), flash_on)
        target = total
        if (SYNC_SPEECH and st == "answering" and s["sync_char_end"] is not None):
            target = min(total, qlen + s["sync_char_end"] + 1)
        if self.revealed < target:
            self.revealed = min(float(target), self.revealed + max(dt, 0.0) * CPS)
            sc, cursor, total = self.pages.conversation(s, int(self.revealed), flash_on)
        typing = self.revealed < target
        blink = flash_on or typing
        img = sc.render(flash_on, cursor=cursor if blink else None, cursor_color=THEME["fg"])
        self.show(img)
        return typing or st == "listening"

    def stop(self):
        self.running = False
        self.event.set()


# ---------------------------------------------------------------- server socket


class Server:
    def __init__(self, whisplay, state, renderer):
        self.whisplay = whisplay
        self.state = state
        self.renderer = renderer
        self.clients = {}
        self.clients_lock = threading.Lock()
        self.camera_thread = None
        self.capture_path = ""

    def broadcast(self, message):
        data = json.dumps(message).encode("utf-8") + b"\n"
        with self.clients_lock:
            items = list(self.clients.items())
        for addr, sock in items:
            try:
                sock.sendall(data)
            except OSError as e:
                print(f"[Socket] Invio fallito verso {addr}: {e}")

    def on_press(self):
        self.broadcast({"event": "button_pressed"})

    def on_release(self):
        self.broadcast({"event": "button_released"})

    def on_exit_request(self):
        self.broadcast({"event": "app_exit_requested"})
        self.renderer.stop()
        if hasattr(self.whisplay, "prepare_exit"):
            try:
                self.whisplay.prepare_exit()
            except Exception:
                pass
        threading.Timer(0.5, lambda: os._exit(0)).start()

    def set_camera(self, enabled):
        if enabled:
            try:
                from camera import CameraThread  # modulo originale del chatbot
            except Exception as e:
                print(f"[Camera] Non disponibile: {e}")
                return
            with self.state.lock:
                self.state.camera_mode = True
            self.camera_thread = CameraThread(self.whisplay, self.capture_path)
            self.camera_thread.start()
        else:
            if self.camera_thread is not None:
                self.camera_thread.stop()
                self.camera_thread = None
            with self.state.lock:
                self.state.camera_mode = False
            self.renderer.last_frame = None
            self.renderer.page_kind = None
        self.renderer.wake()

    def handle(self, sock, addr):
        with self.clients_lock:
            self.clients[addr] = sock
        buf = ""
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        sock.send(b"ERROR: invalid JSON\n")
                        continue
                    try:
                        self.process(msg)
                        sock.send(b"OK\n")
                        if msg.get("response"):
                            sock.send(json.dumps({"response": msg["response"]}).encode() + b"\n")
                    except Exception as e:
                        print(f"[Socket] Errore: {e}")
                        sock.send(f"ERROR: {e}\n".encode())
        except OSError as e:
            print(f"[Socket] Connessione {addr}: {e}")
        finally:
            with self.clients_lock:
                self.clients.pop(addr, None)
            sock.close()

    def process(self, msg):
        rgb = msg.get("RGB")
        if rgb:
            col = parse_color(rgb)
            if col:
                try:
                    self.whisplay.set_rgb_fade(*col, duration_ms=500)
                except Exception:
                    pass
        if msg.get("brightness"):
            self.whisplay.set_backlight(msg["brightness"])
        if msg.get("capture_image_path") is not None:
            self.capture_path = msg["capture_image_path"]
        if msg.get("camera_mode") is not None:
            self.set_camera(bool(msg["camera_mode"]))
        if msg.get("camera_capture") and self.camera_thread is not None:
            self.camera_thread.capture()
            self.broadcast({"event": "camera_capture"})
        self.state.update(msg)
        self.renderer.wake()

    def serve(self, host="0.0.0.0", port=12345):
        self.whisplay.on_button_press(self.on_press)
        self.whisplay.on_button_release(self.on_release)
        if hasattr(self.whisplay, "on_exit_request"):
            self.whisplay.on_exit_request(self.on_exit_request)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(5)
        print(f"[Videotex] In ascolto su {host}:{port} (tema {THEME_NAME})")
        while True:
            client, addr = srv.accept()
            threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()


def parse_color(value):
    if isinstance(value, int) and 0 <= value <= 0xFFFF:
        return (((value >> 11) & 0x1F) * 255 // 31, ((value >> 5) & 0x3F) * 255 // 63,
                (value & 0x1F) * 255 // 31)
    if isinstance(value, str):
        h = value.lstrip("#")
        if len(h) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in h):
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def main():
    from whisplay_client import create_whisplay_hardware  # modulo originale del chatbot

    whisplay = create_whisplay_hardware()
    print(f"[LCD] {whisplay.LCD_WIDTH}x{whisplay.LCD_HEIGHT}")
    try:
        whisplay.set_backlight(100)
    except Exception:
        pass
    state = State()
    renderer = Renderer(whisplay, state)
    renderer.start()
    server = Server(whisplay, state, renderer)

    def cleanup(signum, frame):
        renderer.stop()
        try:
            whisplay.cleanup()
        finally:
            sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, cleanup)
    server.serve()


if __name__ == "__main__":
    main()
