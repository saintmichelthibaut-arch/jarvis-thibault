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
    "Incarne une intelligence artificielle majordome de film de super-héros : voix masculine grave, feutrée, "
    "extrêmement posée, avec une élégance très britannique transposée en français impeccable. Ton flegmatique, "
    "courtois, d'un calme absolu, pince-sans-rire : les traits d'humour sont dits avec un sérieux parfait, "
    "un très léger sourire dans la voix. Diction nette et précise, débit fluide, petites pauses élégantes. "
    "Légère froideur synthétique d'IA, jamais robotique, jamais enthousiaste."
)


def dossier_audio(cfg) -> Path:
    p = cfg.dossier / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


ELEVEN = "https://api.elevenlabs.io/v1"
GEORGE = "JBFqnCBsd6RMkjVDRZzb"  # voix « George » d'ElevenLabs (voix de base, offre gratuite)


def elevenlabs_tts(cle: str, voix_id: str, texte: str, sortie: Path, modele: str = "eleven_flash_v2_5",
                   reglages: Optional[dict] = None, transport=None, avec_langue: bool = True) -> Path:
    """Synthèse ElevenLabs → fichier mp3."""
    import httpx

    if not voix_id:
        raise ValueError("Aucune voix ElevenLabs choisie : lancez « jarvis-thibault elevenlabs »")
    corps = {"text": texte[:4500], "model_id": modele,
             "voice_settings": reglages or {"stability": .5, "similarity_boost": .8, "style": .25, "use_speaker_boost": True}}
    if avec_langue:
        corps["language_code"] = "fr"
    with httpx.Client(timeout=40, transport=transport) as c:
        r = c.post(f"{ELEVEN}/text-to-speech/{voix_id}", params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": cle, "accept": "audio/mpeg"}, json=corps)
    if r.status_code == 401:
        raise PermissionError("Clé ElevenLabs refusée (401) : vérifiez-la avec ajouter-cle.sh")
    if r.status_code in (400, 422) and avec_langue:
        return elevenlabs_tts(cle, voix_id, texte, sortie, modele, reglages, transport, avec_langue=False)
    r.raise_for_status()
    sortie.write_bytes(r.content)
    return sortie


def elevenlabs_voix(cle: str, transport=None) -> list:
    """Les voix de « Mes voix » sur ElevenLabs (celles ajoutées depuis la Voice Library)."""
    import httpx

    with httpx.Client(timeout=30, transport=transport) as c:
        r = c.get(f"{ELEVEN}/voices", headers={"xi-api-key": cle})
    if r.status_code == 401:
        raise PermissionError("Clé ElevenLabs refusée (401)")
    r.raise_for_status()
    return [{"id": v["voice_id"], "nom": v.get("name", "?"), "categorie": v.get("category", ""),
             "description": ((v.get("labels") or {}).get("description") or (v.get("labels") or {}).get("accent") or "")}
            for v in r.json().get("voices", [])]


def synthetiser(cfg, texte: str, nom: Optional[str] = None) -> Optional[Path]:
    """Transforme le texte en fichier audio. Renvoie None si la voix est désactivée."""
    v = cfg["voix"]
    fournisseur = v.get("fournisseur", "openai")
    if fournisseur == "aucune" or not texte.strip():
        return None
    # Clé ElevenLabs présente → George (ou la voix choisie) d'office, OpenAI en secours
    if fournisseur == "openai" and cfg.secret("elevenlabs_api_key") and v.get("auto_elevenlabs", True):
        fournisseur = "elevenlabs"
    voix_el = v.get("elevenlabs_voix") or GEORGE
    suffixe = f"-el-{voix_el[:6]}" if fournisseur == "elevenlabs" else ""
    nom = (nom or hashlib.sha1(f"{fournisseur}{v}{texte}".encode()).hexdigest()[:16]) + suffixe
    dossier = dossier_audio(cfg)

    if fournisseur == "elevenlabs":
        cle = cfg.secret("elevenlabs_api_key")
        if cle:
            sortie = dossier / f"{nom}.mp3"
            if sortie.exists() and sortie.stat().st_size > 1000:
                return sortie
            try:
                return elevenlabs_tts(cle, voix_el, texte, sortie, v.get("elevenlabs_modele") or "eleven_multilingual_v2",
                                      {"stability": .55, "similarity_boost": .8, "style": .3, "use_speaker_boost": True})
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.getLogger("jarvis.voix").warning("ElevenLabs indisponible (%s) : voix OpenAI en secours", exc)
        fournisseur = "openai"  # secours

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
