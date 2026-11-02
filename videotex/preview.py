#!/usr/bin/env python3
"""Anteprima dell'interfaccia Videotex senza Raspberry Pi.

Genera delle immagini PNG delle pagine principali per ogni tema:
    python3 preview.py [cartella_output] [tema ...]
Le variabili VTX_* funzionano come sul dispositivo (es. VTX_LOGO_TEXT=ITOMI).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
THEMES = ["videotel", "minitel", "televideo", "fosfori", "cyberpunk"]


def run_theme(out_dir, theme):
    os.environ["VTX_THEME"] = theme
    sys.path.insert(0, HERE)
    import time
    import videotex_ui as ui
    from PIL import Image

    class FakeWhisplay:
        LCD_WIDTH, LCD_HEIGHT = 240, 280
        frame = None

        def draw_image(self, x, y, w, h, data):
            self.frame = Image.frombytes("RGB", (w, h), bytes(rgb565_to_rgb(data)))

    def rgb565_to_rgb(data):
        out = bytearray()
        for i in range(0, len(data), 2):
            v = (data[i] << 8) | data[i + 1]
            out += bytes(((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
        return out

    wp = FakeWhisplay()
    st = ui.State()
    if theme == "cyberpunk":
        from cyber_ui import CyberRenderer
        r = CyberRenderer(wp, st)
        r.show = lambda img: None
    else:
        r = ui.Renderer(wp, st)

    def shot(name, settle=30.0):
        r.page_started = time.time() - settle
        r.last_tick = time.time() - settle
        r.last_frame = None
        r.render_once()
        img = wp.frame.resize((480, 560), Image.NEAREST)
        path = os.path.join(out_dir, f"{theme}-{name}.png")
        img.save(path)
        print(path)

    if theme == "cyberpunk":
        return run_cyber(out_dir, ui, r, wp, st)

    # pagina di connessione (avvio)
    sc = r.pages.boot_page([(2, "ATDT 165", ui.THEME["fg"]), (4, "Chiamata in corso", ui.THEME["dim"]),
                            (6, "Portante rilevata", ui.THEME["dim"]),
                            (8, "CONNESSO 1200/75", ui.THEME["accent"])], True)
    r.show(sc.render(cursor=(16, 8), cursor_color=ui.THEME["fg"]))
    wp.frame.resize((480, 560), Image.NEAREST).save(os.path.join(out_dir, f"{theme}-0-avvio.png"))

    st.update({"status": "idle", "text": "Long Press the button to say something.", "battery_level": 87})
    r.render_once()
    shot("1-home")
    st.update({"status": "listening", "text": "Listening..."})
    shot("2-ascolto")
    st.update({"status": "recognizing", "text": "Che tempo fa domani a Milano?"})
    st.update({"status": "answering", "text": "Domani a Milano è previsto sole al mattino e qualche nuvola nel pomeriggio, con massime di 18 gradi. Perfetto per una passeggiata!"})
    shot("3-risposta")
    st.update({"status": "idle"})
    shot("4-fine")


def run_cyber(out_dir, ui, r, wp, st):
    """Anteprime dello stile cyberpunk + GIF animata dell'avvio con glitch."""
    import time
    from PIL import Image
    frames = []
    orig_draw = wp.draw_image

    def capture(x, y, w, h, data):
        orig_draw(x, y, w, h, data)
        frames.append(wp.frame)

    wp.draw_image = capture
    os.environ["VTX_MODEM_SOUND"] = "0"
    ui.MODEM_SOUND = False
    st.update({"battery_level": 87, "network_connected": True})
    r.running = True
    r.boot()
    gif = os.path.join(out_dir, "cyberpunk-avvio.gif")
    step = max(1, len(frames) // 90)
    sel = frames[::step]
    sel[0].save(gif, save_all=True, append_images=sel[1:], duration=40 * step, loop=0)
    print(gif)
    wp.draw_image = orig_draw

    def shot(name, settle=30.0, amount=None):
        r.page_started = time.time() - settle
        r.last_tick = time.time() - settle
        r.glitch_until = 0
        r.next_glitch = time.time() + 999
        r.last_frame = None
        if amount is None:
            r.render_once()            # cambio pagina (attiva il taglio glitch)
            r.glitch_until = 0
            r.page_started = time.time() - settle
            r.last_tick = time.time() - settle
            r.last_frame = None
            r.render_once()
        else:
            s = st.snapshot()
            c, _ = r.page_home(s, time.time())
            r.show_arr(c.a, amount)
        path = os.path.join(out_dir, f"cyberpunk-{name}.png")
        wp.frame.resize((480, 560), Image.NEAREST).save(path)
        print(path)

    st.update({"status": "idle", "text": "Long Press the button to say something."})
    r.render_once()
    shot("1-home")
    shot("1b-glitch", amount=0.5)
    st.update({"status": "listening", "text": "Listening..."})
    shot("2-ascolto")
    st.update({"status": "recognizing", "text": "Che tempo fa domani a Milano?"})
    st.update({"status": "answering", "text": "Domani a Milano è previsto sole al mattino e qualche nuvola nel pomeriggio, con massime di 18 gradi."})
    shot("3-risposta")
    img = os.getenv("PREVIEW_IMAGE")
    if img:
        st.update({"image": img})
        shot("4-immagine")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "anteprime")
    themes = sys.argv[2:] or THEMES
    os.makedirs(out, exist_ok=True)
    if len(themes) == 1:
        run_theme(out, themes[0])
    else:
        for t in themes:
            subprocess.run([sys.executable, os.path.abspath(__file__), out, t], check=True)
