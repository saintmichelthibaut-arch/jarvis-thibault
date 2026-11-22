"""Réveil par double claquement de mains : ouvre Jarvis en plein écran.

Écoute le micro en arrière-plan (même quand la fenêtre est fermée). Un claquement
est un son très bref et très fort par rapport au bruit ambiant, qui retombe aussitôt
(la voix ou la musique, elles, durent). Deux claquements espacés de 0,2 à 0,9 s
déclenchent le réveil.
"""

from __future__ import annotations

import logging
import math
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("jarvis.claquement")

TAUX = 16000
BLOC = 256  # 16 ms


class Detecteur:
    """Reçoit des blocs d'échantillons (floats -1..1) et signale les doubles claquements."""

    def __init__(self, sensibilite: float = 1.0, ecart_min: float = .18, ecart_max: float = .9,
                 pause_apres: float = 4.0, horloge: Callable[[], float] = time.monotonic):
        self.k = 6.0 / max(.3, sensibilite)        # combien de fois plus fort que le bruit ambiant
        self.min_abs = .02 / max(.3, sensibilite)   # niveau minimum absolu (RMS)
        self.decroissance = .5                      # le son doit retomber sous 50 % en ~140 ms
        self.nb_claps = 0
        self.ecart_min, self.ecart_max, self.pause_apres = ecart_min, ecart_max, pause_apres
        self.horloge = horloge
        self.bruit = .004
        self.candidat: Optional[tuple] = None  # (t, rms, blocs écoulés, rms max des blocs suivants)
        self.claps: List[float] = []
        self.dernier_reveil = -1e9
        self.dernier_clap = -1e9

    def bloc(self, ech) -> bool:
        t = self.horloge()
        n = len(ech) or 1
        rms = math.sqrt(sum(x * x for x in ech) / n)
        crete = max((abs(x) for x in ech), default=0.0)
        reveil = False
        if self.candidat:
            t0, r0, vus, suite = self.candidat
            suite = max(suite, rms if vus >= 2 else 0.0)  # on laisse 2 blocs pour la queue du claquement
            vus += 1
            if vus >= 9:  # ~140 ms après : un claquement est retombé, une voix non
                if suite < r0 * self.decroissance:
                    reveil = self._clap(t0)
                self.candidat = None
            else:
                self.candidat = (t0, r0, vus, suite)
        elif (rms > max(self.min_abs, self.bruit * self.k) and crete > 1.8 * rms
              and t - self.dernier_clap > .12):
            self.candidat = (t, rms, 0, 0.0)
        else:
            # bruit ambiant : moyenne lente, seulement hors pics
            self.bruit = .995 * self.bruit + .005 * min(rms, self.bruit * 3 + 1e-4)
        return reveil

    def _clap(self, t: float) -> bool:
        self.dernier_clap = t
        self.nb_claps += 1
        log.info("Claquement entendu")
        if t - self.dernier_reveil < self.pause_apres:
            return False
        self.claps = [c for c in self.claps if t - c <= self.ecart_max] + [t]
        if len(self.claps) >= 2 and self.ecart_min <= self.claps[-1] - self.claps[-2] <= self.ecart_max:
            self.claps = []
            self.dernier_reveil = t
            return True
        return False


def reveiller(cfg, ev=None) -> None:
    """Ouvre l'app Jarvis en plein écran (ou la ramène devant) et salue."""
    (cfg.dossier / ".reveil").write_text(str(time.time()), encoding="utf-8")
    app = Path.home() / "Applications" / "Jarvis.app"
    if app.exists():
        subprocess.Popen(["open", str(app)])
    appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
    if ev is not None:
        ev.publier("reveil", "Réveil", "double claquement", "raison")

    def saluer():
        try:
            from . import ecoute, voix

            f = voix.synthetiser(cfg, f"À votre service, {appel}.", nom=f"reveil-{appel}-v2")
            if f:
                voix.jouer(f, attendre=True)
            if ev is not None and cfg["claquement"].get("ecouter_apres", True):
                ev.publier("ecoute", "À l'écoute", "parlez maintenant", "langage")
                texte = ecoute.ecouter_commande(cfg)
                if texte:
                    ev.publier("commande", "Vous", texte, "langage")
                else:
                    ev.publier("ecoute_fin", "Écoute", "terminée", "langage")
        except Exception as exc:  # noqa: BLE001
            log.warning("Salutation / écoute impossible : %s", exc)

    threading.Thread(target=saluer, daemon=True).start()


def ecouter(cfg, ev=None) -> None:
    """Boucle d'écoute du micro (thread de fond). Ne fait rien si le micro est indisponible."""
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        log.info("Réveil par claquement indisponible (%s)", exc)
        return
    det = Detecteur(float(cfg["claquement"].get("sensibilite", 1.0) or 1.0))
    log.info("Réveil par claquement de mains : à l'écoute")
    while True:
        try:
            with sd.InputStream(samplerate=TAUX, channels=1, blocksize=BLOC, dtype="float32") as flux:
                while True:
                    donnees, _ = flux.read(BLOC)
                    if det.bloc(donnees[:, 0].tolist()):
                        log.info("Double claquement détecté")
                        reveiller(cfg, ev)
        except Exception as exc:  # noqa: BLE001
            log.warning("Micro indisponible pour le claquement : %s — nouvel essai dans 30 s", exc)
            time.sleep(30)


def diagnostic(secondes: float = 6.0) -> int:
    """Enregistre quelques secondes, mesure les claquements et dit si Jarvis les reconnaît."""
    import sounddevice as sd

    from .config import charger

    cfg = charger()
    sens = float(cfg["claquement"].get("sensibilite", 1.0) or 1.0)
    print(f"Faites clap-clap 2 ou 3 fois pendant {secondes:.0f} secondes… (sensibilité {sens})")
    son = sd.rec(int(secondes * TAUX), samplerate=TAUX, channels=1, dtype="float32")
    sd.wait()
    x = son[:, 0].tolist()
    blocs = [x[i:i + BLOC] for i in range(0, len(x) - BLOC, BLOC)]
    rms = [math.sqrt(sum(v * v for v in b) / len(b)) for b in blocs]
    pic = max((abs(v) for v in x), default=0.0)
    fond = sorted(rms)[len(rms) // 2] if rms else 0
    print(f"Niveau max : {pic:.3f}   ·   bruit de fond : {fond:.4f}   ·   plus fort bloc : {max(rms, default=0):.3f}")
    if pic < 1e-4:
        print("✗ Le micro ne renvoie que du silence : macOS bloque l'accès au micro.")
        print("  Réglages Système → Confidentialité et sécurité → Micro → activez Terminal (et Jarvis), puis relancez.")
        return 1
    t = [0.0]
    det = Detecteur(sens, horloge=lambda: t[0])
    reveils = 0
    for i, b in enumerate(blocs):
        t[0] = i * BLOC / TAUX
        reveils += det.bloc(b)
    print(f"Claquements reconnus : {det.nb_claps}   ·   doubles claquements (réveil) : {reveils}")
    if reveils:
        print("✓ Parfait : Jarvis vous entend. Fermez sa fenêtre et faites clap-clap.")
    elif det.nb_claps == 0:
        print("✗ Aucun claquement reconnu. Essayez plus fort / plus près, ou montez la sensibilité (ex. 1.8).")
    else:
        print("~ Claquements entendus mais pas en double : faites-les plus rapprochés (moins d'une seconde).")
    return 0
