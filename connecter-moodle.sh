#!/bin/bash
# Connecte Jarvis à votre Moodle (devoirs, échéances, cours), puis redémarre Jarvis.
JH="${JARVIS_HOME:-$HOME/.jarvis}"
"$JH/app/.venv/bin/jarvis-thibault" moodle || exit 1
pkill -f "jarvis-thibault serveur" 2>/dev/null; pkill -f "jarvis_thibault.cli serveur" 2>/dev/null
sleep 1
bash "$JH/app/lancer.sh" --silencieux
echo "✓ Jarvis connaît maintenant vos devoirs. Demandez-lui : « Qu'est-ce que j'ai à rendre cette semaine ? »"
