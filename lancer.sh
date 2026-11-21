#!/bin/bash
# Démarre Jarvis (si besoin) puis ouvre son écran dans une fenêtre à part.
#   --silencieux : démarre seulement, sans ouvrir de fenêtre
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
PORT=$(grep -E '^port[[:space:]]*=' "$JH/config.toml" 2>/dev/null | head -1 | tr -dc '0-9'); PORT=${PORT:-8765}
URL="http://localhost:$PORT/"

if ! curl -s -o /dev/null "$URL"; then
  pgrep -x ollama >/dev/null 2>&1 || open -a Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &)
  nohup "$JH/app/.venv/bin/jarvis-thibault" serveur >> "$JH/jarvis.log" 2>&1 &
  for i in $(seq 1 40); do curl -s -o /dev/null "$URL" && break; sleep 0.5; done
fi
[[ "${1:-}" == "--silencieux" ]] && exit 0

# 1) L'app « Jarvis Écran » créée avec Safari (Fichier → Ajouter au Dock)
for ECRAN in "$HOME/Applications/Jarvis Écran.app" "$HOME/Applications/Jarvis Ecran.app"; do
  if [[ -d "$ECRAN" ]]; then open "$ECRAN"; exit 0; fi
done
# 2) Sinon Chrome en mode application (fenêtre sans onglets ni barre d'adresse)
if [[ -d "/Applications/Google Chrome.app" ]]; then
  open -na "Google Chrome" --args --app="$URL" --start-fullscreen
  exit 0
fi
# 3) Sinon le navigateur par défaut
open "$URL"
