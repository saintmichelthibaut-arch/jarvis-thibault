#!/bin/bash
# Installe l'app Jarvis, la veille automatique (relance Jarvis s'il s'arrête, toutes les minutes)
# et redémarre proprement la bonne version.
ICI="$(cd "$(dirname "$0")" && pwd)"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
mkdir -p "$JH/app" "$HOME/Applications"
cp "$ICI/lancer.sh" "$ICI/demarrer-app.sh" "$JH/app/" && chmod +x "$JH/app/lancer.sh" "$JH/app/demarrer-app.sh"
date +%d.%m-%H%M > "$JH/app/version"
[[ "$(uname)" == "Darwin" ]] || { bash "$JH/app/lancer.sh" --redemarrer; exit 0; }
bash "$ICI/creer-app.sh"
# l'ancien démarrage par « élément d'ouverture » est remplacé par la veille
osascript -e 'tell application "System Events" to delete (every login item whose name is "Jarvis")' >/dev/null 2>&1 || true
PL="$HOME/Library/LaunchAgents/com.thibault.jarvis.veille.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.thibault.jarvis.veille</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$JH/app/lancer.sh</string><string>--silencieux</string></array>
  <key>RunAtLoad</key><true/>
  <key>AbandonProcessGroup</key><true/>
  <key>StartInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$JH/veille.log</string>
  <key>StandardErrorPath</key><string>$JH/veille.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/com.thibault.jarvis.veille" >/dev/null 2>&1 || true
bash "$JH/app/lancer.sh" --redemarrer
launchctl bootstrap "gui/$(id -u)" "$PL" >/dev/null 2>&1 || launchctl load "$PL" >/dev/null 2>&1 || true
echo "  ✓ Veille installée : Jarvis tourne en permanence et se relance tout seul."
