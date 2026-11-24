"""Une seule écoute du micro pour tout Jarvis (clap-clap, conversation, interruption).

macOS supporte mal plusieurs écoutes du micro ouvertes en même temps dans le même
programme (erreur -50, une écoute « sourde »). Ce module ouvre UN flux et le partage :
chaque utilisateur s'abonne et reçoit les mêmes échantillons.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import List

log = logging.getLogger("jarvis.micro")
TAUX = 16000
MORCEAU = 160  # 10 ms

_abonnes: List["queue.Queue"] = []
_verrou = threading.Lock()
_fil = None
ETAT = {"ouvert": False, "erreur": None, "nom": ""}
EXTERNE = {"oui": False}  # le son arrive du moteur audio macOS (annulation d'écho) au lieu de sounddevice
_SILENCE = {"dit": 0.0}


INTEGRE = ("macbook", "built-in", "intégré", "integre", "internal")
A_EVITER = ("iphone", "ipad", "continuity", "teams", "zoom", "blackhole", "loopback", "soundflower",
            "aggregate", "agrégé", "virtual", "virtuel", "krisp", "airpods")


def choisir_micro(appareils: list, defaut: int = -1, prefere: str = "") -> int | None:
    """Index du micro à utiliser :
    1. celui nommé dans la config ([ecoute] micro = "…"), s'il est branché ;
    2. sinon le micro intégré du MacBook — TOUJOURS, même si macOS bascule le micro par défaut
       sur l'iPhone (Continuité), des AirPods ou un faux micro (Teams, Zoom…) ;
    3. sinon le micro par défaut, s'il n'est pas un de ceux-là ; sinon le premier micro réel."""
    entrees = [(i, str(a.get("name", ""))) for i, a in enumerate(appareils) if a.get("max_input_channels", 0) > 0]
    if prefere:
        for i, nom in entrees:
            if prefere.lower() in nom.lower():
                return i
    for i, nom in entrees:
        if any(m in nom.lower() for m in INTEGRE) and not any(m in nom.lower() for m in A_EVITER):
            return i
    noms = dict(entrees)
    if defaut in noms and not any(m in noms[defaut].lower() for m in A_EVITER):
        return defaut
    for i, nom in entrees:
        if not any(m in nom.lower() for m in A_EVITER):
            return i
    return None


def _micro_voulu(sd) -> tuple:
    prefere = ""
    try:
        from .config import charger

        prefere = str(charger()["ecoute"].get("micro", "") or "")
    except Exception:  # noqa: BLE001
        pass
    defaut = -1
    try:
        d = sd.default.device  # paire (entrée, sortie) : sounddevice._InputOutputPair, indexable
        try:
            d = d[0]
        except (TypeError, IndexError, KeyError):
            pass
        defaut = int(d) if d is not None else -1
    except Exception:  # noqa: BLE001
        defaut = -1
    appareils = [dict(a) for a in sd.query_devices()]
    i = choisir_micro(appareils, defaut, prefere)
    return i, (appareils[i]["name"] if i is not None else "micro par défaut")


def utiliser_source_externe() -> None:
    """Le micro arrive désormais par pousser() (moteur audio avec annulation d'écho)."""
    EXTERNE["oui"] = True
    ETAT.update(ouvert=True, erreur=None, nom="micro avec annulation d'écho (macOS)")


def pousser(bloc) -> None:
    """Distribue des échantillons (float32, 16 kHz) à tous les utilisateurs du micro."""
    for i in range(0, len(bloc), MORCEAU):
        morceau = bloc[i:i + MORCEAU]
        with _verrou:
            for q in list(_abonnes):
                try:
                    q.put_nowait(morceau)
                except queue.Full:
                    pass


def _boucle() -> None:
    import sounddevice as sd

    while not EXTERNE["oui"]:
        try:
            index, nom = _micro_voulu(sd)
            with sd.InputStream(device=index, samplerate=TAUX, channels=1, blocksize=MORCEAU, dtype="float32") as flux:
                ETAT.update(ouvert=True, erreur=None, nom=nom)
                log.info("Micro ouvert (écoute partagée) : %s", nom)
                while not EXTERNE["oui"]:
                    donnees, _ = flux.read(MORCEAU)
                    bloc = donnees[:, 0].copy()
                    with _verrou:
                        for q in list(_abonnes):
                            try:
                                q.put_nowait(bloc)
                            except queue.Full:
                                pass
        except Exception as exc:  # noqa: BLE001
            ETAT.update(ouvert=False, erreur=str(exc)[:200])
            log.warning("Micro indisponible : %s — nouvel essai dans 5 s", exc)
            time.sleep(5)
            try:  # micro débranché / changé : on relit la liste des micros avant de réessayer
                sd._terminate()
                sd._initialize()
            except Exception:  # noqa: BLE001
                pass


def _demarrer() -> None:
    global _fil
    if EXTERNE["oui"]:
        return
    with _verrou:
        if _fil is None or not _fil.is_alive():
            _fil = threading.Thread(target=_boucle, daemon=True, name="micro")
            _fil.start()


class InputStream:
    """Remplace sounddevice.InputStream : lit le flux partagé (mêmes signatures utilisées dans Jarvis)."""

    def __init__(self, samplerate: int = TAUX, channels: int = 1, blocksize: int = MORCEAU, dtype: str = "float32", **_):
        self.taille, self.dtype = blocksize, dtype
        self.q: "queue.Queue" = queue.Queue(maxsize=3000)  # 30 s de marge
        self.tampon = None

    def __enter__(self):
        _demarrer()
        with _verrou:
            _abonnes.append(self.q)
        return self

    def __exit__(self, *exc):
        with _verrou:
            if self.q in _abonnes:
                _abonnes.remove(self.q)
        return False

    def read(self, n: int):
        import numpy as np

        morceaux, total = [], 0
        if self.tampon is not None and len(self.tampon):
            morceaux.append(self.tampon)
            total = len(self.tampon)
        while total < n:
            try:
                b = self.q.get(timeout=2)
            except queue.Empty:
                b = np.zeros(MORCEAU, dtype="float32")  # micro coupé : du silence plutôt qu'un blocage
                if time.time() - _SILENCE["dit"] > 600:
                    _SILENCE["dit"] = time.time()
                    log.warning("Micro : plus aucun son reçu depuis 2 s (micro débranché ou bloqué ?)")
            morceaux.append(b)
            total += len(b)
        tout = np.concatenate(morceaux)
        bloc, self.tampon = tout[:n], tout[n:]
        if self.dtype == "int16":
            bloc = (np.clip(bloc, -1, 1) * 32767).astype("int16")
        return bloc.reshape(-1, 1), False
