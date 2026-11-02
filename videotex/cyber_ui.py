"""Pagine e animazioni dello stile "pixel cyberpunk" (VTX_THEME=cyberpunk).

Riusa lo stato, il server socket e il ciclo di disegno di videotex_ui.py;
cambia solo il modo in cui le pagine vengono composte e animate.
"""

import os
import time

import numpy as np

import videotex_ui as vu
from vtx_cyber import (
    BG, DARK, MID, LINE, FG, HI, ALERT, GLITCH, TAGLINE, UNIT_ID, FOOTER_LINES,
    Canvas, wrap, prep, pixelize, load_logo, glitch, static_noise, local_ip, glitch_wav,
)
from vtx_render import crt_effect

W, H = 240, 280
COLS_THIN = (W - 8) // 10        # 23 caratteri per riga col font sottile
HOME_TEXT = vu._env("VTX_HOME_TEXT", "In attesa di comandi. Tieni premuto il tasto e parla.")
KATAKANA = vu._env("VTX_KATAKANA", "アシスタント")


def status_label(st, status):
    return prep(vu.STATUS_LABELS.get(st, status))


class CyberRenderer(vu.Renderer):
    def __init__(self, whisplay, state):
        super().__init__(whisplay, state)
        self.rng = np.random.default_rng()
        self.glitch_until = 0.0
        self.glitch_amount = 0.0
        self.next_glitch = time.time() + 6
        self._logo_small = None
        self._image = (None, None)
        self._ip = (0.0, "")

    # ------------------------------------------------------------ output
    def show_arr(self, arr, amount=0.0):
        if amount > 0:
            arr = glitch(arr, amount, self.rng)
        img = vu.Image.fromarray(arr, "RGB")
        if vu.CRT > 0:
            img = crt_effect(img, vu.CRT)
        data = vu.to_rgb565(img)
        if data == self.last_frame:
            return
        self.last_frame = data
        self.whisplay.draw_image(0, 0, self.width, self.height, list(data))

    def ip(self):
        if time.time() - self._ip[0] > 30:
            self._ip = (time.time(), local_ip())
        return self._ip[1]

    # ------------------------------------------------------------ elementi comuni
    def header(self, c, s, now):
        c.frame(0, 0, W, H, DARK)
        c.text(5, 2, prep(vu.SERVICE_NAME)[:9], HI, "thin")
        net = s["network"]
        if net is False:
            sig, col = "NO SIGNAL", ALERT if int(now * 2) % 2 == 0 else DARK
        else:
            sig, col = "SIGNAL OK", FG
        c.text(118 - 0, 6, sig, col, "small")
        c.battery(W - 5, 6, s["battery"])
        c.hline(0, 20, W, LINE)

    def footer(self, c, s, now, label=None):
        c.hline(0, 252, W, LINE)
        if label is None:
            for i, ln in enumerate(FOOTER_LINES[:2]):
                c.text_center(256 + i * 11, prep(ln)[:30], LINE, "small", 20, W - 20)
            c.emblem(6, 257, FG, MID)
            c.emblem(W - 18, 257, FG, MID)
        else:
            c.text(5, 261, "> " + label[:24], FG, "small")
            c.text_right(W - 5, 261, time.strftime("%H:%M:%S"), LINE, "small")

    # ------------------------------------------------------------ pagine
    def page_home(self, s, now):
        c = Canvas(W, H)
        self.header(c, s, now)
        # riga "unità" con sigla grande
        c.text(5, 24, "UNITA'", LINE, "small")
        c.text(5, 35, prep(UNIT_ID)[:12], HI, "bold")
        c.text_right(W - 5, 24, "ACCESSO", LINE, "small")
        c.text_right(W - 5, 35, "********", MID, "small")
        c.text_right(W - 5, 45, "LIV. 3", LINE, "small")
        c.hline(0, 58, W, LINE)
        # pannello logo
        if self._logo_small is None:
            self._logo_small = load_logo(112, 112)
        c.frame(4, 62, 116, 116, LINE)
        c.blit(self._logo_small, 6, 64)
        c.corners(4, 62, 116, 116, HI)
        # colonna informazioni
        x = 126
        rows = [
            ("MODELLO AI", os.getenv("LLM_SERVER", "--")),
            ("VOCE", os.getenv("TTS_SERVER", "--")),
            ("IP", self.ip()),
        ]
        y = 62
        for label, value in rows:
            c.text(x, y, label, LINE, "small")
            v = prep(str(value))
            if len(v) <= 10:
                c.text(x, y + 10, v, FG, "thin")
                y += 32
            else:
                c.text(x, y + 11, v[:18], FG, "small")
                y += 26
        c.text(x, 152, KATAKANA[:10], FG, "thin")
        c.barcode(x, 172, 4, 165, MID)
        c.vline(122, 58, 122, LINE)
        c.hline(0, 180, W, LINE)
        # testo
        text = HOME_TEXT
        if "double click" in (s["text"] or ""):
            text += " Doppio clic: fotocamera."
        for i, ln in enumerate(wrap(text, COLS_THIN)[:3]):
            c.text(5, 186 + i * 20, ln, FG, "thin")
        c.text_right(W - 5, 240, time.strftime("%d.%m.%Y %H:%M"), LINE, "small")
        self.footer(c, s, now)
        return c, False

    def page_conv(self, s, now, dt):
        c = Canvas(W, H)
        self.header(c, s, now)
        st = s["st"]
        blink = int(now * 2) % 2 == 0
        # --- input
        c.text(5, 24, "INPUT // UTENTE", LINE, "small")
        q = s["question"]
        qlines = wrap(q, COLS_THIN)[:3] if q else []
        if st in ("listening", "detecting") and not q:
            c.text(5, 36, ">" + ("_" if blink else ""), FG, "thin")
        for i, ln in enumerate(qlines):
            c.text(5, 36 + i * 18, ln, FG, "thin")
        c.hline(4, 92, W - 8, MID, dash=2)
        # --- output
        c.text(5, 96, "OUTPUT // " + prep(vu.SERVICE_NAME)[:12], LINE, "small")
        if st == "listening":
            if blink:
                c.rect(W - 40, 97, 6, 6, ALERT)
            c.text(W - 30, 96, "REC", ALERT, "small")
            # equalizzatore animato
            n = 28
            heights = np.abs(np.sin(now * 7 + np.arange(n) * 0.7)) * 0.5 + self.rng.random(n) * 0.5
            for i, hgt in enumerate(heights):
                bh = int(8 + hgt * 90)
                col = HI if hgt > 0.75 else (FG if hgt > 0.4 else MID)
                c.rect(8 + i * 8, 200 - bh // 2, 5, bh, col)
            self.footer(c, s, now, status_label(st, s["status"]))
            return c, True
        a = s["answer"]
        lines = wrap(a, COLS_THIN) if a else []
        total = sum(len(ln) + 1 for ln in lines)
        # rivelazione progressiva (segue la voce se disponibile)
        if a != self.last_a and not a.startswith(self.last_a[: max(0, len(self.last_a) - 2)]):
            self.revealed = 0.0
        if q != self.last_q:
            self.revealed = 0.0
            self.last_q = q
        self.last_a = a
        target = total
        if vu.SYNC_SPEECH and st == "answering" and s["sync_char_end"] is not None:
            target = min(total, s["sync_char_end"] + 1)
        if self.revealed < target:
            self.revealed = min(float(target), self.revealed + max(dt, 0.0) * vu.CPS)
        budget = int(self.revealed)
        shown = []
        for ln in lines:
            if budget >= len(ln) + 1:
                shown.append(ln)
                budget -= len(ln) + 1
            else:
                shown.append(ln[: max(0, budget)])
                break
        visible = shown[-8:]
        col = ALERT if st == "error" else HI
        for i, ln in enumerate(visible):
            c.text(5, 108 + i * 18, ln, col, "thin")
        typing = self.revealed < target
        thinking = st not in ("idle", "answering", "error") and not a
        if visible and (blink or typing):
            cx = 5 + len(visible[-1]) * 10
            cy = 108 + (len(visible) - 1) * 18
            if cx < W - 10:
                c.rect(cx, cy + 2, 8, 14, MID)
        elif thinking:
            dots = int(now * 4) % 4
            c.text(5, 108, "ELABORAZIONE" + "." * dots, FG, "thin")
        self.footer(c, s, now, status_label(st, s["status"]))
        return c, typing or thinking

    def page_image(self, s, now, elapsed):
        c = Canvas(W, H)
        self.header(c, s, now)
        path = s["image_path"]
        if self._image[0] != path:
            try:
                arr = pixelize(path, 228, 210)
            except Exception as e:
                print(f"[Cyber] Immagine non leggibile {path}: {e}")
                arr = None
            self._image = (path, arr)
        arr = self._image[1]
        c.text(5, 24, "IMG // RICOSTRUZIONE", LINE, "small")
        c.frame(4, 36, 232, 214, LINE)
        anim = False
        if arr is not None:
            # scansione dall'alto verso il basso
            rows = int(min(1.0, elapsed / 1.4) * arr.shape[0])
            c.blit(arr[:rows], 6, 38)
            if rows < arr.shape[0]:
                c.rect(6, 38 + rows, 228, 2, HI)
                anim = True
        c.corners(4, 36, 232, 214, HI)
        self.footer(c, s, now, status_label(s["st"], s["status"]))
        return c, anim

    # ------------------------------------------------------------ avvio
    def boot(self):
        mode = vu.BOOT_MODE
        self.page_kind = None
        if mode == "off":
            return
        if mode != "full":
            self.glitch_until = time.time() + 0.6
            return
        path = "/tmp/vtx_glitch.wav"
        try:
            glitch_wav(path)
            vu.play_wav(path)
        except Exception as e:
            print(f"[Cyber] Suono di avvio non disponibile: {e}")
        logo = load_logo(200, 200)
        s = self.state.snapshot()
        batt = s["battery"]
        log = [
            ("PAi-OS 1.0 // (C) " + time.strftime("%Y"), FG),
            ("> CODEC AUDIO ..... OK", FG),
            ("> DISPLAY ST7789 .. OK", FG),
            ("> RETE " + ("." * 11) + " " + ("OK" if self.ip() != "0.0.0.0" else "--"), FG),
            ("> BATTERIA ........ " + (str(batt) + "%" if batt is not None else "--"), FG),
            ("> LINK NEURALE .... OK", HI),
        ]
        start = time.time()
        T_NOISE, T_LOGO, T_TAG, T_LOG, T_END = 0.6, 2.8, 4.2, 5.8, 6.3
        while self.running:
            el = time.time() - start
            if el > T_END:
                break
            c = Canvas(W, H, BG)
            amount = 0.0
            if el < T_NOISE:
                c.a = static_noise(H, W, self.rng, density=0.6 - el)
                amount = 0.6
            elif el < T_TAG:
                c.blit(logo, 20, 20)
                k = (el - T_NOISE) / (T_LOGO - T_NOISE)
                amount = max(0.08, 1.0 - k) if el < T_LOGO else (0.5 if self.rng.random() < 0.12 else 0.0)
                if el < T_LOGO and self.rng.random() < 0.12:
                    c.a[:, :] = BG  # sfarfallio
            elif el < T_LOG:
                c.blit(logo, 20, 20)
                tl = prep(TAGLINE)
                n = int((el - T_TAG) * 25)
                c.text_center(236, tl[:n][:COLS_THIN], HI, "thin")
                if self.rng.random() < 0.15:
                    amount = 0.35
            else:
                n = int((el - T_LOG) * 12) + 1
                for i, (ln, col) in enumerate(log[:n]):
                    c.text(6, 20 + i * 14, ln[:38], col, "small")
                if el > T_END - 0.25:
                    amount = 0.9
            self.show_arr(c.a, amount)
            time.sleep(1 / 25)
        self.glitch_until = time.time() + 0.4

    # ------------------------------------------------------------ ciclo
    def render_once(self):
        s = self.state.snapshot()
        if s["camera_mode"]:
            return False
        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now
        st = s["st"]
        if s["image_path"]:
            kind = "image"
        elif st in ("idle", "starting") and (
                (not s["answer"] and not s["question"])
                or (vu.HOME_TIMEOUT > 0 and now - s["last_activity"] > vu.HOME_TIMEOUT)):
            kind = "home"
        else:
            kind = "conv"
        if kind != self.page_kind:
            if self.page_kind is not None:
                self.glitch_until = now + 0.3  # taglio glitch tra le pagine
            self.page_kind = kind
            self.page_started = now
            self.revealed = 0.0
            self.last_q = None
            self.last_a = ""
        elapsed = now - self.page_started
        if kind == "image":
            c, anim = self.page_image(s, now, elapsed)
        elif kind == "home":
            c, anim = self.page_home(s, now)
        else:
            c, anim = self.page_conv(s, now, dt)

        # glitch: taglio tra pagine o piccoli disturbi casuali a riposo
        amount = 0.0
        if now < self.glitch_until:
            amount = 0.7
        elif GLITCH > 0 and kind == "home":
            if now >= self.next_glitch:
                self.glitch_until = now + float(self.rng.uniform(0.1, 0.35))
                self.glitch_amount = float(self.rng.uniform(0.2, 0.6)) * GLITCH
                self.next_glitch = now + float(self.rng.uniform(4, 12)) / max(GLITCH, 0.1)
            if now < self.glitch_until:
                amount = self.glitch_amount
        self.show_arr(c.a, amount)
        return anim or amount > 0 or now < self.glitch_until
