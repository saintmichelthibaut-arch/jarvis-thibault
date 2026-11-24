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
ETAT = {"ouvert": False, "erreur": None}


def _boucle() -> None:
    import sounddevice as sd

    while True:
        try:
            with sd.InputStream(samplerate=TAUX, channels=1, blocksize=MORCEAU, dtype="float32") as flux:
                ETAT.update(ouvert=True, erreur=None)
                log.info("Micro ouvert (écoute partagée)")
                while True:
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


def _demarrer() -> None:
    global _fil
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
            morceaux.append(b)
            total += len(b)
        tout = np.concatenate(morceaux)
        bloc, self.tampon = tout[:n], tout[n:]
        if self.dtype == "int16":
            bloc = (np.clip(bloc, -1, 1) * 32767).astype("int16")
        return bloc.reshape(-1, 1), False
