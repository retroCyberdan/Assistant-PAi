#!/usr/bin/env python3
"""Pannello web di Assistant-PAi.

Permette dal browser (telefono o PC, sulla stessa rete) di:
  - caricare il logo e vedere l'anteprima del display;
  - cambiare stile, colori, testi ed effetti dell'interfaccia (file .env);
  - riavviare l'assistente o il Raspberry.

Avvio:  python3 vtx_panel.py            (porta 8080, o PAI_PANEL_PORT)
Password iniziale: python3 vtx_panel.py --set-password
"""

import argparse
import functools
import getpass
import hmac
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

from flask import (Flask, Response, abort, redirect, render_template_string, request,
                   send_file, session, url_for)
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
APP_DIR = os.getenv("PAI_APP_DIR", os.path.join(HOME, "whisplay-ai-chatbot"))
ENV_PATH = os.path.join(APP_DIR, ".env")
CONF_DIR = os.path.join(HOME, ".config", "pai-panel")
CONF_PATH = os.path.join(CONF_DIR, "config.json")
ASSETS_DIR = os.getenv("PAI_ASSETS_DIR", os.path.join(HOME, "pai-assets"))
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
PORT = int(os.getenv("PAI_PANEL_PORT", "8080"))
MAX_UPLOAD = 10 * 1024 * 1024

# ------------------------------------------------------------------ campi modificabili
# (chiave, etichetta, tipo, opzioni, valore predefinito, aiuto, gruppo)
FIELDS = [
    ("UI_STYLE", "Stile interfaccia", "select",
     [("cyberpunk", "Pixel cyberpunk"), ("videotex", "Videotex (Videotel / Minitel / Televideo)"),
      ("original", "Originale PiSugar")], "videotex", "", "Stile"),
    ("VTX_THEME", "Tema Videotex", "select",
     [("videotel", "Videotel"), ("minitel", "Minitel"), ("televideo", "Televideo"),
      ("fosfori", "Fosfori verdi")], "videotel", "Usato solo con lo stile Videotex.", "Stile"),
    ("VTX_CYBER_PALETTE", "Colori cyberpunk", "select",
     [("teal", "Teal"), ("verde", "Verde"), ("ambra", "Ambra"), ("viola", "Viola")], "teal",
     "Usato solo con lo stile cyberpunk.", "Stile"),
    ("VTX_SERVICE_NAME", "Nome in testata", "text", None, "PAiTEL", "", "Testi"),
    ("VTX_LOGO_TEXT", "Logo testuale", "text", None, "PAi",
     "Usato quando non c'è un logo caricato (max ~6 caratteri).", "Testi"),
    ("VTX_TAGLINE", "Frase di avvio", "text", None, "SISTEMA NEURALE ONLINE",
     "Cyberpunk: compare sotto il logo durante l'avvio.", "Testi"),
    ("VTX_UNIT_ID", "Sigla unità", "text", None, "PAi-01", "Cyberpunk: sigla grande in home.", "Testi"),
    ("VTX_HOME_TEXT", "Testo home (cyberpunk)", "text", None,
     "In attesa di comandi. Tieni premuto il tasto e parla.", "", "Testi"),
    ("VTX_HOME_LINES", "Righe home (Videotex)", "text", None, "Tieni premuto il|tasto e parla",
     "Separa le righe con |", "Testi"),
    ("VTX_FOOTER_LINES", "Piè di pagina (cyberpunk)", "text", None,
     "PROPRIETA' DI PAi SYSTEMS|UNITA' DI ASSISTENZA VOCALE", "Due righe separate da |", "Testi"),
    ("VTX_BOOT", "Animazione di avvio", "select",
     [("full", "Completa"), ("quick", "Rapida"), ("off", "Nessuna")], "full", "", "Effetti"),
    ("VTX_MODEM_SOUND", "Suono all'avvio", "bool", None, "1", "", "Effetti"),
    ("VTX_GLITCH", "Intensità glitch", "range", (0, 1, 0.1), "0.5", "Cyberpunk: 0 = mai.", "Effetti"),
    ("VTX_CRT", "Effetto monitor CRT", "range", (0, 1, 0.1), "0.7", "", "Effetti"),
    ("VTX_PIXEL", "Grandezza pixel immagini", "select",
     [("1", "1 (più dettaglio)"), ("2", "2"), ("3", "3 (più grossi)")], "2", "Cyberpunk.", "Effetti"),
    ("VTX_UPPERCASE", "Testi in maiuscolo", "bool", None, "1", "Cyberpunk.", "Effetti"),
    ("VTX_BAUD", "Velocità di scrittura", "select",
     [("300", "300 baud (lentissimo)"), ("1200", "1200 baud (autentico)"), ("2400", "2400 baud"),
      ("4800", "4800 baud (rapido)"), ("9600", "9600 baud")], "1200", "", "Effetti"),
    ("VTX_IMAGE_MODE", "Immagini (Videotex)", "select",
     [("mosaic", "Mosaico"), ("photo", "Foto")], "mosaic", "", "Effetti"),
]
FIELD_KEYS = [f[0] for f in FIELDS]
VALUE_RE = re.compile(r"^[^\r\n\x00]{0,200}$")

# ------------------------------------------------------------------ configurazione pannello


def load_conf():
    try:
        with open(CONF_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_conf(conf):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(conf, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONF_PATH)


def set_password(pw):
    conf = load_conf()
    conf["password_hash"] = generate_password_hash(pw)
    conf.setdefault("secret_key", secrets.token_hex(32))
    save_conf(conf)


# ------------------------------------------------------------------ file .env


def parse_env(path=ENV_PATH):
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if not m:
                    continue
                v = m.group(2).strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                else:
                    v = re.sub(r"\s+#.*$", "", v)
                values[m.group(1)] = v
    except OSError:
        pass
    return values


def quote(v):
    """Racchiude il valore tra virgolette solo se serve (commenti # o spazi ai bordi)."""
    v = v.replace('"', "")
    if "#" in v or v != v.strip():
        return '"%s"' % v
    return v


def write_env(updates, path=ENV_PATH):
    """Aggiorna le chiavi nel .env lasciando intatto tutto il resto (con backup)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    done = set()
    out = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            if key in done:
                continue  # rimuove duplicati
            if updates[key] is None:
                done.add(key)
                continue
            out.append("%s=%s" % (key, quote(updates[key])))
            done.add(key)
        else:
            out.append(line)
    missing = [k for k in updates if k not in done and updates[k] is not None]
    if missing:
        if "# ---- Pannello PAi ----" not in out:
            out += ["", "# ---- Pannello PAi ----"]
        for k in missing:
            out.append("%s=%s" % (k, quote(updates[k])))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def current_settings():
    env = parse_env()
    vals = {}
    for key, _l, typ, _o, default, _h, _g in FIELDS:
        # i campi di testo non impostati restano vuoti (il predefinito appare come suggerimento)
        vals[key] = env.get(key, "" if typ == "text" else default)
    vals["_logo"] = env.get("VTX_LOGO_IMAGE", "")
    return vals


def validate(form):
    updates = {}
    for key, _l, typ, opts, default, _h, _g in FIELDS:
        if typ == "bool":
            updates[key] = "1" if form.get(key) in ("1", "on", "true") else "0"
            continue
        v = (form.get(key) or "").strip()
        if not VALUE_RE.match(v):
            abort(400, "Valore non valido per %s" % key)
        if typ == "text" and v == "":
            updates[key] = None  # campo vuoto: torna al valore predefinito
            continue
        if typ == "select" and v not in [o[0] for o in opts]:
            v = default
        if typ == "range":
            try:
                v = "%.1f" % max(opts[0], min(opts[1], float(v)))
            except ValueError:
                v = default
        updates[key] = v
    return updates


# ------------------------------------------------------------------ anteprima e logo


def make_preview(settings, logo_path=None):
    env = dict(os.environ)
    env.update(parse_env())
    for k, v in settings.items():
        if k.startswith("_"):
            continue
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    style = env.get("UI_STYLE", "videotex")
    if style == "cyberpunk":
        env["VTX_THEME"] = "cyberpunk"
    elif env.get("VTX_THEME") == "cyberpunk":
        env["VTX_THEME"] = "videotel"
    if logo_path:
        env["VTX_LOGO_IMAGE"] = logo_path
    fd, out = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "snapshot.py"), out], env=env,
                       cwd=HERE, timeout=40, check=True, capture_output=True)
        with open(out, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def save_logo(file_storage, dest):
    data = file_storage.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        abort(413, "Immagine troppo grande (max 10 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((600, 600))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
    except Exception:
        abort(400, "Il file non è un'immagine valida (usa PNG o JPG)")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    img.save(dest, "PNG")


# ------------------------------------------------------------------ comandi di sistema


def restart_assistant():
    try:
        units = subprocess.run(["systemctl", "list-unit-files", "chatbot.service"],
                               capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        units = ""
    if "chatbot.service" in units:
        r = subprocess.run(["sudo", "-n", "systemctl", "restart", "chatbot.service"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, "Assistente riavviato: guarda il display!"
        return False, "Riavvio non riuscito: " + (r.stderr.strip() or "permessi sudo mancanti")
    return False, ("Servizio chatbot.service non trovato (avvio gestito da whisplay-daemon "
                   "o manuale). Usa \"Riavvia Raspberry\".")


def reboot_pi():
    r = subprocess.run(["sudo", "-n", "systemctl", "reboot"], capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return True, "Il Raspberry si sta riavviando..."
    return False, "Riavvio non riuscito: " + (r.stderr.strip() or "permessi sudo mancanti")


# ------------------------------------------------------------------ app Flask

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD + 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["PERMANENT_SESSION_LIFETIME"] = 30 * 24 * 3600


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    token = request.form.get("csrf") or request.headers.get("X-CSRF", "")
    if not token or not hmac.compare_digest(token, session.get("csrf", "")):
        abort(403, "Sessione scaduta: ricarica la pagina")


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


app.jinja_env.globals["csrf_token"] = csrf_token

CSS = """
:root{--bg:#050d0f;--panel:#0b1d21;--line:#2c8086;--fg:#60c8c4;--hi:#baf8ee;--dim:#16464c;--alert:#ff5060}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 "DejaVu Sans Mono",Menlo,Consolas,"Liberation Mono",monospace}
header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
header b{color:var(--hi);letter-spacing:2px}
main{max-width:980px;margin:0 auto;padding:16px}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
@media(min-width:860px){.grid{grid-template-columns:1fr 1fr}}
@media(max-width:859px){.side{order:-1}.sticky{position:static}}
section{background:var(--panel);border:1px solid var(--line);padding:14px;position:relative}
section h2{margin:0 0 10px;font-size:12px;letter-spacing:2px;color:var(--line);text-transform:uppercase}
label{display:block;margin:10px 0 4px;color:var(--hi);font-size:13px;text-transform:uppercase;letter-spacing:1px}
small{color:#4f9a9a;display:block;margin-top:2px}
input[type=text],input[type=password],select{width:100%;background:#03090a;color:var(--hi);border:1px solid var(--line);padding:9px;font:inherit;border-radius:0}
input[type=range]{width:100%;accent-color:var(--fg)}
input[type=file]{color:var(--fg);max-width:100%}
.btn{display:inline-block;background:transparent;color:var(--hi);border:1px solid var(--fg);padding:10px 14px;font:inherit;text-transform:uppercase;letter-spacing:1px;cursor:pointer;margin:6px 6px 0 0}
.btn.primary{background:var(--fg);color:#021012;font-weight:bold}
.btn.warn{border-color:var(--alert);color:var(--alert)}
.btn:disabled{opacity:.5}
.preview{width:100%;image-rendering:auto;border:1px solid var(--line);background:#000;display:block}
.msg{padding:10px;border:1px solid var(--fg);margin-bottom:14px;color:var(--hi)}
.msg.err{border-color:var(--alert);color:var(--alert)}
.logo{width:96px;height:96px;object-fit:contain;image-rendering:pixelated;border:1px solid var(--dim);background:#000;vertical-align:middle;margin-right:10px}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.check{display:flex;align-items:center;gap:8px;margin-top:12px;text-transform:uppercase;font-size:13px;color:var(--hi)}
a{color:var(--hi)}
.sticky{position:sticky;top:8px}
"""

PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pannello PAi</title><style>{{ css }}</style></head><body>
<header><b>PAi // PANNELLO</b>{% if auth %}<a href="{{ url_for('logout') }}">esci</a>{% endif %}</header>
<main>
{% if msg %}<div class="msg {{ 'err' if err else '' }}">{{ msg }}</div>{% endif %}
{% block body %}{% endblock %}
</main></body></html>"""

LOGIN = PAGE.replace("{% block body %}{% endblock %}", """
<section style="max-width:420px;margin:40px auto">
<h2>Accesso</h2>
<form method="post">
<label>Password</label><input type="password" name="password" autofocus autocomplete="current-password">
<button class="btn primary" type="submit">Entra</button>
</form></section>""")

MAIN = PAGE.replace("{% block body %}{% endblock %}", """
<form id="f" method="post" action="{{ url_for('save') }}" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="{{ csrf_token() }}">
<div class="grid">
<div>
<section>
<h2>Logo</h2>
<div class="row">
{% if has_logo %}<img class="logo" src="{{ url_for('logo') }}?t={{ now }}" alt="logo attuale">{% endif %}
<div>{% if has_logo %}Logo caricato{% else %}Nessun logo: viene usato il logo testuale{% endif %}</div>
</div>
<label>Carica nuovo logo (PNG / JPG)</label>
<input type="file" name="logo" accept="image/png,image/jpeg,image/webp,image/gif">
<small>Meglio immagini ad alto contrasto su sfondo scuro. Verrà ricostruita in pixel.</small>
{% if has_logo %}<label class="check"><input type="checkbox" name="remove_logo" value="1"> Rimuovi logo (usa il testo)</label>{% endif %}
</section>
{% for group in groups %}
<section style="margin-top:16px"><h2>{{ group }}</h2>
{% for key, label, typ, opts, default, help, g in fields if g == group %}
  {% if typ == 'bool' %}
  <label class="check"><input type="checkbox" name="{{ key }}" value="1" {% if values[key] == '1' %}checked{% endif %}> {{ label }}</label>
  {% else %}
  <label for="{{ key }}">{{ label }}{% if typ == 'range' %}: <span id="{{ key }}_v">{{ values[key] }}</span>{% endif %}</label>
  {% if typ == 'select' %}
  <select id="{{ key }}" name="{{ key }}">{% for v, t in opts %}<option value="{{ v }}" {% if values[key] == v %}selected{% endif %}>{{ t }}</option>{% endfor %}</select>
  {% elif typ == 'range' %}
  <input id="{{ key }}" type="range" name="{{ key }}" min="{{ opts[0] }}" max="{{ opts[1] }}" step="{{ opts[2] }}" value="{{ values[key] }}" oninput="document.getElementById('{{ key }}_v').textContent=this.value">
  {% else %}
  <input id="{{ key }}" type="text" name="{{ key }}" value="{{ values[key] }}" placeholder="{{ default }}" maxlength="200">
  {% endif %}
  {% endif %}
  {% if help %}<small>{{ help }}</small>{% endif %}
{% endfor %}
</section>
{% endfor %}
</div>
<div class="side"><div class="sticky">
<section>
<h2>Anteprima display</h2>
<img id="pv" class="preview" src="{{ url_for('preview_saved') }}?t={{ now }}" alt="anteprima">
<small>Sinistra: pagina iniziale. Destra: risposta.</small>
<button class="btn" type="button" id="pvbtn" onclick="livePreview()">Anteprima modifiche</button>
</section>
<section style="margin-top:16px">
<h2>Applica</h2>
<button class="btn primary" type="submit" name="action" value="save_restart">Salva e riavvia assistente</button>
<button class="btn" type="submit" name="action" value="save">Salva soltanto</button>
<br><button class="btn warn" type="submit" name="action" value="reboot" formnovalidate onclick="return confirm('Riavviare il Raspberry?')">Riavvia Raspberry</button>
<small>Le modifiche compaiono sul display dopo il riavvio dell'assistente.</small>
</section>
<section style="margin-top:16px">
<h2>Password</h2>
<a href="{{ url_for('password') }}">Cambia password del pannello</a>
</section>
</div></div>
</div></form>
<script>
async function livePreview(){
  const b=document.getElementById('pvbtn'); b.disabled=true; b.textContent='Genero...';
  try{
    const r=await fetch('{{ url_for("preview_live") }}',{method:'POST',body:new FormData(document.getElementById('f'))});
    if(!r.ok) throw new Error(await r.text());
    document.getElementById('pv').src=URL.createObjectURL(await r.blob());
  }catch(e){alert('Anteprima non riuscita: '+e.message)}
  b.disabled=false; b.textContent='Anteprima modifiche';
}
</script>""")

PASSWORD = PAGE.replace("{% block body %}{% endblock %}", """
<section style="max-width:420px;margin:20px auto"><h2>Cambia password</h2>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf_token() }}">
<label>Password attuale</label><input type="password" name="old" autocomplete="current-password">
<label>Nuova password (min. 8 caratteri)</label><input type="password" name="new" autocomplete="new-password">
<label>Ripeti nuova password</label><input type="password" name="new2" autocomplete="new-password">
<button class="btn primary" type="submit">Salva</button> <a href="{{ url_for('index') }}">annulla</a>
</form></section>""")


def render(tpl, **kw):
    kw.setdefault("msg", session.pop("msg", None))
    kw.setdefault("err", session.pop("err", False))
    return render_template_string(tpl, css=CSS, auth=session.get("auth"), **kw)


def flash_msg(text, err=False):
    session["msg"] = text
    session["err"] = err


_failed = {}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        n, until = _failed.get(ip, (0, 0))
        if time.time() < until:
            return render(LOGIN, msg="Troppi tentativi: riprova tra un minuto.", err=True), 429
        conf = load_conf()
        pw = request.form.get("password", "")
        if conf.get("password_hash") and check_password_hash(conf["password_hash"], pw):
            _failed.pop(ip, None)
            session.clear()
            session.permanent = True
            session["auth"] = True
            return redirect(url_for("index"))
        n += 1
        _failed[ip] = (n, time.time() + 60 if n >= 5 else 0)
        time.sleep(1)
        return render(LOGIN, msg="Password errata.", err=True), 401
    return render(LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    groups = []
    for f in FIELDS:
        if f[6] not in groups:
            groups.append(f[6])
    vals = current_settings()
    has_logo = bool(vals["_logo"]) and os.path.exists(vals["_logo"])
    return render(MAIN, fields=FIELDS, groups=groups, values=vals, has_logo=has_logo,
                  now=int(time.time()))


@app.route("/save", methods=["POST"])
@login_required
def save():
    check_csrf()
    action = request.form.get("action", "save")
    if action == "reboot":
        ok, text = reboot_pi()
        flash_msg(text, not ok)
        return redirect(url_for("index"))
    updates = validate(request.form)
    f = request.files.get("logo")
    if f and f.filename:
        save_logo(f, LOGO_PATH)
        updates["VTX_LOGO_IMAGE"] = LOGO_PATH
    elif request.form.get("remove_logo") == "1":
        updates["VTX_LOGO_IMAGE"] = None
    write_env(updates)
    if action == "save_restart":
        ok, text = restart_assistant()
        flash_msg("Impostazioni salvate. " + text, not ok)
    else:
        flash_msg("Impostazioni salvate. Riavvia l'assistente per vederle sul display.")
    return redirect(url_for("index"))


@app.route("/preview.png")
@login_required
def preview_saved():
    try:
        png = make_preview({})
    except Exception as e:
        return Response("Anteprima non disponibile: %s" % e, status=500, mimetype="text/plain")
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/preview", methods=["POST"])
@login_required
def preview_live():
    check_csrf()
    settings = validate(request.form)
    logo_tmp = None
    try:
        f = request.files.get("logo")
        if f and f.filename:
            fd, logo_tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            save_logo(f, logo_tmp)
        elif request.form.get("remove_logo") == "1":
            settings["VTX_LOGO_IMAGE"] = ""
        png = make_preview(settings, logo_tmp)
    except subprocess.CalledProcessError as e:
        return Response("Errore: %s" % (e.stderr or b"").decode(errors="replace")[-400:],
                        status=500, mimetype="text/plain")
    finally:
        if logo_tmp:
            try:
                os.remove(logo_tmp)
            except OSError:
                pass
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/logo.png")
@login_required
def logo():
    path = parse_env().get("VTX_LOGO_IMAGE", "")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/png", max_age=0)


@app.route("/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        check_csrf()
        conf = load_conf()
        if not check_password_hash(conf.get("password_hash", ""), request.form.get("old", "")):
            return render(PASSWORD, msg="Password attuale errata.", err=True)
        new = request.form.get("new", "")
        if len(new) < 8 or new != request.form.get("new2"):
            return render(PASSWORD, msg="La nuova password deve avere almeno 8 caratteri e coincidere.",
                          err=True)
        set_password(new)
        flash_msg("Password aggiornata.")
        return redirect(url_for("index"))
    return render(PASSWORD)


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(413)
def client_error(e):
    return render(PAGE, msg=getattr(e, "description", str(e)), err=True), e.code


def main():
    ap = argparse.ArgumentParser(description="Pannello web di Assistant-PAi")
    ap.add_argument("--set-password", action="store_true", help="imposta la password del pannello")
    ap.add_argument("--password", help="password (non interattivo)")
    ap.add_argument("--host", default=os.getenv("PAI_PANEL_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    if args.set_password:
        pw = args.password or os.getenv("PAI_PANEL_PASSWORD")
        while not pw:
            pw = getpass.getpass("Nuova password del pannello (min. 8 caratteri): ")
            if len(pw) < 8 or pw != getpass.getpass("Ripeti la password: "):
                print("Le password non coincidono o sono troppo corte.")
                pw = None
        set_password(pw)
        print("Password salvata in", CONF_PATH)
        return
    conf = load_conf()
    if not conf.get("password_hash"):
        print("Nessuna password impostata. Esegui: python3 vtx_panel.py --set-password")
        sys.exit(1)
    app.secret_key = conf["secret_key"]
    print(f"Pannello PAi su http://{args.host}:{args.port}  (file .env: {ENV_PATH})")
    from werkzeug.serving import run_simple
    run_simple(args.host, args.port, app, threaded=True)


if __name__ == "__main__":
    main()
