#!/bin/bash
# Met Jarvis à jour sans reposer les questions et sans toucher à vos réglages ni à vos clés.
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ICI="$(cd "$(dirname "$0")" && pwd)"
JH="${JARVIS_HOME:-$HOME/.jarvis}"

[[ -x "$JH/app/.venv/bin/python" ]] || { echo "Jarvis n'est pas encore installé : lancez d'abord installer.sh"; exit 1; }

echo "Mise à jour de Jarvis…"
rsync -a --delete --exclude ".git" --exclude ".venv" --exclude "__pycache__" --exclude "tests" "$ICI/" "$JH/app/src/"
uv pip install -q -p "$JH/app/.venv" --reinstall-package jarvis-thibault "$JH/app/src"

# Corrige une heure de briefing écrite « 8h » ou « 08h00 » en « 08:00 »
"$JH/app/.venv/bin/python" -I - "$JH/config.toml" <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
def fix(m):
    t = re.match(r"\s*(\d{1,2})\s*(?:[:hH.]\s*(\d{1,2})?)?\s*$", m.group(2))
    return m.group(1) + (f'"{int(t.group(1)):02d}:{int(t.group(2) or 0):02d}"' if t else f'"{m.group(2)}"')
s = re.sub(r'(?m)^(heure\s*=\s*)"([^"]*)"', fix, s, count=1)
# Voix : modèle ElevenLabs rapide (même voix George, réponse ~2x plus rapide)
s = s.replace('elevenlabs_modele = "eleven_multilingual_v2"', 'elevenlabs_modele = "eleven_turbo_v2_5"')
open(p, "w", encoding="utf-8").write(s)
EOF

if ! grep -q "demarrer-app.sh" "$HOME/Applications/Jarvis.app/Contents/MacOS/Jarvis" 2>/dev/null; then NOUVELLE_APP=1; fi
bash "$ICI/installer-veille.sh"
bash "$JH/app/lancer.sh"
# Vérification : c'est bien la nouvelle version qui tourne, avec le nouveau design
sleep 2
ATT=$(cat "$JH/app/version" 2>/dev/null)
EN_COURS=$(curl -s -m 3 http://127.0.0.1:8765/api/version | sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p')
if [[ "$EN_COURS" == "$ATT" ]] && curl -s -m 3 http://127.0.0.1:8765/ | grep -q "ORBE — noir pur"; then
  echo "✓ Nouvelle version active (ORBE · V.$ATT, affichée en bas à droite de l'écran)."
else
  echo "✗ L'ancienne version tourne encore ($EN_COURS au lieu de $ATT) : nouvelle tentative…"
  bash "$JH/app/lancer.sh" --redemarrer; sleep 2
  curl -s -m 3 http://127.0.0.1:8765/api/version
fi
echo "✓ Jarvis est à jour, Monsieur."
if [[ "${NOUVELLE_APP:-}" == "1" ]]; then
  echo ""
  echo "  ➜ Nouvelle app Jarvis (dernière fois, elle ne changera plus). Réactivez-la une fois :"
  echo "    • Micro : acceptez la demande « Jarvis souhaite accéder au micro »"
  echo "    Réglages Système → Confidentialité et sécurité → Accès complet au disque"
  echo "    → « + » → Cmd+Maj+H → Applications → Jarvis → Ouvrir (et activez l'interrupteur)."
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
fi
