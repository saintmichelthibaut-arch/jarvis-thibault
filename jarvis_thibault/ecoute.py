"""Écoute par le micro du Mac, côté Jarvis (pas par la fenêtre) : enregistre une phrase
jusqu'au silence, puis la transcrit en texte (OpenAI)."""

from __future__ import annotations

import io
import logging
import math
import threading
import time
import wave
from typing import Callable, Optional

log = logging.getLogger("jarvis.ecoute")
TAUX = 16000
BLOC = 480  # 30 ms
VERROU = threading.Lock()
niveau_actuel = {"v": 0.0}


def enregistrer_phrase(attente_max: float = 7.0, silence_fin: float = 0.9, duree_max: float = 15.0,
                       sur_niveau: Optional[Callable[[float], None]] = None) -> Optional[bytes]:
    """Renvoie un WAV (bytes) de la phrase prononcée, ou None si personne n'a parlé."""
    import sounddevice as sd

    with VERROU:
        trames, parle, silence, debut = [], False, 0.0, time.monotonic()
        bruit = 0.006
        with sd.InputStream(samplerate=TAUX, channels=1, blocksize=BLOC, dtype="int16") as flux:
            while True:
                donnees, _ = flux.read(BLOC)
                b = donnees[:, 0]
                rms = math.sqrt(sum((int(x) / 32768) ** 2 for x in b) / len(b))
                niveau_actuel["v"] = rms
                if sur_niveau:
                    sur_niveau(rms)
                seuil = max(0.012, bruit * 3.5)
                ecoule = time.monotonic() - debut
                if not parle:
                    trames = (trames + [bytes(b)])[-10:]  # garde 300 ms avant le début de la parole
                    if rms > seuil:
                        parle = True
                    else:
                        bruit = 0.95 * bruit + 0.05 * rms
                        if ecoule > attente_max:
                            return None
                    continue
                trames.append(bytes(b))
                silence = silence + BLOC / TAUX if rms < seuil else 0.0
                if silence >= silence_fin or ecoule > duree_max:
                    break
    niveau_actuel["v"] = 0.0
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAUX)
        w.writeframes(b"".join(trames))
    return tampon.getvalue()


def transcrire(cfg, wav: bytes) -> str:
    from openai import OpenAI

    cle = cfg.secret("openai_api_key")
    if not cle:
        raise ValueError("La reconnaissance vocale a besoin d'une clé OpenAI (ajouter-cle.sh).")
    client = OpenAI(api_key=cle)
    erreur: Exception = ValueError("transcription impossible")
    for modele in (cfg["ecoute"].get("transcription") or "gpt-4o-mini-transcribe", "whisper-1"):
        try:
            r = client.audio.transcriptions.create(model=modele, file=("voix.wav", wav), language="fr")
            return (r.text or "").strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("Transcription (%s) : %s", modele, exc)
            erreur = exc
    raise erreur


def ecouter_commande(cfg) -> str:
    wav = enregistrer_phrase()
    if not wav:
        return ""
    return transcrire(cfg, wav)
