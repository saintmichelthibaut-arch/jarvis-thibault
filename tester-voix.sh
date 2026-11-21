#!/bin/bash
# Teste la voix de Jarvis et la joue sur le Mac. N'affiche jamais la clé.
JH="${JARVIS_HOME:-$HOME/.jarvis}"
"$JH/app/.venv/bin/python" -I - <<'PY'
from jarvis_thibault.config import charger
from jarvis_thibault import voix
c = charger()
print("Clé OpenAI   :", "présente" if c.secret("openai_api_key") else "ABSENTE  →  bash ~/jarvis-thibault-main/ajouter-cle.sh")
print("Voix choisie :", c["voix"]["fournisseur"], "·", c["voix"]["modele"], "·", c["voix"]["voix"])
try:
    f = voix.synthetiser(c, "Bonjour Monsieur. Ceci est un test de ma nouvelle voix.")
    print("Fichier      :", f)
    print("Résultat     :", "voix OpenAI réaliste ✓" if f and f.suffix == ".mp3" else "voix du Mac (robotique)")
    if f:
        import subprocess; subprocess.run(["afplay", str(f)])
except Exception as e:
    print("ERREUR voix  :", type(e).__name__, str(e)[:400])
PY
