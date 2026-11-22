#!/bin/bash
# Répare Jarvis : arrête tout, relance la bonne version via l'app, vérifie micro et clap-clap.
JH="${JARVIS_HOME:-$HOME/.jarvis}"
ICI="$(cd "$(dirname "$0")" && pwd)"
echo "Réparation de Jarvis…"
bash "$ICI/installer-veille.sh" >/dev/null
echo "Vérification du micro (10 s, ne parlez pas)…"
sleep 11
L=$(grep -E "Micro : |claquement" "$JH/jarvis.log" | tail -3)
echo "$L"
if echo "$L" | tail -1 | grep -q "SILENCE"; then
  echo ""
  echo "✗ macOS bloque le micro pour Jarvis. Dans la fenêtre qui s'ouvre : activez « Jarvis » (et Terminal),"
  echo "  puis relancez :  bash ~/jarvis-thibault-main/reparer.sh"
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone" 2>/dev/null
elif echo "$L" | grep -q "Micro : OK"; then
  echo "✓ Micro OK. Fermez la fenêtre de Jarvis et faites clap-clap."
else
  echo "? Pas encore d'info sur le micro : si macOS vous demande l'accès au micro pour « Jarvis », acceptez, puis relancez ce script."
fi
