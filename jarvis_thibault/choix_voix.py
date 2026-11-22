"""Fait écouter plusieurs voix de majordome et enregistre celle que vous choisissez."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess

from .config import DOSSIER, charger

VOIX = [
    ("onyx", "grave et posée"),
    ("ash", "nette et assurée"),
    ("echo", "calme et douce"),
    ("fable", "élégante, un peu théâtrale"),
    ("ballad", "chaleureuse"),
    ("verse", "vive et expressive"),
]


def choisir() -> int:
    from . import voix

    cfg = charger()
    appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
    if not cfg.secret("openai_api_key"):
        print("Il faut d'abord la clé OpenAI (bash ~/jarvis-thibault-main/ajouter-cle.sh).")
        return 1
    for i, (v, desc) in enumerate(VOIX, 1):
        cfg.data["voix"]["voix"] = v
        print(f"  {i}) {v} — {desc}")
        f = voix.synthetiser(cfg, f"Voix numéro {i}. Bonsoir {appel}. Tous les systèmes sont opérationnels, "
                                  f"et votre café, je le crains, refroidit.", nom=f"essai-voix-{v}-v2")
        if f and platform.system() == "Darwin" and shutil.which("afplay"):
            subprocess.run(["afplay", str(f)])
    if platform.system() == "Darwin" and shutil.which("osascript"):
        liste = ", ".join(f'"{i} — {v} ({d})"' for i, (v, d) in enumerate(VOIX, 1))
        r = subprocess.run(["osascript", "-e", f'choose from list {{{liste}}} with title "Jarvis · voix" '
                            f'with prompt "Quelle voix pour Jarvis ?"'], capture_output=True, text=True)
        rep = r.stdout.strip()
        if not rep or rep == "false":
            print("Annulé.")
            return 0
        n = int(rep.split(" ")[0])
    else:
        n = int(input("Votre choix (1-6) : ").strip() or "1")
    choix = VOIX[n - 1][0]
    conf = DOSSIER / "config.toml"
    s = conf.read_text(encoding="utf-8")
    s = re.sub(r'(?m)^(voix\s*=\s*)"[^"]*"', rf'\1"{choix}"', s, count=1)
    conf.write_text(s, encoding="utf-8")
    print(f"✓ Jarvis parlera désormais avec la voix « {choix} ».")
    return 0
