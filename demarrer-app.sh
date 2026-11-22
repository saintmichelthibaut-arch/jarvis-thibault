#!/bin/bash
# Appelé par ~/Applications/Jarvis.app (qui reste toujours identique, pour garder ses autorisations).
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
bash "$JH/app/lancer.sh" --direct
[[ "${1:-}" == "--silencieux" ]] && exit 0
exec "$JH/app/.venv/bin/python" -m jarvis_thibault.cli app
