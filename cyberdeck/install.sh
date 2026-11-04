#!/bin/bash
# Installa l'interfaccia CYBERDECK (e il pannello web) nel chatbot Whisplay.
# Uso: bash install.sh [--no-panel] [percorso_whisplay-ai-chatbot]   (default ~/whisplay-ai-chatbot)
#   --no-panel   non installare il pannello web (http://<raspberry>:8080)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
PANEL=1
if [ "$1" = "--no-panel" ]; then PANEL=0; shift; fi
APP="${1:-$HOME/whisplay-ai-chatbot}"
PY="$APP/python"
CONF="$HOME/.config/cyberdeck"
FILES="deck_font.py deck_gfx.py deck_ui.py deck_panel.py deck_preview.py"

if [ "$(id -u)" = "0" ]; then
  echo "Esegui lo script come utente normale (senza sudo): i permessi li chiede da solo."
  exit 1
fi
if [ ! -f "$PY/chatbot-ui.py" ] && [ ! -f "$PY/chatbot-ui.original.py" ]; then
  echo "Errore: non trovo $PY/chatbot-ui.py. Hai installato whisplay-ai-chatbot?"
  exit 1
fi

echo "== CYBERDECK =="

# 1. conserva l'interfaccia originale (una sola volta)
if [ ! -f "$PY/chatbot-ui.original.py" ]; then
  cp "$PY/chatbot-ui.py" "$PY/chatbot-ui.original.py"
  echo "Interfaccia originale salvata in chatbot-ui.original.py"
fi

# 2. pulizia delle versioni precedenti (interfacce Videotex / cyberpunk)
rm -f "$PY/vtx_font.py" "$PY/vtx_render.py" "$PY/videotex_ui.py" "$PY/vtx_cyber.py" \
      "$PY/cyber_ui.py" "$PY/snapshot.py" "$PY/vtx_panel.py"
rm -rf "$PY/__pycache__"
if [ -f /etc/systemd/system/pai-panel.service ]; then
  sudo systemctl disable --now pai-panel.service >/dev/null 2>&1 || true
  sudo rm -f /etc/systemd/system/pai-panel.service /etc/sudoers.d/pai-panel
  echo "Rimosso il vecchio pannello (pai-panel)."
fi
mkdir -p "$CONF"
if [ -f "$HOME/.config/pai-panel/config.json" ] && [ ! -f "$CONF/panel.json" ]; then
  mv "$HOME/.config/pai-panel/config.json" "$CONF/panel.json"
  rmdir "$HOME/.config/pai-panel" 2>/dev/null || true
  echo "Password del pannello mantenuta."
fi

# 3. copia i moduli
for f in $FILES; do cp "$SRC/$f" "$PY/"; done

# 4. lanciatore: sceglie l'interfaccia in base a UI_STYLE nel file .env
cat > "$PY/chatbot-ui.py" <<'PYEOF'
# Lanciatore installato da Assistant-PAi/cyberdeck/install.sh
# UI_STYLE=cyberdeck (default) oppure UI_STYLE=original nel file .env
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
style = os.getenv("UI_STYLE", "cyberdeck").strip().lower()
target = "chatbot-ui.original.py" if style == "original" else "deck_ui.py"
path = os.path.join(here, target)
sys.argv[0] = path
runpy.run_path(path, run_name="__main__")
PYEOF
git -C "$APP" update-index --assume-unchanged python/chatbot-ui.py 2>/dev/null || true

# 5. pulizia del file .env (vecchie voci VTX_*), con copia di sicurezza
if [ -f "$APP/.env" ]; then
  cp "$APP/.env" "$APP/.env.bak"
  DECK_APP_DIR="$APP" python3 "$PY/deck_panel.py" --migrate-env 2>/dev/null \
    || echo "(Pulizia del .env saltata: Flask non ancora installato)"
fi
echo "Interfaccia CYBERDECK installata."

# 6. pannello web
if [ "$PANEL" = "1" ]; then
  if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installo Flask..."
    sudo apt-get install -y python3-flask
    [ -f "$APP/.env" ] && DECK_APP_DIR="$APP" python3 "$PY/deck_panel.py" --migrate-env
  fi
  if [ ! -f "$CONF/panel.json" ]; then
    echo
    echo "== Password del pannello web =="
    if [ -t 0 ]; then
      python3 "$PY/deck_panel.py" --set-password
    else
      PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(9))")
      python3 "$PY/deck_panel.py" --set-password --password "$PW"
      echo "Password generata: $PW   (cambiala dal pannello)"
    fi
  fi
  # permesso limitato: solo riavvio dell'assistente, riavvio e spegnimento del Raspberry
  SYSTEMCTL=$(command -v systemctl || echo /usr/bin/systemctl)
  TMP=$(mktemp)
  echo "$(whoami) ALL=(root) NOPASSWD: $SYSTEMCTL restart chatbot.service, $SYSTEMCTL reboot, $SYSTEMCTL poweroff" > "$TMP"
  if sudo visudo -cf "$TMP" >/dev/null; then
    sudo install -m 0440 "$TMP" /etc/sudoers.d/cyberdeck
  fi
  rm -f "$TMP"
  sudo tee /etc/systemd/system/cyberdeck-panel.service > /dev/null <<SVC
[Unit]
Description=Pannello web CYBERDECK
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PY
Environment=DECK_APP_DIR=$APP
Environment=HOME=$HOME
ExecStart=$(command -v python3) $PY/deck_panel.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC
  sudo systemctl daemon-reload
  sudo systemctl enable cyberdeck-panel.service >/dev/null 2>&1
  sudo systemctl restart cyberdeck-panel.service
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "Pannello web: http://$(hostname).local:8080   oppure   http://$IP:8080"
fi

# 7. riavvio dell'assistente
if systemctl list-unit-files 2>/dev/null | grep -q '^chatbot.service'; then
  echo "Riavvio l'assistente..."
  sudo systemctl restart chatbot.service
else
  echo "Avvia l'assistente con: cd $APP && bash run_chatbot.sh"
fi
