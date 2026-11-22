#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  Installation de JARVIS pour Thibault — macOS
#  Usage : ouvrez Terminal, glissez ce fichier dedans, appuyez sur Entrée.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

ICI="$(cd "$(dirname "$0")" && pwd)"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
APP="$HOME/Applications/Jarvis.app"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

bleu() { printf "\033[1;36m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
info() { printf "  \033[33m•\033[0m %s\n" "$*"; }

[[ "$(uname)" == "Darwin" ]] || { echo "Ce script est prévu pour macOS."; exit 1; }

bleu "
     ╦╔═╗╦═╗╦  ╦╦╔═╗
     ║╠═╣╠╦╝╚╗╔╝║╚═╗     Installation de votre assistant personnel
    ╚╝╩ ╩╩╚═ ╚╝ ╩╚═╝     Bonjour Monsieur. Je m'installe, ce ne sera pas long.
"

# ─── 1. OpenJarvis + Ollama ─────────────────────────────────────────
bleu "1/7  OpenJarvis et Ollama (le moteur d'IA local)"
if [[ -x "$HOME/.openjarvis/.venv/bin/jarvis" ]] || command -v jarvis >/dev/null 2>&1; then
  ok "OpenJarvis déjà installé"
else
  curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash -s -- --minimal || \
    info "L'installateur OpenJarvis a signalé un souci — on continue."
fi
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install ollama
  else
    echo "  Ollama est introuvable. Téléchargez-le sur https://ollama.com/download puis relancez ce script."
    exit 1
  fi
fi
pgrep -x ollama >/dev/null 2>&1 || (open -a Ollama 2>/dev/null || nohup ollama serve >/dev/null 2>&1 &)
ok "Ollama prêt"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# ─── 2. L'application Jarvis ────────────────────────────────────────
bleu "2/7  Installation de Jarvis"
mkdir -p "$JH/app"
rsync -a --delete --exclude ".venv" --exclude "__pycache__" --exclude "tests" "$ICI/" "$JH/app/src/"
uv venv -q --allow-existing --python 3.12 "$JH/app/.venv"
uv pip install -q -p "$JH/app/.venv" "$JH/app/src"
PY="$JH/app/.venv/bin/python"
ok "Jarvis installé dans $JH"

# ─── 3. Réglages ────────────────────────────────────────────────────
bleu "3/7  Vos réglages"
[[ -f "$JH/config.toml" ]] || cp "$ICI/exemples/config.toml" "$JH/config.toml"
[[ -f "$JH/fixigo.md" ]]   || cp "$ICI/exemples/fixigo.md" "$JH/fixigo.md"
RAM=$(( $(sysctl -n hw.memsize) / 1073741824 ))
MODELE="qwen3.5:9b"; (( RAM < 16 )) && MODELE="qwen3.5:4b"

read -r -p "  Votre ville pour la météo [Paris] : " VILLE; VILLE="${VILLE:-Paris}"
read -r -p "  Heure du briefing du matin [07:00] : " HEURE; HEURE="${HEURE:-07:00}"
read -r -p "  Objectif de MRR Fixigo en € [5000] : " OBJ; OBJ="${OBJ:-5000}"
echo
echo "  Le « cerveau » de Jarvis :"
echo "    1) Sur ce Mac ($MODELE) — gratuit, vos chiffres ne quittent pas le Mac"
echo "    2) OpenAI — plus fin et plus drôle, quelques centimes par jour"
read -r -p "  Votre choix [1] : " CERV; CERV="${CERV:-1}"

VILLE="$VILLE" HEURE="$HEURE" OBJ="$OBJ" CERV="$CERV" MODELE="$MODELE" CFG="$JH/config.toml" "$PY" -I - <<'EOF'
import os, re
p = os.environ["CFG"]; s = open(p, encoding="utf-8").read()
def put(cle, val, section):
    global s
    bloc = re.search(rf"(?ms)^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)", s)
    corps = re.sub(rf"(?m)^{cle}\s*=.*$", f"{cle} = {val}", bloc.group(1), count=1)
    s = s[:bloc.start(1)] + corps + s[bloc.end(1):]
q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
put("ville", q(os.environ["VILLE"]), "moi")
put("heure", q(os.environ["HEURE"]), "briefing")
put("objectif_mrr", str(int(float(os.environ["OBJ"] or 0))), "fixigo")
if os.environ["CERV"] == "2":
    put("fournisseur", q("openai"), "cerveau"); put("modele", q("gpt-4.1-mini"), "cerveau")
else:
    put("fournisseur", q("ollama"), "cerveau"); put("modele", q(os.environ["MODELE"]), "cerveau")
open(p, "w", encoding="utf-8").write(s)
EOF
ok "Réglages enregistrés dans $JH/config.toml"

# ─── 4. Clés secrètes ───────────────────────────────────────────────
bleu "4/7  Vos clés (rien ne s'affiche quand vous collez : c'est normal)"
[[ -f "$JH/secrets.toml" ]] || { cp "$ICI/exemples/secrets.toml" "$JH/secrets.toml"; }
chmod 600 "$JH/secrets.toml"
read -r -s -p "  Clé OpenAI (sk-…), Entrée pour passer : " K_OPENAI; echo
read -r -s -p "  Clé Stripe restreinte (rk_live_…), Entrée pour passer : " K_STRIPE; echo
read -r -s -p "  Adresse de la base Fixigo (postgresql://…), Entrée pour passer : " K_BASE; echo
K_OPENAI="$K_OPENAI" K_STRIPE="$K_STRIPE" K_BASE="$K_BASE" SEC="$JH/secrets.toml" CFG="$JH/config.toml" "$PY" -I - <<'EOF'
import os, re
p = os.environ["SEC"]; s = open(p, encoding="utf-8").read()
q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
for cle, env in (("openai_api_key", "K_OPENAI"), ("stripe_api_key", "K_STRIPE"), ("base_url", "K_BASE")):
    v = os.environ[env].strip()
    if v:
        s = re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: f"{cle} = {q(v)}", s, count=1)
open(p, "w", encoding="utf-8").write(s)
if os.environ["K_BASE"].strip():
    c = open(os.environ["CFG"], encoding="utf-8").read()
    c = re.sub(r"(?ms)(^\[fixigo\.base\]\n.*?^active\s*=\s*)false", r"\1true", c, count=1)
    open(os.environ["CFG"], "w", encoding="utf-8").write(c)
EOF
unset K_OPENAI K_STRIPE K_BASE
ok "Clés rangées dans $JH/secrets.toml (accès réservé à vous)"

# ─── 5. Modèle local ────────────────────────────────────────────────
bleu "5/7  Téléchargement du cerveau local"
if [[ "$CERV" != "2" ]]; then
  for i in 1 2 3 4 5 6 7 8 9 10; do ollama list >/dev/null 2>&1 && break; sleep 2; done
  ollama pull "$MODELE" && ok "Modèle $MODELE prêt"
else
  ok "Cerveau OpenAI : rien à télécharger"
fi

# ─── 6. L'app « Jarvis » + démarrage automatique ────────────────────
bleu "6/7  Création de l'app Jarvis"
bash "$ICI/installer-veille.sh"
ok "App créée : $APP"

# ─── 7. Vérification ────────────────────────────────────────────────
bleu "7/7  Vérification"
"$JH/app/.venv/bin/jarvis-thibault" verifier 2>&1 | head -12 || true

bleu "
════════════════════════════════════════════════════════════════════
  PRESQUE FINI — 2 réglages à faire à la main (2 minutes) :

  1) ACCÈS À L'AGENDA
     Réglages Système → Confidentialité et sécurité → Accès complet au disque
     → bouton « + » → Applications (dans votre dossier perso) → Jarvis → Ouvrir
     (et activez l'interrupteur)

  2) OUTLOOK DANS L'AGENDA DU MAC
     Réglages Système → Comptes Internet → Ajouter un compte → Microsoft Exchange
     (ou Outlook.com) → cochez « Calendriers »

  Ensuite : ouvrez l'app « Jarvis » (dossier Applications de votre dossier perso).
  Vos tâches Fixigo : $JH/fixigo.md
════════════════════════════════════════════════════════════════════
"
open "$HOME/Applications" 2>/dev/null || true
