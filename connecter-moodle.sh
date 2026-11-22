#!/bin/bash
# Connecte Jarvis à votre Moodle (devoirs, échéances, cours), puis redémarre Jarvis.
JH="${JARVIS_HOME:-$HOME/.jarvis}"
"$JH/app/.venv/bin/jarvis-thibault" moodle || exit 1
bash "$JH/app/lancer.sh" --redemarrer
echo "✓ Jarvis connaît maintenant vos devoirs. Demandez-lui : « Qu'est-ce que j'ai à rendre cette semaine ? »"
