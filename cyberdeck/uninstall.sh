#!/bin/bash
# Rimuove CYBERDECK e ripristina l'interfaccia originale del chatbot Whisplay.
# Uso: bash uninstall.sh [percorso_whisplay-ai-chatbot]
# Password e logo restano in ~/.config/cyberdeck (cancellala a mano se non ti serve più).
set -e
APP="${1:-$HOME/whisplay-ai-chatbot}"
PY="$APP/python"
if [ ! -f "$PY/chatbot-ui.original.py" ]; then
  echo "Niente da ripristinare (chatbot-ui.original.py non trovato)."
  exit 0
fi
git -C "$APP" update-index --no-assume-unchanged python/chatbot-ui.py 2>/dev/null || true
mv "$PY/chatbot-ui.original.py" "$PY/chatbot-ui.py"
rm -f "$PY"/deck_*.py
rm -rf "$PY/__pycache__"
if [ -f /etc/systemd/system/cyberdeck-panel.service ]; then
  sudo systemctl disable --now cyberdeck-panel.service >/dev/null 2>&1 || true
  sudo rm -f /etc/systemd/system/cyberdeck-panel.service /etc/sudoers.d/cyberdeck
  sudo systemctl daemon-reload
fi
echo "Interfaccia originale ripristinata. Le voci DECK_* nel .env vengono ignorate."
if systemctl list-unit-files 2>/dev/null | grep -q '^chatbot.service'; then
  sudo systemctl restart chatbot.service
fi
