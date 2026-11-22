#!/bin/bash
# Désinstalle Jarvis (garde vos réglages et tâches sauf si vous répondez « o »).
set -uo pipefail
JH="${JARVIS_HOME:-$HOME/.jarvis}"
launchctl bootout "gui/$(id -u)/com.thibault.jarvis.veille" 2>/dev/null; rm -f "$HOME/Library/LaunchAgents/com.thibault.jarvis.veille.plist"
pkill -f "jarvis_thibault.cli serveur" 2>/dev/null; pkill -f "jarvis-thibault serveur" 2>/dev/null; P=$(lsof -ti tcp:8765 -sTCP:LISTEN 2>/dev/null); [[ -n "$P" ]] && kill $P
osascript -e 'tell application "System Events" to delete (every login item whose name is "Jarvis")' >/dev/null 2>&1
rm -rf "$HOME/Applications/Jarvis.app" "$JH/app"
read -r -p "Supprimer aussi vos réglages, clés, tâches et briefings ($JH) ? [n/o] " R
[[ "$R" == "o" ]] && rm -rf "$JH"
echo "Jarvis est désinstallé. (OpenJarvis et Ollama restent installés.)"
