"""Choisir la voix ElevenLabs de Jarvis parmi « Mes voix » (ajoutées depuis la Voice Library)."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess

from .config import DOSSIER, charger


def _ecrire(conf, cle: str, valeur: str) -> None:
    s = conf.read_text(encoding="utf-8")
    bloc = re.search(r"(?ms)^\[voix\]\n(.*?)(?=^\[|\Z)", s)
    ligne = f'{cle} = "{valeur}"'
    if not bloc:
        s = s.rstrip("\n") + f"\n\n[voix]\n{ligne}\n"
    elif re.search(rf"(?m)^{cle}\s*=", bloc.group(1)):
        s = s[:bloc.start(1)] + re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: ligne, bloc.group(1), count=1) + s[bloc.end(1):]
    else:
        s = s[:bloc.start(1)] + ligne + "\n" + s[bloc.start(1):]
    conf.write_text(s, encoding="utf-8")


def choisir() -> int:
    from . import voix

    cfg = charger()
    cle = cfg.secret("elevenlabs_api_key")
    if not cle:
        print("Ajoutez d'abord la clé ElevenLabs : bash ~/jarvis-thibault-main/ajouter-cle.sh (choix « ElevenLabs »)")
        return 1
    liste = voix.elevenlabs_voix(cle)
    if not liste:
        print("Aucune voix dans « Mes voix ». Sur elevenlabs.io → Voice Library, cliquez « Add to my voices » sur celles qui vous plaisent.")
        return 1
    # les voix ajoutées par vous d'abord
    liste.sort(key=lambda v: v["categorie"] == "premade")
    appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
    mac = platform.system() == "Darwin" and shutil.which("osascript")
    if mac:
        items = ", ".join('"' + f'{i} — {v["nom"]}' .replace('"', "'") + '"' for i, v in enumerate(liste[:40], 1))
        r = subprocess.run(["osascript", "-e", f'choose from list {{{items}}} with title "Jarvis · ElevenLabs" '
                            'with prompt "Quelle voix pour Jarvis ? (je vous la fais écouter)"'], capture_output=True, text=True)
        rep = r.stdout.strip()
        if not rep or rep == "false":
            print("Annulé.")
            return 0
        n = int(rep.split(" ")[0])
    else:
        for i, v in enumerate(liste[:40], 1):
            print(f"  {i}) {v['nom']}  {v['description']}")
        n = int(input("Votre choix : ").strip() or "1")
    choisie = liste[n - 1]
    conf = DOSSIER / "config.toml"
    _ecrire(conf, "fournisseur", "elevenlabs")
    _ecrire(conf, "elevenlabs_voix", choisie["id"])
    cfg = charger()
    f = voix.synthetiser(cfg, f"Bonsoir {appel}. Tous les systèmes sont opérationnels. Je suis à votre service.",
                         nom=f"essai-eleven-{choisie['id']}")
    if f and platform.system() == "Darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", str(f)])
    print(f"✓ Jarvis parle maintenant avec la voix ElevenLabs « {choisie['nom']} ».")
    print("  Pour en changer : relancez cette commande. Pour revenir à OpenAI : fournisseur = \"openai\" dans [voix].")
    return 0
