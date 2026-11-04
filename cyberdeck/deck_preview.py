#!/usr/bin/env python3
"""Anteprime di CYBERDECK senza Raspberry Pi.

  python3 deck_preview.py demo CARTELLA
      simula una sessione completa (accensione, ascolto, elaborazione, risposta,
      spegnimento) e salva una GIF animata e alcune immagini
  python3 deck_preview.py snapshot FILE.png
      immagine della pagina iniziale e di una risposta (usata dal pannello web)

Le impostazioni DECK_* si passano come variabili d'ambiente, come sul dispositivo.
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402


class FakeWhisplay:
    """Finto display: conserva i fotogrammi disegnati."""
    LCD_WIDTH, LCD_HEIGHT = 240, 280

    def __init__(self, record=False):
        self.frame = None
        self.frames = []
        self.record = record

    def draw_image(self, x, y, w, h, data):
        a = np.frombuffer(bytes(data), dtype=">u2").reshape(h, w)
        rgb = np.dstack(((a >> 11) * 255 // 31, ((a >> 5) & 63) * 255 // 63, (a & 31) * 255 // 31))
        self.frame = Image.fromarray(rgb.astype(np.uint8), "RGB")
        if self.record:
            self.frames.append((time.time(), self.frame))


def snapshot(out):
    os.environ["DECK_BOOT"] = "off"
    os.environ["DECK_SOUND"] = "0"
    import deck_ui as ui
    wp = FakeWhisplay()
    st = ui.State()
    r = ui.Renderer(wp, st)
    r.intro_t0 = -10
    st.update({"battery_level": 87, "network_connected": True,
               "status": "idle", "text": "Long Press the button to say something."})
    for _ in range(3):
        r.last_tick = time.time() - 0.5
        r.render_once()
        r.morph.t0 = r.title_t0 = -10
    home = wp.frame
    st.update({"status": "recognizing", "text": "Che tempo fa domani?"})
    st.update({"status": "answering", "text": "Domani è previsto sole al mattino e qualche nuvola nel "
                                              "pomeriggio, con massime di 18 gradi."})
    for _ in range(30):
        r.last_tick = time.time() - 0.5
        r.split = ui.SPLIT_COMPACT
        r.render_once()
        r.morph.t0 = r.title_t0 = -10  # salta le transizioni: immagine a riposo
    sheet = Image.new("RGB", (240 * 2 + 12, 280), (10, 10, 10))
    sheet.paste(home, (0, 0))
    sheet.paste(wp.frame, (252, 0))
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(out)


def demo(out_dir):
    os.environ.setdefault("DECK_SOUND", "0")
    import deck_ui as ui
    os.makedirs(out_dir, exist_ok=True)
    wp = FakeWhisplay(record=True)
    st = ui.State()
    st.update({"battery_level": 87, "network_connected": True})
    r = ui.Renderer(wp, st)
    r.start()
    t_boot = time.time()
    # attende la fine dell'accensione
    while r.intro_t0 < 0 and time.time() - t_boot < 20:
        time.sleep(0.05)
    marks = {"boot_end": time.time()}
    script = [
        (0.0, {"status": "idle", "text": "Long Press the button to say something."}),
        # prima pressione del tasto
        (9.0, {"status": "listening", "text": "Listening..."}),
        (11.5, {"status": "recognizing", "text": "Che tempo fa domani a Milano?"}),
        (12.5, {"status": "answering...", "text": ""}),
        (15.0, {"status": "answering", "text": "Domani a Milano è previsto sole al mattino e qualche "
                                                "nuvola nel pomeriggio, con massime di 18 gradi."}),
        (15.1, {"scroll_sync": {"char_end": 60, "duration_ms": 2500}}),
        (17.5, {"scroll_sync": {"char_end": 200, "duration_ms": 2500}}),
        (20.0, {"status": "idle"}),
        # seconda pressione: Rocky fa qualcos'altro
        (22.0, {"status": "listening", "text": "Listening..."}),
        (24.0, {"status": "recognizing", "text": "Raccontami una curiosità sui cani"}),
        (25.0, {"status": "answering...", "text": ""}),
        (28.0, {"status": "answering", "text": "I Jack Russell sono stati selezionati in Inghilterra "
                                                "per la caccia alla volpe: instancabili e curiosi!"}),
        (32.0, {"status": "idle"}),
    ]
    t0 = time.time()
    for at, msg in script:
        while time.time() - t0 < at:
            time.sleep(0.02)
        st.update(msg)
        r.wake()
        marks.setdefault(msg.get("status", "sync") + "_%d" % int(at * 10), time.time())
    time.sleep(3.0)
    marks["shutdown"] = time.time()
    threading.Thread(target=r.request_shutdown, daemon=True).start()
    r.done.wait(20)
    frames = wp.frames
    print("fotogrammi:", len(frames), "durata: %.1fs" % (frames[-1][0] - frames[0][0]))

    # GIF a ~12 fps
    gif, last_t = [], -1
    for t, f in frames:
        if t - last_t >= 1 / 12:
            gif.append(f)
            last_t = t
    gif[0].save(os.path.join(out_dir, "cyberdeck-demo.gif"), save_all=True, append_images=gif[1:],
                duration=83, loop=0, optimize=True)

    def at(t):
        return min(frames, key=lambda fr: abs(fr[0] - t))[1]

    def clearest(t_a, t_b):
        """Fotogramma con più "inchiostro" nell'intervallo (evita i fotogrammi di glitch)."""
        cand = [f for t, f in frames if t_a <= t <= t_b] or [at(t_a)]
        return max(cand, key=lambda f: (np.asarray(f).max(axis=2) > 120).sum())

    b = marks["boot_end"]
    stills = {
        "1-logo": t_boot + 1.9, "2-terminale": b - 0.6, "3-pronto": b + 1.5,
        "4-ascolto": b + 10.5, "5-elaborazione": b + 14.0, "6-risposta": b + 19.5,
        "7-elaborazione2": b + 27.0, "8-spegnimento": marks["shutdown"] + 3.6,
    }
    for name, t in stills.items():
        p = os.path.join(out_dir, "cyberdeck-%s.png" % name)
        img = clearest(t_boot + 1.6, t_boot + 2.3) if name == "1-logo" else at(t)
        img.resize((480, 560), Image.NEAREST).save(p)
        print(p)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "demo":
        demo(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
