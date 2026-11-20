#!/bin/bash
# Désinstalle Jarvis (garde vos réglages et tâches sauf si vous répondez « o »).
set -uo pipefail
JH="${JARVIS_HOME:-$HOME/.jarvis}"
pkill -f "jarvis-thibault serveur" 2>/dev/null
osascript -e 'tell application "System Events" to delete (every login item whose name is "Jarvis")' >/dev/null 2>&1
rm -rf "$HOME/Applications/Jarvis.app" "$JH/app"
read -r -p "Supprimer aussi vos réglages, clés, tâches et briefings ($JH) ? [n/o] " R
[[ "$R" == "o" ]] && rm -rf "$JH"
echo "Jarvis est désinstallé. (OpenJarvis et Ollama restent installés.)"
