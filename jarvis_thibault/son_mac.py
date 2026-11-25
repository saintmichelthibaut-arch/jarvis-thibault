"""Voix ET micro de Jarvis par le moteur audio de macOS, avec l'ANNULATION D'ÉCHO (comme FaceTime).

Sans elle, le micro du Mac réentend la voix de Jarvis sortir des haut-parleurs, et Jarvis se coupe
la parole tout seul. Ici, Jarvis joue sa voix et écoute le micro dans le MÊME moteur audio, avec le
traitement vocal d'Apple activé : macOS retire en temps réel sa propre voix de ce qu'entend le micro.
Il ne reste que vous (et la pièce).

Si quoi que ce soit échoue (ancien macOS, module absent…), Jarvis revient tout seul à l'ancienne
méthode : la fenêtre joue la voix et le micro est lu directement.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.son")
TAUX = 16000


class Moteur:
    def __init__(self) -> None:
        self.actif = False
        self.erreur: Optional[str] = None
        self.verrou = threading.RLock()
        self.id = 0               # numéro de la phrase en cours (la fenêtre suit sa fin)
        self.fini = True
        self.en_pause = False
        self.fichier: Optional[str] = None
        self.duree = 0.0
        self.debut = 0.0          # instant (monotonic) où la lecture aurait commencé sans pause
        self.pause_a = 0.0
        self.format_lecteur = None
        self._reste = None        # échantillons pas encore convertis à 16 kHz
        self._phase = 0.0

    # ── démarrage ──
    def demarrer(self) -> bool:
        try:
            import AVFoundation as AVF  # noqa: N814

            self.AVF = AVF
            self.moteur = AVF.AVAudioEngine.alloc().init()
            entree = self.moteur.inputNode()
            # Le mélangeur principal (relié à la sortie) doit exister AVANT d'activer le traitement
            # vocal, sinon macOS refuse de démarrer le moteur (erreur -10875, kAUInitialize).
            self.moteur.mainMixerNode()
            ok, err = entree.setVoiceProcessingEnabled_error_(True, None)
            if not ok:
                raise RuntimeError(f"traitement vocal refusé : {err}")
            try:  # ne pas baisser le son des autres apps (musique…) pendant que Jarvis écoute
                cfg = AVF.AVAudioVoiceProcessingOtherAudioDuckingConfiguration
                entree.setVoiceProcessingOtherAudioDuckingConfiguration_(cfg(False, 10))  # 10 = niveau minimum
            except Exception:  # noqa: BLE001
                pass
            self.entree = entree
            self.lecteur = AVF.AVAudioPlayerNode.alloc().init()
            self.moteur.attachNode_(self.lecteur)
            self.sortie = self.moteur.mainMixerNode()
            try:  # petite pièce métallique : la voix d'IA (facultatif)
                rv = AVF.AVAudioUnitReverb.alloc().init()
                rv.loadFactoryPreset_(AVF.AVAudioUnitReverbPresetSmallRoom)
                rv.setWetDryMix_(9.0)
                self.moteur.attachNode_(rv)
                self.moteur.connect_to_format_(rv, self.moteur.mainMixerNode(), None)
                self.sortie = rv
            except Exception as exc:  # noqa: BLE001
                log.info("Son : sans effet de pièce (%s)", exc)
            self.moteur.connect_to_format_(self.lecteur, self.sortie, None)

            fmt = entree.outputFormatForBus_(0)
            self.taux_micro = float(fmt.sampleRate())
            entree.installTapOnBus_bufferSize_format_block_(0, 2048, fmt, self._micro)
            self.moteur.prepare()
            ok, err = self.moteur.startAndReturnError_(None)
            if not ok:
                raise RuntimeError(f"moteur audio : {err}")
            self.actif = True
            log.info("Son : annulation d'écho macOS ACTIVE (micro %.0f Hz)", self.taux_micro)
            threading.Thread(target=self._surveiller_fenetre, daemon=True, name="son-fenetre").start()
            return True
        except Exception as exc:  # noqa: BLE001
            self.erreur = str(exc)[:300]
            log.warning("Son : annulation d'écho indisponible (%s) — méthode classique", self.erreur)
            self.actif = False
            return False

    # ── micro : on convertit en 16 kHz et on distribue au reste de Jarvis ──
    def _micro(self, tampon, quand) -> None:  # appelé par macOS sur son propre fil
        try:
            import numpy as np

            from . import micro

            n = int(tampon.frameLength())
            if n <= 0:
                return
            canal = tampon.floatChannelData()[0]
            x = np.frombuffer(canal.as_buffer(n), dtype=np.float32)
            if len(x) < n:  # selon la version de pyobjc, la taille est en octets
                x = np.frombuffer(canal.as_buffer(n * 4), dtype=np.float32)
            x = x[:n].copy()
            if self._reste is not None and len(self._reste):
                x = np.concatenate([self._reste, x])
            pas = self.taux_micro / TAUX
            k = max(1, int(round(pas)))
            if k > 1:  # petit filtre passe-bas avant de réduire la fréquence
                x_f = np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")
            else:
                x_f = x
            positions = np.arange(self._phase, len(x) - 1, pas)
            sortie = np.interp(positions, np.arange(len(x)), x_f).astype(np.float32)
            dernier = positions[-1] + pas if len(positions) else self._phase
            garde = int(dernier) - 1
            self._reste = x[max(0, garde):]
            self._phase = dernier - max(0, garde)
            micro.pousser(sortie)
        except Exception as exc:  # noqa: BLE001
            if time.time() - getattr(self, "_err_t", 0) > 60:
                self._err_t = time.time()
                log.warning("Son : micro illisible (%s)", exc)

    # ── fenêtre fermée : traitement vocal coupé (le micro brut entend mieux les claquements) ──
    def traitement(self, actif: bool) -> None:
        if getattr(self, "_traitement", None) == actif:
            return
        try:
            self.entree.setVoiceProcessingBypassed_(not actif)
            self._traitement = actif
            log.info("Son : annulation d'écho %s", "active (fenêtre ouverte)" if actif else "en pause (fenêtre fermée)")
        except Exception as exc:  # noqa: BLE001
            log.info("Son : réglage du traitement vocal impossible (%s)", exc)
            self._traitement = actif

    def _surveiller_fenetre(self) -> None:
        from .claquement import fenetre_ouverte_cache

        while self.actif:
            try:
                self.traitement(fenetre_ouverte_cache() or not self.fini)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)

    # ── voix ──
    def jouer(self, fichier: Path, position: float = 0.0) -> int:
        AVF = self.AVF
        from Foundation import NSURL

        with self.verrou:
            self.id += 1
            num = self.id
            f, err = AVF.AVAudioFile.alloc().initForReading_error_(NSURL.fileURLWithPath_(str(fichier)), None)
            if f is None:
                raise RuntimeError(f"fichier audio illisible : {err}")
            fmt = f.processingFormat()
            taux = float(fmt.sampleRate())
            debut = max(0, int(position * taux))
            total = int(f.length())
            self.lecteur.stop()
            if self.format_lecteur is None or not self.format_lecteur.isEqual_(fmt):
                self.moteur.disconnectNodeOutput_(self.lecteur)
                self.moteur.connect_to_format_(self.lecteur, self.sortie, fmt)
                self.format_lecteur = fmt

            def termine(*_):
                with self.verrou:
                    if num == self.id:
                        self.fini = True
                        from . import ecoute

                        ecoute.lecture_fin()

            self.lecteur.scheduleSegment_startingFrame_frameCount_atTime_completionHandler_(
                f, debut, max(0, total - debut), None, termine)
            if not self.moteur.isRunning():
                self.moteur.startAndReturnError_(None)
            self.lecteur.play()
            self.fini, self.en_pause = False, False
            self.fichier, self.duree = str(fichier), total / taux
            self.debut = time.monotonic() - position
            return num

    def pause(self) -> None:
        with self.verrou:
            if not self.fini and not self.en_pause:
                self.lecteur.pause()
                self.en_pause, self.pause_a = True, time.monotonic()

    def reprendre(self) -> None:
        with self.verrou:
            if not self.fini and self.en_pause:
                self.debut += time.monotonic() - self.pause_a
                self.lecteur.play()
                self.en_pause = False

    def arreter(self) -> None:
        with self.verrou:
            self.id += 1
            self.fini, self.en_pause = True, False
            self.lecteur.stop()

    def position(self) -> float:
        if self.fini:
            return self.duree
        t = (self.pause_a if self.en_pause else time.monotonic()) - self.debut
        return max(0.0, min(self.duree, t))

    def etat(self) -> dict:
        from . import ecoute

        pos = self.position()
        niveau = 0.0
        env = ecoute._ENVS.get(self.fichier or "")
        if env and not self.fini and not self.en_pause:
            i = int(pos / ecoute.ENV_PAS)
            niveau = max(env[max(0, i - 1):i + 2] or [0.0])
        return {"id": self.id, "fini": self.fini, "pause": self.en_pause, "position": round(pos, 3),
                "duree": round(self.duree, 3), "niveau": round(niveau, 4)}


MOTEUR = Moteur()


def actif() -> bool:
    return MOTEUR.actif


def demarrer(cfg) -> bool:
    """À appeler une fois au lancement du serveur (macOS seulement)."""
    import platform

    if platform.system() != "Darwin" or not cfg["voix"].get("annulation_echo", True):
        return False
    if MOTEUR.actif:
        return True
    from . import micro

    if MOTEUR.demarrer():
        micro.utiliser_source_externe()
        return True
    return False
