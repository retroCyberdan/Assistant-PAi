#!/bin/bash
# Installa l'interfaccia Videotex nel chatbot Whisplay.
# Uso: bash install.sh [percorso_whisplay-ai-chatbot]   (default ~/whisplay-ai-chatbot)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$HOME/whisplay-ai-chatbot}"
PY="$APP/python"

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
   "$SRC/vtx_cyber.py" "$SRC/cyber_ui.py" "$PY/"

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
if systemctl list-unit-files 2>/dev/null | grep -q '^chatbot.service'; then
  echo "Riavvio il servizio chatbot..."
  sudo systemctl restart chatbot.service
else
  echo "Avvia il chatbot con: cd $APP && bash run_chatbot.sh"
fi
