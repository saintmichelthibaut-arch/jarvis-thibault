#!/bin/bash
# Démarre Jarvis — toujours VIA l'app Jarvis, pour qu'il ait SES autorisations (micro, agenda) —
# et ouvre son écran.
#   (sans option)  : s'assure que Jarvis tourne, puis ouvre l'écran
#   --silencieux   : s'assure seulement que Jarvis tourne (utilisé par la veille, toutes les minutes)
#   --redemarrer   : arrête TOUS les Jarvis en cours puis relance proprement
#   --direct       : (interne, appelé par l'app) démarre le serveur ici même
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
PORT=$(grep -E '^port[[:space:]]*=' "$JH/config.toml" 2>/dev/null | head -1 | tr -dc '0-9'); PORT=${PORT:-8765}
URL="http://127.0.0.1:$PORT"
APP="$HOME/Applications/Jarvis.app"
ATTENDUE=$(cat "$JH/app/version" 2>/dev/null)

arreter() {
  pkill -f "jarvis_thibault.cli serveur" 2>/dev/null
  pkill -f "jarvis-thibault serveur" 2>/dev/null
  local p; p=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null); [[ -n "$p" ]] && kill $p 2>/dev/null
  for i in $(seq 1 20); do curl -s -o /dev/null -m 1 "$URL/" || return 0; sleep .3; done
  p=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null); [[ -n "$p" ]] && kill -9 $p 2>/dev/null; sleep .5
}
version() { curl -s -m 2 "$URL/api/version" 2>/dev/null | sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p'; }
a_jour() { local v; v=$(version); [[ -n "$v" && ( -z "$ATTENDUE" || "$v" == "$ATTENDUE" ) ]]; }
demarrer_ici() {
  pgrep -x ollama >/dev/null 2>&1 || pgrep -f "ollama serve" >/dev/null 2>&1 || (open -g -a Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &))
  nohup "$JH/app/.venv/bin/jarvis-thibault" serveur >> "$JH/jarvis.log" 2>&1 &
}
attendre() { for i in $(seq 1 60); do curl -s -o /dev/null -m 1 "$URL/" && return 0; sleep .5; done; return 1; }

case "${1:-}" in
  --direct)
    if ! a_jour; then [[ -n "$(version)" ]] && arreter; demarrer_ici; attendre; fi
    exit 0 ;;
  --redemarrer) arreter ;;
esac

if ! a_jour; then
  [[ -n "$(version)" ]] && arreter
  if [[ "$(uname)" == "Darwin" && -x "$APP/Contents/MacOS/Jarvis" ]]; then
    open -n -g -j -a "$APP" --args --silencieux
    attendre || { demarrer_ici; attendre; }
  else
    demarrer_ici; attendre
  fi
fi
[[ "${1:-}" == "--silencieux" || "${1:-}" == "--redemarrer" ]] && exit 0

if [[ "$(uname)" == "Darwin" && -x "$APP/Contents/MacOS/Jarvis" ]]; then open "$APP"; exit 0; fi
open "$URL/" 2>/dev/null || xdg-open "$URL/" 2>/dev/null
