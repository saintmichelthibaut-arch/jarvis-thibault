#!/bin/bash
# Ajoute ou remplace une clé (OpenAI, Stripe, base Fyxigo) sans toucher au reste.
set -euo pipefail
JH="${JARVIS_HOME:-$HOME/.jarvis}"
SEC="$JH/secrets.toml"
PY="$JH/app/.venv/bin/python"
[[ -x "$PY" ]] || { echo "Jarvis n'est pas encore installé."; exit 1; }
[[ -f "$SEC" ]] || { printf 'openai_api_key = ""\nstripe_api_key = ""\nbase_url = ""\n' > "$SEC"; }
chmod 600 "$SEC"

if [[ "$(uname)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
  # Petites fenêtres du Mac : marche même lancé depuis Claude Code (« ! bash … »)
  CHOIX=$(osascript -e 'choose from list {"OpenAI (sk-…)", "Stripe (rk_live_…)", "Base Fyxigo (postgresql://…)"} with title "Jarvis" with prompt "Quelle clé voulez-vous ajouter ?" default items {"OpenAI (sk-…)"}' 2>/dev/null || echo false)
  case "$CHOIX" in
    OpenAI*) CLE=openai_api_key ;;
    Stripe*) CLE=stripe_api_key ;;
    Base*) CLE=base_url ;;
    *) echo "Annulé, rien n'a changé."; exit 0 ;;
  esac
  VAL=$(osascript -e 'text returned of (display dialog "Collez la clé ici (Cmd + V), puis Enregistrer :" default answer "" with hidden answer with title "Jarvis" buttons {"Annuler", "Enregistrer"} default button "Enregistrer" cancel button "Annuler")' 2>/dev/null || true)
else
  echo "Quelle clé voulez-vous ajouter ?"
  echo "  1) OpenAI (sk-…)"
  echo "  2) Stripe restreinte (rk_live_…)"
  echo "  3) Adresse de la base Fyxigo (postgresql://…)"
  read -r -p "Votre choix : " CHOIX
  case "$CHOIX" in
    1) CLE=openai_api_key ;;
    2) CLE=stripe_api_key ;;
    3) CLE=base_url ;;
    *) echo "Choix inconnu."; exit 1 ;;
  esac
  read -r -s -p "Collez-la puis Entrée (rien ne s'affiche, c'est normal) : " VAL; echo
fi
[[ -n "$VAL" ]] || { echo "Rien n'a été collé, rien n'a changé."; exit 1; }

CLE="$CLE" VAL="$VAL" SEC="$SEC" CFG="$JH/config.toml" "$PY" -I - <<'EOF'
import os, re
p, cle, val = os.environ["SEC"], os.environ["CLE"], os.environ["VAL"].strip()
s = open(p, encoding="utf-8").read()
ligne = f'{cle} = "' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'
if re.search(rf"(?m)^{cle}\s*=", s):
    s = re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: ligne, s, count=1)
else:
    s = s.rstrip("\n") + "\n" + ligne + "\n"
open(p, "w", encoding="utf-8").write(s)
if cle == "base_url":
    c = open(os.environ["CFG"], encoding="utf-8").read()
    c = re.sub(r"(?ms)(^\[f[iy]xigo\.base\]\n.*?^active\s*=\s*)false", r"\1true", c, count=1)
    open(os.environ["CFG"], "w", encoding="utf-8").write(c)
EOF
unset VAL
echo "✓ Clé enregistrée. Redémarrage de Jarvis…"
pkill -f "jarvis-thibault serveur" 2>/dev/null; pkill -f "jarvis_thibault.cli serveur" 2>/dev/null; true
sleep 1
bash "$JH/app/lancer.sh" --silencieux
"$JH/app/.venv/bin/jarvis-thibault" verifier 2>&1 | head -6
