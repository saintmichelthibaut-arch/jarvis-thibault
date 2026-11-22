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
ANNULER = threading.Event()


def _rms(b) -> float:
    try:
        import numpy as np

        x = b.astype("float32") / 32768.0
        return float(np.sqrt(np.mean(x * x)))
    except Exception:  # noqa: BLE001
        return math.sqrt(sum((int(v) / 32768) ** 2 for v in b) / len(b))


def enregistrer_phrase(attente_max: float = 8.0, silence_fin: float = 1.0, duree_max: float = 15.0,
                       sur_niveau: Optional[Callable[[float], None]] = None, journal: Optional[dict] = None,
                       interruption: bool = False, sur_debut: Optional[Callable[[], None]] = None,
                       sensibilite: float = 1.0) -> Optional[bytes]:
    """Renvoie un WAV (bytes) de la phrase prononcée, ou None si personne n'a parlé.
    Le seuil s'adapte au bruit de la pièce (mesuré pendant les 0,3 premières secondes)."""
    import sounddevice as sd

    from collections import deque

    j = journal if journal is not None else {}
    with VERROU:
        ANNULER.clear()
        trames, parle, silence, debut = [], False, 0.0, time.monotonic()
        calib, bruit, maxi = [], 0.0, 0.0
        echo, fort = deque(maxlen=50), 0  # mode interruption : niveau de la voix de Jarvis captée par le micro
        with sd.InputStream(samplerate=TAUX, channels=1, blocksize=BLOC, dtype="int16") as flux:
            while True:
                donnees, _ = flux.read(BLOC)
                b = donnees[:, 0]
                rms = _rms(b)
                maxi = max(maxi, rms)
                niveau_actuel["v"] = rms
                if sur_niveau:
                    sur_niveau(rms)
                ecoule = time.monotonic() - debut
                if ANNULER.is_set():
                    j.update(annule=True, maxi=maxi, parle=parle)
                    niveau_actuel["v"] = 0.0
                    return None
                if interruption and not parle:
                    # Jarvis parle : on ne déclenche que si une voix dépasse nettement son propre écho
                    echo.append(rms)
                    ref = sorted(echo)[int(len(echo) * .9)] if len(echo) >= 10 else 1.0
                    seuil_i = max(0.03 / max(.3, sensibilite), ref * 2.3 / max(.3, sensibilite))
                    trames = (trames + [bytes(b)])[-12:]
                    fort = fort + 1 if rms > seuil_i else 0
                    if fort >= 7:  # ~210 ms de voix forte
                        parle, bruit = True, ref
                        if sur_debut:
                            sur_debut()
                    elif ecoule > attente_max:
                        j.update(maxi=maxi, parle=False)
                        return None
                    continue
                if len(calib) < 10:  # 0,3 s de calibrage
                    calib.append(rms)
                    trames.append(bytes(b))
                    bruit = sorted(calib)[len(calib) // 2]
                    continue
                seuil = max(0.0025, bruit * 2.2)
                if interruption:
                    seuil = max(seuil, bruit * 1.2)
                if not parle:
                    trames = (trames + [bytes(b)])[-12:]  # garde 360 ms avant le début de la parole
                    if rms > seuil:
                        parle = True
                        if sur_debut:
                            sur_debut()
                    else:
                        bruit = 0.97 * bruit + 0.03 * rms
                        if ecoule > attente_max:
                            j.update(bruit=bruit, maxi=maxi, seuil=seuil, parle=False)
                            niveau_actuel["v"] = 0.0
                            return None
                    continue
                trames.append(bytes(b))
                silence = silence + BLOC / TAUX if rms < seuil * 0.8 else 0.0
                if silence >= silence_fin or ecoule > duree_max:
                    break
    j.update(bruit=bruit, maxi=maxi, seuil=seuil, parle=True)
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
    j: dict = {}
    wav = enregistrer_phrase(journal=j)
    log.info("Écoute : bruit %.4f · max %.4f · seuil %.4f · parole %s", j.get("bruit", 0), j.get("maxi", 0), j.get("seuil", 0), j.get("parle"))
    if j.get("maxi", 1) < 1e-4:
        raise PermissionError("le micro ne renvoie que du silence : macOS bloque le micro (Réglages Système → Confidentialité → Micro)")
    if not wav:
        return ""
    texte = transcrire(cfg, wav)
    log.info("Entendu : %r", texte)
    return texte


def diagnostic(cfg) -> int:
    print("Parlez normalement dans les 8 secondes (ex. « Jarvis, quelle heure est-il ? »)…")
    j: dict = {}
    wav = enregistrer_phrase(journal=j)
    print(f"Bruit de fond {j.get('bruit', 0):.4f} · voix max {j.get('maxi', 0):.4f} · seuil {j.get('seuil', 0):.4f}")
    if j.get("maxi", 1) < 1e-4:
        print("✗ Silence total : macOS bloque le micro. Réglages Système → Confidentialité et sécurité → Micro → activez Terminal et Jarvis.")
        return 1
    if not wav:
        print("✗ Je n'ai pas détecté de parole. Parlez plus fort / plus près du Mac, ou vérifiez le micro choisi (Réglages Système → Son → Entrée).")
        return 1
    print(f"✓ Parole détectée ({len(wav) // 32000:.0f} s). Transcription…")
    try:
        print(f"✓ Entendu : « {transcrire(cfg, wav)} »")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Transcription impossible : {exc}")
        return 1
    return 0
