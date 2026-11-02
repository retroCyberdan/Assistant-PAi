#!/bin/bash
# Ripristina l'interfaccia originale del chatbot Whisplay.
# Uso: bash uninstall.sh [percorso_whisplay-ai-chatbot]
set -e
APP="${1:-$HOME/whisplay-ai-chatbot}"
PY="$APP/python"
if [ -f "$PY/chatbot-ui.original.py" ]; then
  git -C "$APP" update-index --no-assume-unchanged python/chatbot-ui.py 2>/dev/null || true
  mv "$PY/chatbot-ui.original.py" "$PY/chatbot-ui.py"
  rm -f "$PY/vtx_font.py" "$PY/vtx_render.py" "$PY/videotex_ui.py"
  echo "Interfaccia originale ripristinata."
  if systemctl list-unit-files 2>/dev/null | grep -q '^chatbot.service'; then
    sudo systemctl restart chatbot.service
  fi
else
  echo "Niente da ripristinare (chatbot-ui.original.py non trovato)."
fi
