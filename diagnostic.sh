#!/bin/bash
# Diagnostic complet de Jarvis : copiez tout ce qui s'affiche et envoyez-le.
JH="${JARVIS_HOME:-$HOME/.jarvis}"
URL="http://127.0.0.1:8765"
echo "── Jarvis · diagnostic ──"
echo "Version installée : $(cat "$JH/app/version" 2>/dev/null || echo ?)"
echo "Version en cours  : $(curl -s -m 2 $URL/api/version || echo 'AUCUN JARVIS EN COURS')"
echo "Veille automatique: $(launchctl list 2>/dev/null | grep -q com.thibault.jarvis.veille && echo active || echo INACTIVE)"
echo "Nombre de Jarvis  : $(pgrep -f 'jarvis(-thibault|_thibault.cli) serveur' | wc -l | tr -d ' ')"
echo "Micro (Jarvis)    : $(curl -s -m 2 $URL/api/etat | python3 -c 'import json,sys;m=json.load(sys.stdin).get("micro");print({True:"ok",False:"BLOQUÉ",None:"inconnu"}[m])' 2>/dev/null || echo ?)"
echo "App               : $(head -2 "$HOME/Applications/Jarvis.app/Contents/MacOS/Jarvis" 2>/dev/null | tail -1)"
echo ""
echo "── Derniers messages ──"
grep -E "Micro|laquement|Bruit fort|Réveil|Erreur|Error|Traceback|refusée|Écoute :|Entendu" "$JH/jarvis.log" 2>/dev/null | tail -12
echo ""
echo "── Test : faites clap-clap MAINTENANT (10 s) ──"
L0=$(wc -l < "$JH/jarvis.log" 2>/dev/null || echo 0)
sleep 10
tail -n +$((L0+1)) "$JH/jarvis.log" 2>/dev/null | grep -E "laquement|Bruit fort|Micro" || echo "(aucun claquement entendu pendant le test)"
