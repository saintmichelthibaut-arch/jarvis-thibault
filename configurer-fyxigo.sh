#!/bin/bash
# Configure Jarvis pour Fyxigo en une seule fois :
#   1. sauvegarde vos réglages actuels ;
#   2. met les 9 indicateurs de l'appli, le taux de commission et l'objectif ;
#   3. remplace les tâches d'exemple par les vraies priorités de Fyxigo ;
#   4. demande la clé Stripe et l'adresse de la base (facultatif, Annuler pour passer) ;
#   5. redémarre Jarvis.
set -euo pipefail
JH="${JARVIS_HOME:-$HOME/.jarvis}"
PY="$JH/app/.venv/bin/python"
EX="$JH/app/src/exemples/config.toml"
[[ -x "$PY" ]] || { echo "Jarvis n'est pas encore installé : lancez d'abord installer.sh"; exit 1; }
[[ -f "$EX" ]] || { echo "Mettez d'abord Jarvis à jour (mettre-a-jour.sh)."; exit 1; }
[[ -f "$JH/config.toml" ]] || cp "$EX" "$JH/config.toml"
[[ -f "$JH/secrets.toml" ]] || printf 'openai_api_key = ""\nstripe_api_key = ""\nbase_url = ""\n' > "$JH/secrets.toml"
chmod 600 "$JH/secrets.toml"

# ─── 1. Sauvegarde ──────────────────────────────────────────────────
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$JH/sauvegardes"
cp "$JH/config.toml" "$JH/sauvegardes/config-$STAMP.toml"
TACHES="$JH/fyxigo.md"
[[ ! -f "$TACHES" && -f "$JH/fixigo.md" ]] && TACHES="$JH/fixigo.md"
[[ -f "$TACHES" ]] && cp "$TACHES" "$JH/sauvegardes/$(basename "$TACHES" .md)-$STAMP.md"
echo "✓ Réglages sauvegardés dans $JH/sauvegardes"

# ─── 2. Indicateurs, commission, objectif ───────────────────────────
CFG="$JH/config.toml" EX="$EX" "$PY" -I - <<'EOF'
import os, re
p = os.environ["CFG"]
s = open(p, encoding="utf-8").read()
ex = open(os.environ["EX"], encoding="utf-8").read()

# Retire l'ancien bloc d'indicateurs ([fixigo.base] ou [fyxigo.base] et ses [[…indicateurs]])
base = re.compile(r"^\[\[?f[iy]xigo\.base(\.indicateurs)?\]\]?\s*$")
garde, saute = [], False
for ligne in s.splitlines():
    if ligne.startswith("["):
        saute = bool(base.match(ligne))
    if not saute:
        garde.append(ligne)
s = "\n".join(garde).rstrip("\n") + "\n"

# Taux de commission et objectif dans la section [fyxigo] (ou l'ancienne [fixigo])
def put(cle, val):
    global s
    bloc = re.search(r"(?ms)^\[f[iy]xigo\]\n(.*?)(?=^\[|\Z)", s)
    if not bloc:
        s = s.rstrip("\n") + "\n\n[fyxigo]\n"
        bloc = re.search(r"(?ms)^\[fyxigo\]\n(.*?)(?=^\[|\Z)", s)
    corps = bloc.group(1)
    if re.search(rf"(?m)^{cle}\s*=", corps):
        if cle == "objectif_commission_mois" and not re.search(rf"(?m)^{cle}\s*=\s*0\s*(#.*)?$", corps):
            return  # objectif déjà choisi : on n'y touche pas
        corps = re.sub(rf"(?m)^{cle}\s*=.*$", f"{cle} = {val}", corps, count=1)
    else:
        corps = f"{cle} = {val}\n" + corps
    s = s[:bloc.start(1)] + corps + s[bloc.end(1):]
put("taux_commission", "0.30")
put("objectif_commission_mois", "3000")

# Nouveau bloc d'indicateurs, repris de l'exemple livré avec Jarvis
m = re.search(r"(?ms)^\[fyxigo\.base\]\n.*?(?=^\[(?!\[?fyxigo\.base)|\Z)", ex)
s = s.rstrip("\n") + "\n\n" + m.group(0).rstrip("\n") + "\n"
open(p, "w", encoding="utf-8").write(s)
EOF
echo "✓ 9 indicateurs de l'appli, commission de 30 % et objectif de 3 000 €/mois"

# ─── 3. Vraies priorités (seulement si le fichier ne contient que les exemples) ─
if [[ ! -f "$TACHES" ]] || ! grep -q "^- \[ \]" "$TACHES" || ! grep "^- \[ \]" "$TACHES" | grep -qv "Exemple"; then
  cat > "$TACHES" <<'EOF'
# Objectifs
- 3 000 € de commission Fyxigo par mois
- 3 artisans vérifiés par métier sur la zone de lancement

# À faire
<!-- « ! » à « !!! » = priorité, « @AAAA-MM-JJ » = échéance -->
- [ ] !!! Corriger la base : les commandes de chauffagiste sont refusées
- [ ] !!! Faire pointer fyxigo.fr vers Vercel (2 enregistrements A vers 76.76.21.21 chez Hostinger)
- [ ] !! Recruter 2 plombiers et 2 chauffagistes vérifiés (1 seul de chaque aujourd'hui)
- [ ] !! Désigner le médiateur de la consommation
- [ ] !! Souscrire la RC professionnelle de la plateforme
- [ ] !! Passer Stripe en clés live (clés + webhook)
- [ ] ! Mettre main comme branche de production sur Vercel
- [ ] ! Créer la fiche Google Business Profile
- [ ] Préparer les fiches App Store et Google Play
EOF
  echo "✓ Vraies priorités Fyxigo écrites dans $TACHES"
else
  echo "• Vos tâches ne sont pas des exemples : je n'y touche pas ($TACHES)"
fi

# ─── 4. Clés (facultatif) ───────────────────────────────────────────
demander() {  # $1 = message
  if [[ "$(uname)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
    osascript -e "text returned of (display dialog \"$1\" default answer \"\" with hidden answer with title \"Jarvis\" buttons {\"Passer\", \"Enregistrer\"} default button \"Enregistrer\" cancel button \"Passer\")" 2>/dev/null || true
  elif [[ -t 0 ]]; then
    local v; read -r -s -p "$1 (Entrée pour passer) : " v; echo >&2; printf '%s' "$v"
  fi
}
K_STRIPE=$(demander "Clé Stripe restreinte de Jarvis (rk_test_… ou rk_live_…). Collez-la (Cmd + V) :")
K_BASE=$(demander "Adresse de la base Supabase (postgresql://…). Collez-la, ou Passer :")
K_STRIPE="$K_STRIPE" K_BASE="$K_BASE" SEC="$JH/secrets.toml" CFG="$JH/config.toml" "$PY" -I - <<'EOF'
import os, re
p = os.environ["SEC"]; s = open(p, encoding="utf-8").read()
for cle, env in (("stripe_api_key", "K_STRIPE"), ("base_url", "K_BASE")):
    v = os.environ[env].strip()
    if not v:
        continue
    ligne = f'{cle} = "' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if re.search(rf"(?m)^{cle}\s*=", s):
        s = re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: ligne, s, count=1)
    else:
        s = s.rstrip("\n") + "\n" + ligne + "\n"
open(p, "w", encoding="utf-8").write(s)
# La base n'est lue que si une adresse est connue
if re.search(r'(?m)^base_url\s*=\s*"[^"]+"', s):
    c = open(os.environ["CFG"], encoding="utf-8").read()
    c = re.sub(r"(?ms)(^\[fyxigo\.base\]\n.*?^active\s*=\s*)false", r"\1true", c, count=1)
    open(os.environ["CFG"], "w", encoding="utf-8").write(c)
EOF
[[ -n "$K_STRIPE" ]] && echo "✓ Clé Stripe enregistrée" || echo "• Clé Stripe : passée"
[[ -n "$K_BASE" ]] && echo "✓ Base Fyxigo enregistrée" || echo "• Base Fyxigo : passée"
unset K_STRIPE K_BASE

# ─── 5. Redémarrage ─────────────────────────────────────────────────
"$JH/app/.venv/bin/jarvis-thibault" verifier >/dev/null 2>&1 || true
if [[ -x "$JH/app/lancer.sh" ]]; then
  pkill -f "jarvis-thibault serveur" 2>/dev/null; pkill -f "jarvis_thibault.cli serveur" 2>/dev/null; true
  sleep 1
  bash "$JH/app/lancer.sh" --silencieux || true
fi
echo
echo "✓ Terminé. Jarvis redémarre avec les chiffres de Fyxigo."
echo "  En cas de souci, vos anciens réglages sont dans $JH/sauvegardes"
