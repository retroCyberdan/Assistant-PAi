#!/usr/bin/env python3
"""Genera un'anteprima PNG dell'interfaccia con le impostazioni VTX_* correnti.

Uso: python3 snapshot.py output.png
Le impostazioni si passano come variabili d'ambiente (usato dal pannello web).
L'immagine contiene affiancate la pagina iniziale e una pagina di risposta.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["VTX_MODEM_SOUND"] = "0"

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import videotex_ui as ui  # noqa: E402


class FakeWhisplay:
    LCD_WIDTH, LCD_HEIGHT = 240, 280
    frame = None

    def draw_image(self, x, y, w, h, data):
        a = np.frombuffer(bytes(data), dtype=">u2").reshape(h, w)
        rgb = np.dstack(((a >> 11) * 255 // 31, ((a >> 5) & 63) * 255 // 63, (a & 31) * 255 // 31))
        self.frame = Image.fromarray(rgb.astype(np.uint8), "RGB")


def render(state_msgs, r, wp, st):
    for m in state_msgs:
        st.update(m)
    for _ in range(2):  # il primo giro registra il cambio di pagina
        r.page_started = time.time() - 60
        r.last_tick = time.time() - 60
        r.glitch_until = 0
        if hasattr(r, "next_glitch"):
            r.next_glitch = time.time() + 999
        r.last_frame = None
        r.render_once()
    return wp.frame


def main(out):
    wp = FakeWhisplay()
    st = ui.State()
    if ui.THEME_NAME == "cyberpunk":
        from cyber_ui import CyberRenderer
        r = CyberRenderer(wp, st)
    else:
        r = ui.Renderer(wp, st)
    st.update({"battery_level": 87, "network_connected": True})
    home = render([{"status": "idle", "text": "Long Press the button to say something."}], r, wp, st)
    answer = render([
        {"status": "recognizing", "text": "Che tempo fa domani?"},
        {"status": "answering", "text": "Domani è previsto sole al mattino e qualche nuvola nel pomeriggio, "
                                        "con massime di 18 gradi."},
    ], r, wp, st)
    sheet = Image.new("RGB", (240 * 2 + 12, 280), (20, 20, 24))
    sheet.paste(home, (0, 0))
    sheet.paste(answer, (252, 0))
    sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST)
    sheet.save(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "anteprima.png")
