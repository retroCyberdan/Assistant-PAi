#!/usr/bin/env python3
"""CYBERDECK: interfaccia del display Whisplay per whisplay-ai-chatbot.

Sostituisce `chatbot-ui.py`: parla lo stesso protocollo socket del chatbot
(TCP 12345, un messaggio JSON per riga) e disegna una dashboard dot-matrix
con animazioni che cambiano in base a cosa sta facendo l'assistente:

  pronto       -> Rocky, il Jack Russell a puntini, che aspetta: scodinzola,
                  si siede e ansima, fa un giro, schiaccia un pisolino...
  in ascolto   -> forma d'onda animata (mentre tieni premuto il tasto)
  elaborazione -> Rocky si dà da fare: scava, salta o si rotola (a caso)
  risposta     -> barre di puntini che "parlano" + testo scritto in tempo reale
  errore       -> particelle disperse

Le forme sono fatte degli stessi puntini, che scivolano da una forma all'altra:
ogni passaggio è fluido. All'accensione e allo spegnimento viene mostrata una
sequenza glitch con il logo e il terminale "SYSTEM STATUS".

Impostazioni (file .env del chatbot, modificabili dal pannello web):
  DECK_NAME            nome mostrato in testata e nel logo   (CYBERDECK ROCKY Pi)
  DECK_NAME_KANA       il nome in katakana, sotto il logo    (サイバーデッキ ロッキー パイ)
  DECK_PALETTE         verde | ambra | ghiaccio                (verde)
  DECK_LOGO_IMAGE      immagine da usare come logo (opzionale)
  DECK_HINT            testo della pagina iniziale
  DECK_BOOT            full | quick | off   animazione di accensione
  DECK_SHUTDOWN        full | quick | off   animazione di spegnimento
  DECK_BOOT_LINES      3 righe sotto "ONLINE." separate da |
  DECK_SHUTDOWN_LINES  3 righe sotto "OFFLINE." separate da |
  DECK_ENTER_TEXT      testo del prompt finale             ([ ENTER TERMINAL ])
  DECK_SOUND           1 = suoni di accensione/spegnimento   (1)
  DECK_AUDIO_DEVICE    dispositivo ALSA per i suoni          (automatico)
  DECK_CRT             0..1 effetto monitor CRT               (0.7)
  DECK_GLITCH          0..1 glitch casuali a riposo           (0.2)
  DECK_TEXT_SPEED      caratteri al secondo del testo         (60)
"""

import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import deck_gfx as gfx  # noqa: E402
from deck_dog import Dog  # noqa: E402
from deck_gfx import Canvas, Morph, W, H, mix, ease  # noqa: E402

# ------------------------------------------------------------------ impostazioni


def _env(name, default):
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _num(name, default, lo, hi):
    try:
        return max(lo, min(hi, float(_env(name, default))))
    except ValueError:
        return float(default)


NAME = _env("DECK_NAME", "CYBERDECK ROCKY Pi")
NAME_KANA = gfx.prep(_env("DECK_NAME_KANA", "サイバーデッキ ロッキー パイ"))  # scarta i caratteri non disegnati
VERSION = "v1.0"
PAL = gfx.palette(_env("DECK_PALETTE", "verde"))
LOGO_IMAGE = _env("DECK_LOGO_IMAGE", "")
HINT = _env("DECK_HINT", "Tieni premuto il tasto e parla")
BOOT = _env("DECK_BOOT", "full").lower()
SHUTDOWN = _env("DECK_SHUTDOWN", "full").lower()
BOOT_LINES = _env("DECK_BOOT_LINES", "The Simulation has been mapped.|The Archives are open.|"
                                     "Observer protocol initiated.").split("|")[:3]
SHUTDOWN_LINES = _env("DECK_SHUTDOWN_LINES", "The Simulation has been archived.|The Archives are sealed.|"
                                             "Observer protocol terminated.").split("|")[:3]
ENTER_TEXT = _env("DECK_ENTER_TEXT", "[ ENTER TERMINAL ]")
SOUND = _env("DECK_SOUND", "1") == "1"
AUDIO_DEVICE = _env("DECK_AUDIO_DEVICE", "")
CRT = _num("DECK_CRT", 0.7, 0, 1)
GLITCH = _num("DECK_GLITCH", 0.2, 0, 1)
CPS = _num("DECK_TEXT_SPEED", 60, 5, 1000)
SYNC_SPEECH = _env("DECK_SYNC_SPEECH", "1") == "1"
HOME_TIMEOUT = _num("DECK_HOME_TIMEOUT", 90, 0, 86400)

# ------------------------------------------------------------------ layout

CARD_X, CARD_W = 4, 232
TOP = 22                 # inizio della card "agente"
BOTTOM = 276             # fine della card "terminale"
SPLIT_BIG, SPLIT_COMPACT = 202, 112
LINE_H = 18
TEXT_COLS = 21           # caratteri per riga nel font a tratto sottile

STATES = {
    # stato del chatbot: (titolo, katakana, forma, card agente grande?, cosa fa Rocky)
    "starting": ("BOOTING", "キドウ", "dog", True, "sit"),
    "idle": ("READY", "レディ", "dog", True, "idle"),
    "listening": ("LISTENING", "リスニング", "wave", True, None),
    "detecting": ("LISTENING", "リスニング", "wave", True, None),
    "recognizing": ("DECODING...", "デコード", "dog", True, "busy"),
    "answering...": ("THINKING...", "シンキング", "dog", True, "busy"),
    "thinking": ("THINKING...", "シンキング", "dog", True, "busy"),
    "tool calling": ("TOOLS...", "ツール", "dog", True, "busy"),
    "queued": ("QUEUED...", "タイキ", "dog", True, "busy"),
    "answering": ("SPEAKING", "スピーキング", "spectrum", False, None),
    "music": ("MUSIC", "ミュージック", "spectrum", True, None),
    "confirm": ("CONFIRM?", "カクニン", "dog", False, "sit"),
    "error": ("ERROR", "エラー", "scatter", False, None),
    "camera": ("CAMERA", "カメラ", "dog", True, "sit"),
}
LABEL_KANA = {"AGENT STATUS": "ジョウタイ", "INPUT": "インプット", "OUTPUT": "アウトプット",
              "TERMINAL": "ターミナル", "ERROR": "エラー", "VISION": "ビジョン"}

DEFAULT_HINT_PREFIXES = ("Long Press the button", "Waiting for message")
TOOL_TAG_RE = re.compile(r"(?<![A-Za-z0-9])[%％﹪]\s*[A-Za-z_][\w.-]*(?:\s+[0-9]+s)?")
PLACEHOLDER_RE = re.compile(r"\{tool:[A-Za-z0-9_-]+\}")
MARKDOWN_RE = re.compile(r"(\*\*|__|`+|^#+\s*)", re.MULTILINE)


def clean_text(text):
    text = PLACEHOLDER_RE.sub("", text or "")
    text = TOOL_TAG_RE.sub("", text)
    return MARKDOWN_RE.sub("", text).strip()


# ------------------------------------------------------------------ stato


class State:
    """Ultimo stato ricevuto dal chatbot (aggiornato dal thread del socket)."""

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

    @staticmethod
    def is_default_hint(text):
        t = (text or "").strip()
        return (not t) or t.startswith(DEFAULT_HINT_PREFIXES)

    def update(self, msg):
        with self.lock:
            status, text, delta = msg.get("status"), msg.get("text"), msg.get("text_delta")
            if text is None and delta is not None:
                text = (self.text or "") + delta
            if status is not None:
                self.status = str(status)
            if text is not None:
                self.text = text
            st = self.status.lower()
            if status is not None and st in ("listening", "detecting"):
                self.question, self.answer, self.sync_char_end = "", "", None
            elif st == "recognizing" and text is not None:
                self.question, self.answer, self.sync_char_end = clean_text(text), "", None
            elif st not in ("idle", "starting", "camera", "listening", "detecting", "recognizing") \
                    and text is not None:
                new = clean_text(text)
                if not new.startswith(self.answer[: max(0, len(self.answer) - 2)]):
                    self.sync_char_end = None
                self.answer = new
            elif st == "idle" and text is not None and not self.is_default_hint(text):
                self.answer = clean_text(text)
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

    def snapshot(self):
        with self.lock:
            return {k: getattr(self, k) for k in (
                "status", "text", "question", "answer", "battery", "network", "image_path",
                "camera_mode", "sync_char_end", "last_activity")} | {"st": self.status.lower()}


# ------------------------------------------------------------------ sistema e suoni


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def uptime_text():
    try:
        with open("/proc/uptime") as f:
            sec = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return "--"
    h, m = sec // 3600, (sec % 3600) // 60
    return "%dH%02d" % (h, m) if h else "%dM" % m


def _audio_device():
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


def _synth(events, total, sr=16000):
    """Crea un suono a partire da eventi (inizio, tipo, durata, parametri)."""
    out = np.zeros(int(sr * total), dtype=np.float32)
    rng = np.random.default_rng(1)
    for t0, kind, dur, a, b in events:
        n = int(sr * dur)
        t = np.arange(n) / sr
        if kind == "noise":
            x = rng.uniform(-1, 1, n)
            step = int(a)
            x = np.repeat(x[::step], step)[:n]
            x *= b
        elif kind == "sweep":
            f = a + (b - a) * (t / dur)
            x = np.sign(np.sin(2 * np.pi * np.cumsum(f) / sr)) * 0.08 + np.sin(2 * np.pi * np.cumsum(f) / sr) * 0.12
        elif kind == "beep":
            x = np.sign(np.sin(2 * np.pi * a * t)) * b
        else:
            continue
        env = np.minimum(1, np.minimum(t / 0.005, (dur - t) / 0.02))
        i0 = int(sr * t0)
        seg = out[i0:i0 + n]
        seg += (x * env)[:len(seg)]
    return out


def play_sound(kind):
    if not SOUND:
        return
    if kind == "boot":
        ev = [(0.0, "noise", 0.12, 9, 0.25), (0.2, "noise", 0.08, 23, 0.2), (0.5, "sweep", 0.7, 90, 900, ),
              (2.2, "noise", 0.1, 13, 0.25), (2.45, "noise", 0.15, 5, 0.2)]
        ev = [e if len(e) == 5 else e + (0,) for e in ev]
        ev += [(2.9 + i * 0.12, "beep", 0.025, 2400 + (i % 3) * 300, 0.05) for i in range(14)]
        ev += [(5.0, "beep", 0.09, 1568, 0.12), (5.1, "beep", 0.16, 2093, 0.12)]
        total = 6.0
    else:
        ev = [(0.0, "noise", 0.15, 7, 0.25)]
        ev += [(0.35 + i * 0.12, "beep", 0.025, 2000 - (i % 3) * 300, 0.05) for i in range(10)]
        ev += [(2.2, "beep", 0.12, 1568, 0.1), (2.35, "beep", 0.2, 1046, 0.1),
               (4.5, "noise", 0.12, 11, 0.25), (6.2, "sweep", 0.6, 700, 60), (6.7, "noise", 0.08, 3, 0.2)]
        total = 7.5
    audio = _synth(ev, total)
    path = os.path.join("/tmp", "cyberdeck-%s.wav" % kind)
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        cmd = ["aplay", "-q"]
        dev = _audio_device()
        if dev:
            cmd += ["-D", dev]
        subprocess.Popen(cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"[Cyberdeck] Suono non riprodotto: {e}")


# ------------------------------------------------------------------ renderer


class Renderer(threading.Thread):
    def __init__(self, whisplay, state):
        super().__init__(daemon=True)
        self.whisplay = whisplay
        self.state = state
        self.p = PAL
        self.rng = np.random.default_rng()
        self.running = True
        self.event = threading.Event()
        self.shutdown_requested = threading.Event()
        self.done = threading.Event()
        self.last_frame = None
        self.last_arr = None
        # animazione
        self.t_start = time.time()
        self.last_tick = time.time()
        self.morph = Morph("dog")
        self.dog = Dog(self.rng)
        self.kana = "レディ"
        self.split = float(SPLIT_BIG)
        self.title = "READY"
        self.title_t0 = -10.0
        self.page = "dash"
        self.page_t0 = 0.0
        self.intro_t0 = -10.0
        self.qrev = 0.0
        self.arev = 0.0
        self.last_q = None
        self.last_a = ""
        self.turns = 0
        self.glitch_until = 0.0
        self.glitch_amount = 0.0
        self.next_glitch = time.time() + 8
        self._ip = (0.0, "")
        self._img = (None, None)
        self._logo = None

    # -------------------------------------------------------------- output
    def wake(self):
        self.event.set()

    def show(self, arr, amount=0.0):
        if amount > 0:
            arr = gfx.glitch(arr, amount, self.rng, self.p)
        self.last_arr = arr
        data = gfx.to_rgb565(gfx.crt(arr, CRT))
        if data == self.last_frame:
            return
        self.last_frame = data
        self.whisplay.draw_image(0, 0, W, H, list(data))

    def ip(self):
        if time.time() - self._ip[0] > 30:
            self._ip = (time.time(), local_ip())
        return self._ip[1]

    # -------------------------------------------------------------- elementi comuni
    def header(self, cv, s, now):
        p = self.p
        cv.text(14, 7, gfx.prep(NAME)[:20], p["hi"], "s")
        x = 14 + gfx.text_width(gfx.prep(NAME)[:20], "s") + 8
        online = s["network"] is not False
        if s["st"] in ("listening", "detecting"):
            cv.disc(x + 2.5, 11, 2.5, p["acc"] if int(now * 3) % 2 == 0 else p["dim"])
            cv.text(x + 8, 7, "REC", p["acc"], "s")
        else:
            cv.disc(x + 2.5, 11, 2.5, p["acc"] if online else p["err"])
        if s["battery"] is not None:
            try:
                lvl = int(s["battery"])
                cv.text_right(204, 7, "%d%%" % lvl, p["mid"] if lvl > 15 else p["err"], "s")
                cv.battery(226, 7, lvl, p["mid"], p["err"])
            except (TypeError, ValueError):
                pass

    def card_label(self, cv, x, y, num, label):
        """Etichetta di una card ("01  AGENT STATUS") con la traduzione in katakana accanto."""
        p = self.p
        txt = "%s  %s" % (num, label)
        w = cv.text(x, y, txt, p["hi"], "s")
        kana = LABEL_KANA.get(label)
        if kana:
            cv.text(x + w + 6, y, kana, p["dim"], "s")

    def logo(self, cv, y_center, color_main=None, color_sub=None):
        """Logo: il nome in grandi puntini (o l'immagine caricata), con katakana e versione."""
        p = self.p
        if gfx.file_exists(LOGO_IMAGE):
            if self._logo is None:
                try:
                    self._logo = gfx.dot_image(LOGO_IMAGE, 180, 138, p, pitch=3, dot=2, fit="contain")
                except Exception as e:
                    print(f"[Cyberdeck] Logo non leggibile: {e}")
                    self._logo = False
            if self._logo is not False:
                cv.blit(self._logo, (W - 180) // 2, y_center - 100)
                cv.text_center(y_center + 46, gfx.prep(NAME)[:30], color_main or p["hi"], "s")
                cv.text_center(y_center + 60, NAME_KANA, p["fg"], "s")
                cv.text_center(y_center + 74, VERSION, p["dim"], "s")
                return
        words = gfx.prep(NAME, True).split()
        main = words[0] if words else "CYBERDECK"
        sub = gfx.prep(" ".join(NAME.split()[1:]))
        mode = "D" if gfx.text_width(main, "D") <= 220 else ("d" if gfx.text_width(main, "d") <= 220 else "s")
        _cw, chh = gfx.cell_size(mode)
        x = (W - gfx.text_width(main, mode)) // 2
        top = y_center - chh - 6
        cv.text(x, top, main, color_main or p["hi"], mode)
        y = top + chh + 2
        if sub:
            # il resto del nome ("ROCKY Pi") allineato a destra sotto, nel colore accento
            sm = mode if gfx.text_width(sub, mode) <= 220 else "d"
            cv.text(x + gfx.text_width(main, mode) - gfx.text_width(sub, sm), y, sub, color_sub or p["acc"], sm)
            y += gfx.cell_size(sm)[1] + 4
        cv.text_center(y + 2, NAME_KANA, p["fg"], "s")
        cv.text_center(y + 16, VERSION + "  //  AI TERMINAL", p["dim"], "s")

    # -------------------------------------------------------------- dashboard
    def target_for(self, s, now):
        """Titolo, katakana, forma, card grande?, comportamento di Rocky per lo stato attuale."""
        st = s["st"]
        if st == "idle" and (s["answer"] or s["question"]) and not (
                HOME_TIMEOUT > 0 and now - s["last_activity"] > HOME_TIMEOUT):
            return "READY", "レディ", "dog", False, "idle"
        if st == "answering" and not s["answer"]:
            return STATES["thinking"]
        return STATES.get(st, (gfx.prep(s["status"], True)[:12] or "READY", "", "dog", True, "busy"))

    def compose_dash(self, s, now, dt):
        p = self.p
        title, kana, shape, big, dog_mode = self.target_for(s, now)
        if title != self.title:
            self.title, self.kana, self.title_t0 = title, kana, now
        self.morph.set(shape, now)
        self.dog.set_mode(dog_mode if shape == "dog" else "hidden", now)
        target = SPLIT_BIG if big else SPLIT_COMPACT
        self.split += (target - self.split) * (1 - math.exp(-dt * 6))
        split = int(round(self.split))

        cv = Canvas(p)
        self.header(cv, s, now)

        # ---- card 01: stato dell'agente
        cv.card(CARD_X, TOP, CARD_W, split - TOP)
        self.card_label(cv, 16, TOP + 9, "01", "AGENT STATUS")
        st = s["st"]
        if st in ("listening", "detecting"):
            if int(now * 3) % 2 == 0:
                cv.disc(199.5, TOP + 13, 2.5, p["acc"])
            cv.text(205, TOP + 9, "REC", p["acc"], "s")
        elif st == "answering":
            cv.text_right(224, TOP + 9, "LIVE", p["acc"], "s")
        k = (now - self.title_t0) / 0.45
        shown = gfx.scramble(self.title, k, int(now * 20))
        cv.text(16, TOP + 22, shown, p["hi"] if k >= 1 else p["fg"], "d")
        if self.kana:  # traduzione in katakana sotto il titolo, appare dopo la decodifica
            kk = max(0.0, min(1.0, (now - self.title_t0 - 0.3) / 0.3))
            cv.text(16, TOP + 43, self.kana, mix(p["card"], p["dim"], kk), "s")
        stats_a = max(0.0, min(1.0, (split - 145) / 40.0))
        vis_top = TOP + 56
        vis_bot = split - 8 - int(36 * stats_a)
        if vis_bot - vis_top > 8:
            box = (16, vis_top, 208, vis_bot - vis_top)
            dog_w = self.morph.weight(now, "dog")
            if dog_w > 0.02 and box[3] >= 40:  # il "pavimento" su cui sta Rocky
                gy = int(Dog.anchor(box)[1] + Dog.pitch(box))
                cv.hdots(20, gy, 200, mix(p["card"], p["faint"], dog_w), 3)
            wave_w = self.morph.weight(now, "wave")
            if wave_w > 0.02:  # linea di base puntinata dell'onda, come nel riferimento
                cv.hdots(18, (vis_top + vis_bot) // 2, 204, mix(p["card"], p["faint"], wave_w), 3)
            pos, col = self.morph.points(now, box, p, dog={"dog": self.dog})
            Morph.draw(cv, pos, col, 2 if Dog.pitch(box) >= 2.5 else 1)
            if dog_w > 0.98:
                self.dog.draw_extras(cv, box, p)
        if stats_a > 0.02:
            y = split - 40
            lab, val = mix(p["card"], p["dim"], stats_a), mix(p["card"], p["fg"], stats_a)
            batt = "--" if s["battery"] is None else "%s%%" % s["battery"]
            for i, (l, v) in enumerate((("BATTERY", batt), ("UPTIME", uptime_text()),
                                        ("TURNS", str(self.turns)))):
                x = 16 + i * 72
                cv.text(x, y, l, lab, "s")
                cv.text(x, y + 11, v[:5], val, "d")
                if i:
                    cv.vdots(x - 8, y + 2, 26, mix(p["card"], p["edge"], stats_a), 2)

        # ---- card 02: terminale (domanda / risposta)
        top2 = split + 4
        cv.card(CARD_X, top2, CARD_W, BOTTOM - top2)
        label = {"listening": "INPUT", "detecting": "INPUT", "recognizing": "INPUT"}.get(st, "OUTPUT")
        if not s["question"] and not s["answer"] and st not in ("listening", "detecting"):
            label = "TERMINAL"
        if st == "error":
            label = "ERROR"
        self.card_label(cv, 16, top2 + 9, "02", label)
        cv.text_right(224, top2 + 9, time.strftime("%H:%M"), p["dim"], "s")
        lines, cursor_ok = self.terminal_lines(s, now, dt)
        nlines = max(1, (BOTTOM - 8 - (top2 + 24)) // LINE_H)
        vis = lines[-nlines:]
        for i, (txt, col) in enumerate(vis):
            cv.text(16, top2 + 24 + i * LINE_H, txt, col, "t")
        if cursor_ok and int(now * 2.5) % 2 == 0:
            last = vis[-1][0] if vis else ""
            cx = 16 + min(len(last), TEXT_COLS) * 10
            cy = top2 + 24 + (max(1, len(vis)) - 1) * LINE_H
            cv.rect(cx, cy + 2, 7, 13, p["acc"])

        # glitch casuali a riposo
        amount = 0.0
        if GLITCH > 0 and st == "idle":
            if now >= self.next_glitch:
                self.glitch_until = now + float(self.rng.uniform(0.08, 0.25))
                self.glitch_amount = float(self.rng.uniform(0.15, 0.45)) * GLITCH
                self.next_glitch = now + float(self.rng.uniform(6, 16)) / max(GLITCH, 0.1)
            if now < self.glitch_until:
                amount = self.glitch_amount
        anim = True  # la dashboard è sempre animata (respiro, rotazione, onda...)
        fast = True  # Rocky, l'onda e le barre sono sempre in movimento
        return cv.a, amount, anim, fast

    def terminal_lines(self, s, now, dt):
        """Righe della card terminale, con il testo "trasmesso" carattere per carattere."""
        p = self.p
        st = s["st"]
        q, a = s["question"], s["answer"]
        if q != self.last_q:
            self.last_q, self.qrev = q, 0.0
            self.arev = 0.0
        if a and not self.last_a:
            self.turns += 1
        if not a.startswith(self.last_a[: max(0, len(self.last_a) - 2)]):
            self.arev = 0.0
        self.last_a = a
        step = max(dt, 0.0) * CPS
        if self.qrev < len(q):
            self.qrev = min(len(q), self.qrev + step * 2)
        elif a:
            target = len(a)
            if SYNC_SPEECH and st == "answering" and s["sync_char_end"] is not None:
                target = min(len(a), s["sync_char_end"] + 1)
            if self.arev < target:
                self.arev = min(float(target), self.arev + step)
        lines = []
        if st in ("listening", "detecting"):
            return [("> ", p["fg"])], True
        if not q and not a:
            return [(ln, p["fg"]) for ln in gfx.wrap("> " + HINT, TEXT_COLS)], True
        if q:
            ql = gfx.wrap("> " + q[: int(self.qrev)], TEXT_COLS)
            if a:  # durante la risposta la domanda si riduce a una riga
                one = "> " + q
                ql = [one if len(one) <= TEXT_COLS else one[: TEXT_COLS - 3] + "..."]
            lines += [(ln, p["dim"] if a else p["fg"]) for ln in ql]
        if a:
            col = p["err"] if st == "error" else p["hi"]
            lines += [(ln, col) for ln in gfx.wrap(a[: int(self.arev)], TEXT_COLS)]
        return lines, True

    def compose_image(self, s, now):
        p = self.p
        cv = Canvas(p)
        self.header(cv, s, now)
        cv.card(CARD_X, TOP, CARD_W, BOTTOM - TOP)
        self.card_label(cv, 16, TOP + 9, "03", "VISION")
        if int(now * 2) % 2 == 0:
            cv.disc(199.5, TOP + 13, 2.5, p["acc"])
        cv.text(205, TOP + 9, "REC", p["acc"], "s")
        path = s["image_path"]
        if self._img[0] != path:
            try:
                img = gfx.dot_image(path, 204, 204, p, pitch=3, dot=2)
            except Exception as e:
                print(f"[Cyberdeck] Immagine non leggibile {path}: {e}")
                img = None
            self._img = (path, img)
        img = self._img[1]
        box = (18, TOP + 26, 204, 204)
        if img is not None:
            rows = int(min(1.0, (now - self.page_t0) / 1.2) * img.shape[0])
            cv.blit(img[:rows], box[0], box[1])
            if rows < img.shape[0]:
                cv.rect(box[0], box[1] + rows, 204, 1, p["hi"])
        cv.brackets(box[0] - 4, box[1] - 4, 212, 212, p["fg"], 12)
        cv.text(16, BOTTOM - 16, "RECONSTRUCTION", p["dim"], "s")
        cv.text_right(224, BOTTOM - 16, "100%", p["fg"], "s")
        return cv.a

    def render_once(self):
        s = self.state.snapshot()
        if s["camera_mode"]:
            return False
        now = time.time()
        dt = min(0.25, now - self.last_tick)
        self.last_tick = now
        page = "image" if s["image_path"] else "dash"
        if page != self.page:
            self.page, self.page_t0 = page, now
            self.glitch_until = now + 0.3
            self.glitch_amount = 0.6
        if page == "image":
            arr, fast = self.compose_image(s, now), True
            amount = self.glitch_amount if now < self.glitch_until else 0.0
        else:
            arr, amount, _anim, fast = self.compose_dash(s, now, dt)
            if now < self.glitch_until and self.glitch_amount > amount:
                amount = self.glitch_amount
        # accensione della dashboard: rivelazione dall'alto con una riga luminosa
        k = (now - self.intro_t0) / 0.6
        if 0 <= k < 1:
            y = int(ease(k) * H)
            arr = arr.copy()
            arr[y:] = self.p["bg"]
            arr[max(0, y - 1):y + 1] = self.p["hi"]
            fast = True
        self.show(arr, amount)
        return fast

    # -------------------------------------------------------------- sequenze
    def _status_block(self, cv, el, title, word, kana, lines, prompt, t_title=0.0):
        """Blocco "SYSTEM STATUS" (come nel monitor di riferimento). el = secondi dall'inizio."""
        p = self.p
        y0 = 124
        if el >= t_title:
            n = int((el - t_title) * 36)
            cv.disc(19, y0 + 10, 4.5, p["acc"])
            cv.text(30, y0, title[:n], p["hi"], "b")
        t_word = t_title + 0.45
        if el >= t_word:
            on = (el - t_word) > 0.3 or int((el - t_word) * 20) % 2 == 0
            if on:
                cv.text(14, y0 + 22, word, p["fg"], "B")
            if el >= t_word + 0.3:
                n = int((el - t_word - 0.3) * 40)
                cv.text(16, y0 + 64, kana[:n], p["mid"], "s")
        t_lines = t_word + 0.35
        for i, ln in enumerate(lines):
            ti = t_lines + i * 0.35
            if el >= ti:
                n = int((el - ti) * 90)
                cv.text(16, y0 + 80 + i * 12, ln[:n][:36], p["fg"], "s")
        t_prompt = t_lines + len(lines) * 0.35 + 0.2
        if el >= t_prompt:
            cv.text(16, y0 + 122, prompt, p["hi"], "t")
            if int((el - t_prompt) * 2.5) % 2 == 0:
                cv.rect(16 + gfx.text_width(prompt, "t") + 4, y0 + 123, 8, 15, p["acc"])
        return t_prompt

    def _log(self, cv, el, lines, t0, y_max=118, step=0.12):
        """Righe di codice che scorrono (dall'alto, il testo esce oltre il bordo come sul CRT)."""
        p = self.p
        n = int((el - t0) / step) + 1 if el >= t0 else 0
        n = min(n, len(lines))
        vis_rows = (y_max - 8) // 11
        shown = lines[max(0, n - vis_rows):n]
        for i, ln in enumerate(shown):
            col = p["mid"] if i < len(shown) - 1 else p["fg"]
            cv.text(14, 8 + i * 11, ln[:40], col, "s")
        return n >= len(lines)

    def _logo_frame(self, el, t_in, t_hold, t_out):
        """Logo con glitch in entrata e in uscita. Restituisce (array, intensità glitch)."""
        cv = Canvas(self.p)
        if el < t_in:
            cv.a = gfx.static_noise(self.rng, self.p, 0.45 * (1 - el / t_in) + 0.05)
            return cv.a, 0.9
        if el < t_out + 0.5:
            self.logo(cv, 128)
        if el < t_hold:
            k = (el - t_in) / (t_hold - t_in)
            amount = max(0.0, 1 - k * 1.6)
            if self.rng.random() < 0.15 * (1 - k):
                cv.a[:, :] = self.p["bg"]
            return cv.a, amount
        if el < t_out:
            return cv.a, 0.05 if self.rng.random() < 0.08 else 0.0
        k = (el - t_out) / 0.5
        if self.rng.random() < k * 0.5:
            cv.a[:, :] = self.p["bg"]
        return cv.a, min(1.0, 0.2 + k * 1.2)

    def boot_lines(self):
        s = self.state.snapshot()
        ip = self.ip()
        batt = "--" if s["battery"] is None else "%s%%" % s["battery"]
        return [
            "%s %s // boot" % (gfx.prep(NAME), VERSION),
            "Initializing terminal core...",
            "Collecting boot services...",
            "Mounting root:/deck/sys ... ok",
            "Loading kernel %s ... ok" % os.uname().release,
            "Selecting audio codec: whisplay ... ok",
            "Starting display ST7789 240x280 ... ok",
            "Connecting network: %s" % (ip or "OFFLINE"),
            "Connecting power: PiSugar %s" % batt,
            "Linking AI core: %s" % _env("LLM_SERVER", "--").upper(),
            "Linking voice: ASR %s / TTS %s" % (_env("ASR_SERVER", "--").upper(), _env("TTS_SERVER", "--").upper()),
            "Syncing clock: %s" % time.strftime("%Y-%m-%d %H:%M"),
            "Waking up Rocky ... woof!",
            "Evaluating response...",
            "Connecting System Status: online",
        ]

    def _play(self, duration, frame_fn, fps=30):
        start = time.time()
        while True:
            el = time.time() - start
            if el > duration:
                break
            arr, amount = frame_fn(el)
            self.show(arr, amount)
            time.sleep(max(0.0, 1 / fps - (time.time() - start - el)))

    def boot(self):
        if BOOT == "off":
            self.intro_t0 = time.time()
            return
        if BOOT == "full":
            play_sound("boot")
        logo_end = 2.8 if BOOT == "full" else 0.0
        lines = self.boot_lines() if BOOT == "full" else []
        t_log = logo_end + 0.1
        t_status = t_log + len(lines) * 0.12 + 0.2 if lines else 0.2
        t_prompt_est = t_status + 0.45 + 0.35 + 3 * 0.35 + 0.2
        t_end = t_prompt_est + 1.5

        def frame(el):
            if el < logo_end:
                return self._logo_frame(el, 0.5, 1.6, 2.3)
            cv = Canvas(self.p)
            if lines:
                self._log(cv, el, lines, t_log)
            if el >= t_status:
                self._status_block(cv, el - t_status, "SYSTEM STATUS:", "ONLINE.",
                                   "システム ステータス: オンライン", BOOT_LINES, ENTER_TEXT)
            amount = 0.0
            if el > t_end - 0.3:
                amount = (el - (t_end - 0.3)) / 0.3
            return cv.a, amount

        self._play(t_end, frame)
        self.intro_t0 = time.time()

    def shutdown_sequence(self):
        if SHUTDOWN == "off":
            return
        last = self.last_arr if self.last_arr is not None else Canvas(self.p).a
        if SHUTDOWN == "quick":
            self._play(0.6, lambda el: (gfx.crt_collapse(last, el / 0.6, self.p), 0.0))
            return
        play_sound("shutdown")
        lines = ["Closing active session...", "Saving memory buffers ... ok", "Unlinking AI core ...",
                 "Stopping voice services ... ok", "Disconnecting network ...", "Releasing audio codec ... ok",
                 "Unmounting root:/deck/sys ... ok", "Archiving the Simulation ...", "System halt requested."]
        t_log = 0.35
        t_status = t_log + len(lines) * 0.12 + 0.2
        t_logo = t_status + 0.45 + 0.35 + 3 * 0.35 + 0.2 + 1.0
        t_end = t_logo + 2.8

        def frame(el):
            if el < t_log:
                return last, el / t_log
            if el < t_logo:
                cv = Canvas(self.p)
                self._log(cv, el, lines, t_log)
                if el >= t_status:
                    self._status_block(cv, el - t_status, "SYSTEM STATUS:", "OFFLINE.",
                                       "システム ステータス: オフライン", SHUTDOWN_LINES, "[ TERMINAL CLOSED ]")
                amount = (el - (t_logo - 0.25)) / 0.25 if el > t_logo - 0.25 else 0.0
                return cv.a, amount
            le = el - t_logo
            if le < 2.3:  # logo: glitch in entrata, pausa, glitch in uscita
                return self._logo_frame(le + 0.5, 0.5, 1.6, 2.3)
            blank = Canvas(self.p).a  # tubo catodico che si spegne: riga, poi punto
            return gfx.crt_collapse(blank, 0.6 + (le - 2.3) / 0.5 * 0.4, self.p), 0.0

        self._play(t_end, frame)
        black = Canvas(self.p)
        black.a[:, :] = 0
        self.show(black.a)

    # -------------------------------------------------------------- ciclo
    def run(self):
        try:
            self.boot()
        except Exception as e:
            print(f"[Cyberdeck] Errore durante l'accensione: {e}")
            self.intro_t0 = time.time()
        while self.running and not self.shutdown_requested.is_set():
            t_frame = time.time()
            try:
                fast = self.render_once()
            except Exception as e:
                print(f"[Cyberdeck] Errore di disegno: {e}")
                fast = False
            # ritmo costante: ~30 fotogrammi al secondo durante le animazioni, 12 a riposo
            period = 1 / 30 if fast else 1 / 12
            self.event.wait(max(0.0, period - (time.time() - t_frame)))
            self.event.clear()
        if self.shutdown_requested.is_set():
            try:
                self.shutdown_sequence()
            except Exception as e:
                print(f"[Cyberdeck] Errore durante lo spegnimento: {e}")
        self.done.set()

    def stop(self):
        self.running = False
        self.event.set()

    def request_shutdown(self, timeout=15):
        """Mostra l'animazione di spegnimento e attende che finisca."""
        self.shutdown_requested.set()
        self.event.set()
        self.done.wait(timeout)


# ------------------------------------------------------------------ server socket


class Server:
    def __init__(self, whisplay, state, renderer):
        self.whisplay = whisplay
        self.state = state
        self.renderer = renderer
        self.clients = {}
        self.lock = threading.Lock()
        self.camera_thread = None
        self.capture_path = ""

    def broadcast(self, message):
        data = json.dumps(message).encode("utf-8") + b"\n"
        with self.lock:
            items = list(self.clients.items())
        for addr, sock in items:
            try:
                sock.sendall(data)
            except OSError as e:
                print(f"[Socket] Invio fallito verso {addr}: {e}")

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
        self.renderer.wake()

    def process(self, msg):
        rgb = parse_color(msg.get("RGB"))
        if rgb:
            try:
                self.whisplay.set_rgb_fade(*rgb, duration_ms=500)
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

    def handle(self, sock, addr):
        with self.lock:
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
            with self.lock:
                self.clients.pop(addr, None)
            sock.close()

    def serve(self, host="0.0.0.0", port=12345):
        self.whisplay.on_button_press(lambda: self.broadcast({"event": "button_pressed"}))
        self.whisplay.on_button_release(lambda: self.broadcast({"event": "button_released"}))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(5)
        print(f"[Cyberdeck] In ascolto su {host}:{port}")
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
    try:
        whisplay.set_backlight(100)
    except Exception:
        pass
    state = State()
    renderer = Renderer(whisplay, state)
    renderer.start()
    server = Server(whisplay, state, renderer)
    exiting = threading.Event()

    def shutdown(*_args):
        """Spegnimento del sistema o arresto del servizio: animazione, poi uscita."""
        if exiting.is_set():
            return
        exiting.set()
        server.broadcast({"event": "app_exit_requested"})
        renderer.request_shutdown()
        try:
            whisplay.set_backlight(0)
        except Exception:
            pass
        if hasattr(whisplay, "prepare_exit"):
            try:
                whisplay.prepare_exit()
            except Exception:
                pass
        try:
            whisplay.cleanup()
        finally:
            os._exit(0)

    if hasattr(whisplay, "on_exit_request"):
        whisplay.on_exit_request(lambda: threading.Thread(target=shutdown, daemon=True).start())
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT, signal.SIGHUP):
        signal.signal(sig, shutdown)
    server.serve()


if __name__ == "__main__":
    main()
