#!/bin/bash
# Installa l'interfaccia Videotex nel chatbot Whisplay.
# Uso: bash install.sh [--no-panel] [percorso_whisplay-ai-chatbot]   (default ~/whisplay-ai-chatbot)
#   --no-panel   non installare il pannello web (http://<raspberry>:8080)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
PANEL=1
if [ "$1" = "--no-panel" ]; then PANEL=0; shift; fi
APP="${1:-$HOME/whisplay-ai-chatbot}"
PY="$APP/python"

if [ "$(id -u)" = "0" ]; then
  echo "Esegui lo script come utente normale (senza sudo): i permessi li chiede da solo."
  exit 1
fi

if [ ! -f "$PY/chatbot-ui.py" ] && [ ! -f "$PY/chatbot-ui.original.py" ]; then
  echo "Errore: non trovo $PY/chatbot-ui.py. Hai installato whisplay-ai-chatbot?"
  exit 1
fi

# 1. conserva l'interfaccia originale (una sola volta)
if [ ! -f "$PY/chatbot-ui.original.py" ]; then
  cp "$PY/chatbot-ui.py" "$PY/chatbot-ui.original.py"
  echo "Interfaccia originale salvata in chatbot-ui.original.py"
fi

# 2. copia i moduli Videotex
cp "$SRC/vtx_font.py" "$SRC/vtx_render.py" "$SRC/videotex_ui.py" \
   "$SRC/vtx_cyber.py" "$SRC/cyber_ui.py" "$SRC/snapshot.py" "$SRC/vtx_panel.py" "$PY/"

# 3. lanciatore: sceglie l'interfaccia in base a UI_STYLE nel file .env
cat > "$PY/chatbot-ui.py" <<'PYEOF'
# Lanciatore installato da Assistant-PAi/videotex/install.sh
# UI_STYLE=videotex (default) | cyberpunk | original nel file .env
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
style = os.getenv("UI_STYLE", "videotex").strip().lower()
if style == "cyberpunk":
    os.environ["VTX_THEME"] = "cyberpunk"
target = "videotex_ui.py" if style in ("videotex", "cyberpunk") else "chatbot-ui.original.py"
path = os.path.join(here, target)
sys.argv[0] = path
runpy.run_path(path, run_name="__main__")
PYEOF

# 4. evita che git segnali il file come modificato
git -C "$APP" update-index --assume-unchanged python/chatbot-ui.py 2>/dev/null || true

echo "Interfaccia Videotex installata."

# 5. pannello web
if [ "$PANEL" = "1" ]; then
  if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installo Flask..."
    sudo apt-get install -y python3-flask
  fi
  if [ ! -f "$HOME/.config/pai-panel/config.json" ]; then
    echo
    echo "== Password del pannello web =="
    if [ -t 0 ]; then
      python3 "$PY/vtx_panel.py" --set-password
    else
      PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(9))")
      python3 "$PY/vtx_panel.py" --set-password --password "$PW"
      echo "Password generata: $PW   (cambiala dal pannello)"
    fi
  fi
  # permesso limitato: riavviare solo l'assistente o il Raspberry senza password
  SUDOERS_TMP=$(mktemp)
  SYSTEMCTL=$(command -v systemctl || echo /usr/bin/systemctl)
  echo "$(whoami) ALL=(root) NOPASSWD: $SYSTEMCTL restart chatbot.service, $SYSTEMCTL reboot" > "$SUDOERS_TMP"
  if sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
    sudo install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/pai-panel
  fi
  rm -f "$SUDOERS_TMP"
  sudo tee /etc/systemd/system/pai-panel.service > /dev/null <<SVC
[Unit]
Description=Pannello web Assistant-PAi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PY
Environment=PAI_APP_DIR=$APP
Environment=HOME=$HOME
ExecStart=$(command -v python3) $PY/vtx_panel.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC
  sudo systemctl daemon-reload
  sudo systemctl enable pai-panel.service >/dev/null 2>&1
  sudo systemctl restart pai-panel.service
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "Pannello web attivo: http://$(hostname).local:8080   oppure   http://$IP:8080"
fi
if systemctl list-unit-files 2>/dev/null | grep -q '^chatbot.service'; then
  echo "Riavvio il servizio chatbot..."
  sudo systemctl restart chatbot.service
else
  echo "Avvia il chatbot con: cd $APP && bash run_chatbot.sh"
fi
