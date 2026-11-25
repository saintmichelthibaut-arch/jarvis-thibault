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



def _micro():
    """Le micro partagé de Jarvis (ou un faux micro pendant les tests)."""
    import sys

    faux = sys.modules.get("sounddevice")
    if faux is not None and not hasattr(faux, "query_devices"):
        return faux
    import sounddevice  # noqa: F401  (vérifie que le micro est utilisable)

    from . import micro

    return micro


log = logging.getLogger("jarvis.claquement")

TAUX = 16000
BLOC = 256  # 16 ms
ETAT_MICRO: dict = {"ok": None}


class Detecteur:
    """Reçoit des blocs d'échantillons (floats -1..1) et signale les doubles claquements.
    (Même sensibilité qu'à l'origine ; seule différence : 3 claquements ou plus d'affilée — une rafale
    de clics de clavier par exemple — ne réveillent pas Jarvis.)"""

    def __init__(self, sensibilite: float = 1.0, ecart_min: float = .15, ecart_max: float = 1.3,
                 pause_apres: float = 10.0, horloge: Callable[[], float] = time.monotonic):
        self.k = 5.0 / max(.3, sensibilite)        # combien de fois plus fort que le bruit ambiant
        self.min_abs = .02 / max(.3, sensibilite)   # niveau minimum absolu (RMS)
        self.decroissance = .6                      # le son doit retomber sous 60 % en ~140 ms
        self.calme_apres = .5                       # pas de 3e claquement dans la demi-seconde qui suit
        self.nb_claps = 0
        self.ecart_min, self.ecart_max, self.pause_apres = ecart_min, ecart_max, pause_apres
        self.horloge = horloge
        self.bruit = .004
        self.candidat: Optional[tuple] = None  # (t, rms, blocs écoulés, rms max des blocs suivants)
        self.claps: List[float] = []
        self.attente: Optional[float] = None   # double claquement repéré : on vérifie qu'il n'y en a pas un 3e
        self.dernier_reveil = -1e9
        self.dernier_clap = -1e9
        self.derniere_rafale = -1e9

    def reinitialiser(self) -> None:
        """Oublie les claquements en cours (Jarvis parle : ce n'est pas le moment)."""
        self.candidat = None
        self.claps = []
        self.attente = None

    def bloc(self, ech) -> bool:
        t = self.horloge()
        n = len(ech) or 1
        rms = math.sqrt(sum(x * x for x in ech) / n)
        crete = max((abs(x) for x in ech), default=0.0)
        reveil = False
        if self.attente is not None and t >= self.attente and not self.candidat:
            self.attente = None
            self.claps = []
            self.dernier_reveil = t
            reveil = True
        if self.candidat:
            t0, r0, vus, suite = self.candidat
            suite = max(suite, rms if vus >= 2 else 0.0)  # on laisse 2 blocs pour la queue du claquement
            vus += 1
            if vus >= 9:  # ~140 ms après : un claquement est retombé, une voix non
                if suite < r0 * self.decroissance:
                    self._clap(t0)
                elif time.time() - getattr(self, "_dernier_rejet", 0) > 20:
                    self._dernier_rejet = time.time()
                    log.info("Bruit fort ignoré (pas assez bref pour un claquement)")
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

    def _clap(self, t: float) -> None:
        self.dernier_clap = t
        self.nb_claps += 1
        log.info("Claquement entendu")
        if self.attente is not None or t - self.derniere_rafale < 1.0:
            # un 3e juste après (ou la rafale continue) : clavier, tapotements… pas un clap-clap
            if self.attente is not None:
                log.info("Claquements en rafale : ignorés")
            self.attente = None
            self.derniere_rafale = t
            self.claps = []
            return
        if t - self.dernier_reveil < self.pause_apres:
            return
        self.claps = [c for c in self.claps if t - c <= self.ecart_max] + [t]
        if len(self.claps) >= 2 and self.ecart_min <= self.claps[-1] - self.claps[-2] <= self.ecart_max:
            self.attente = t + self.calme_apres


_REVEIL = threading.Lock()


def _occupe() -> Optional[str]:
    """Raison de ne PAS écouter les claquements en ce moment (sinon None).
    Fenêtre fermée, seule la voix jouée directement par le Mac (salut, briefing) compte : rien ne peut
    rester « bloqué » par une fenêtre fermée au milieu d'une phrase."""
    from . import voix

    if _REVEIL.locked():
        return "réveil en cours"
    if voix.parle_sur_le_mac():
        return "Jarvis parle"
    if fenetre_ouverte_cache():
        return "fenêtre ouverte"
    return None


_FENETRE = {"t": -1e9, "ouverte": False}


def fenetre_ouverte_cache() -> bool:
    """fenetre_ouverte(), vérifiée au plus une fois par seconde."""
    if time.monotonic() - _FENETRE["t"] > 1.0:
        _FENETRE.update(t=time.monotonic(), ouverte=fenetre_ouverte())
    return _FENETRE["ouverte"]


def fenetre_ouverte() -> bool:
    # « [.] » : un autre pgrep lancé au même moment (clap-clap + annulation d'écho) ne se reconnaît pas
    # lui-même comme la fenêtre (sa ligne de commande contient « [.] », pas « . »).
    r = subprocess.run(["pgrep", "-f", "jarvis_thibault[.]cli app"], capture_output=True)
    return r.returncode == 0


def ouvrir_app(cfg) -> str:
    """Ouvre la fenêtre de Jarvis en plein écran et VÉRIFIE qu'elle est bien là (sinon, autre méthode)."""
    import sys

    (cfg.dossier / ".reveil").write_text(str(time.time()), encoding="utf-8")
    if fenetre_ouverte():
        log.info("Réveil : fenêtre déjà ouverte → mise au premier plan")
        subprocess.run(["osascript", "-e", 'tell application "Jarvis" to activate'], capture_output=True, timeout=5)
        return "deja"
    app = Path.home() / "Applications" / "Jarvis.app"
    if app.exists():
        r = subprocess.run(["open", str(app)], capture_output=True, text=True, timeout=15)
        log.info("Réveil : open Jarvis.app → code %s %s", r.returncode, (r.stderr or "").strip()[:200])
        for _ in range(40):  # jusqu'à 8 s
            if fenetre_ouverte():
                log.info("Réveil : fenêtre ouverte ✓")
                return "app"
            time.sleep(.2)
        log.warning("Réveil : l'app ne s'est pas ouverte avec « open » → lancement direct")
    journal = open(cfg.dossier / "jarvis.log", "ab")  # noqa: SIM115
    subprocess.Popen([sys.executable, "-m", "jarvis_thibault.cli", "app"], stdout=journal, stderr=journal,
                     start_new_session=True)
    for _ in range(40):
        if fenetre_ouverte():
            log.info("Réveil : fenêtre ouverte (lancement direct) ✓")
            return "direct"
        time.sleep(.2)
    log.error("Réveil : impossible d'ouvrir la fenêtre de Jarvis")
    return "echec"


def reveiller(cfg, ev=None) -> None:
    """Ouvre l'app Jarvis en plein écran et salue (une seule fois, même si on claque encore)."""
    if not _REVEIL.acquire(blocking=False):
        log.info("Réveil déjà en cours : ignoré")
        return
    log.info("Réveil demandé")
    threading.Thread(target=ouvrir_app, args=(cfg,), daemon=True).start()
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
        finally:
            _REVEIL.release()

    threading.Thread(target=saluer, daemon=True).start()


def ecouter(cfg, ev=None) -> None:
    """Boucle d'écoute du micro (thread de fond). Ne fait rien si le micro est indisponible."""
    try:
        sd = _micro()
    except Exception as exc:  # noqa: BLE001
        log.info("Réveil par claquement indisponible (%s)", exc)
        return
    det = Detecteur(float(cfg["claquement"].get("sensibilite", 1.0) or 1.0))
    occupe_avant: Optional[str] = None
    log.info("Réveil par claquement de mains : à l'écoute")
    while True:
        try:
            with sd.InputStream(samplerate=TAUX, channels=1, blocksize=BLOC, dtype="float32") as flux:
                debut, maxi, signale = time.monotonic(), 0.0, False
                while True:
                    donnees, _ = flux.read(BLOC)
                    if not signale:
                        maxi = max(maxi, float(abs(donnees).max()))
                        if time.monotonic() - debut > 8:
                            signale = True
                            if maxi < 1e-4:
                                ETAT_MICRO["ok"] = False
                                log.warning("Micro : SILENCE TOTAL — macOS bloque le micro pour ce processus. "
                                            "Réglages Système → Confidentialité et sécurité → Micro : activez Jarvis.")
                                prevenir = time.time() - ETAT_MICRO.get("prevenu", 0) > 3600
                                if prevenir:
                                    ETAT_MICRO["prevenu"] = time.time()
                                if ev is not None and prevenir:
                                    ev.publier("micro", "Micro bloqué", "Réglages Système → Confidentialité → Micro → activez Jarvis", "raison")
                                from .voix import notifier

                                if prevenir:
                                    notifier("Jarvis", "Je n'ai pas accès au micro : Réglages Système → Confidentialité → Micro → activez Jarvis.")
                                break  # on réessaie dans 30 s (au cas où l'accès vient d'être donné)
                            ETAT_MICRO["ok"] = True
                            log.info("Micro : OK (niveau max %.3f sur 8 s)", maxi)
                    raison = _occupe()
                    if raison:
                        if raison != occupe_avant:
                            log.info("Clap-clap en pause : %s", raison)
                        occupe_avant = raison
                        det.reinitialiser()
                        continue
                    if occupe_avant:
                        log.info("Clap-clap : de nouveau à l'écoute")
                        occupe_avant = None
                    if det.bloc(donnees[:, 0].tolist()):
                        log.info("Double claquement détecté")
                        _FENETRE["t"] = -1e9
                        reveiller(cfg, ev)
        except Exception as exc:  # noqa: BLE001
            ETAT_MICRO["ok"] = False
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
