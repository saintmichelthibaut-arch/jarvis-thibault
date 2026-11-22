"""La voix de Jarvis : OpenAI (réaliste) ou voix du Mac (gratuite)."""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from openai import OpenAI


CONSIGNES_JARVIS = (
    "Tu es JARVIS, intelligence artificielle et majordome numérique. Français de France, voix masculine grave, "
    "posée et parfaitement maîtrisée, diction impeccable et précise. Ton flegmatique, courtois, légèrement "
    "pince-sans-rire, d'un raffinement très britannique. Débit fluide et rapide mais jamais pressé. "
    "Une légère froideur d'intelligence artificielle, jamais robotique."
)


def dossier_audio(cfg) -> Path:
    p = cfg.dossier / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def synthetiser(cfg, texte: str, nom: Optional[str] = None) -> Optional[Path]:
    """Transforme le texte en fichier audio. Renvoie None si la voix est désactivée."""
    v = cfg["voix"]
    fournisseur = v.get("fournisseur", "openai")
    if fournisseur == "aucune" or not texte.strip():
        return None
    nom = nom or hashlib.sha1(f"{fournisseur}{v}{texte}".encode()).hexdigest()[:16]
    dossier = dossier_audio(cfg)

    if fournisseur == "openai":
        cle = cfg.secret("openai_api_key")
        if cle:
            sortie = dossier / f"{nom}.mp3"
            if sortie.exists() and sortie.stat().st_size > 1000:
                return sortie  # déjà prononcé : instantané
            args = dict(model=v.get("modele", "gpt-4o-mini-tts"), voice=v.get("voix", "onyx"),
                        input=texte[:4000], response_format="mp3")
            if "tts-1" not in args["model"]:
                if v.get("style", "jarvis") == "jarvis":
                    args["instructions"] = CONSIGNES_JARVIS
                elif v.get("consignes"):
                    args["instructions"] = v["consignes"]
            with OpenAI(api_key=cle).audio.speech.with_streaming_response.create(**args) as r:
                r.stream_to_file(sortie)
            return sortie
        fournisseur = "mac"  # pas de clé : on se rabat sur la voix du Mac

    if fournisseur == "mac" and platform.system() == "Darwin" and shutil.which("say"):
        aiff = dossier / f"{nom}.aiff"
        sortie = dossier / f"{nom}.m4a"
        subprocess.run(["say", "-v", v.get("voix_mac", "Thomas"), "-o", str(aiff), texte], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(sortie)], check=True)
        aiff.unlink(missing_ok=True)
        return sortie
    return None


def jouer(fichier: Path, attendre: bool = False) -> None:
    """Joue un fichier audio sur les haut-parleurs du Mac (sans navigateur)."""
    if platform.system() == "Darwin" and shutil.which("afplay"):
        (subprocess.run if attendre else subprocess.Popen)(["afplay", str(fichier)])


def notifier(titre: str, message: str) -> None:
    if platform.system() == "Darwin":
        msg = message.replace('"', "'")[:200]
        subprocess.Popen(["osascript", "-e",
                          f'display notification "{msg}" with title "{titre}" sound name "Glass"'])


def nettoyer(cfg, garder: int = 200) -> None:
    fichiers = sorted(dossier_audio(cfg).iterdir(), key=lambda p: p.stat().st_mtime)
    for f in fichiers[:-garder]:
        f.unlink(missing_ok=True)
