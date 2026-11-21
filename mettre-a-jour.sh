#!/bin/bash
# Met Jarvis à jour sans reposer les questions et sans toucher à vos réglages ni à vos clés.
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ICI="$(cd "$(dirname "$0")" && pwd)"
JH="${JARVIS_HOME:-$HOME/.jarvis}"

[[ -x "$JH/app/.venv/bin/python" ]] || { echo "Jarvis n'est pas encore installé : lancez d'abord installer.sh"; exit 1; }

echo "Mise à jour de Jarvis…"
rsync -a --delete --exclude ".venv" --exclude "__pycache__" --exclude "tests" "$ICI/" "$JH/app/src/"
uv pip install -q -p "$JH/app/.venv" --reinstall-package jarvis-thibault "$JH/app/src"
cp "$ICI/lancer.sh" "$JH/app/lancer.sh" && chmod +x "$JH/app/lancer.sh"

# Corrige une heure de briefing écrite « 8h » ou « 08h00 » en « 08:00 »
"$JH/app/.venv/bin/python" -I - "$JH/config.toml" <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
def fix(m):
    t = re.match(r"\s*(\d{1,2})\s*(?:[:hH.]\s*(\d{1,2})?)?\s*$", m.group(2))
    return m.group(1) + (f'"{int(t.group(1)):02d}:{int(t.group(2) or 0):02d}"' if t else f'"{m.group(2)}"')
s = re.sub(r'(?m)^(heure\s*=\s*)"([^"]*)"', fix, s, count=1)
open(p, "w", encoding="utf-8").write(s)
EOF

pkill -f "jarvis-thibault serveur" 2>/dev/null || true
sleep 1
bash "$JH/app/lancer.sh"
echo "✓ Jarvis est à jour, Monsieur."
