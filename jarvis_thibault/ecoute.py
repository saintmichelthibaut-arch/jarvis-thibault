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



def _micro():
    """Le micro partagé de Jarvis (ou un faux micro pendant les tests)."""
    import sys

    faux = sys.modules.get("sounddevice")
    if faux is not None and not hasattr(faux, "query_devices"):
        return faux
    import sounddevice  # noqa: F401  (vérifie que le micro est utilisable)

    from . import micro

    return micro


log = logging.getLogger("jarvis.ecoute")
TAUX = 16000
BLOC = 480  # 30 ms
VERROU = threading.Lock()
niveau_actuel = {"v": 0.0}
ANNULER = threading.Event()
DERNIER_STOP = {"t": -1e9}  # fenêtre fermée / écoute arrêtée : une écoute qui démarre juste après est annulée aussi
ENV_PAS = BLOC / TAUX  # 30 ms
LECTURE: dict = {"env": None, "t0": 0.0, "actif": False, "fin": 0.0}
_ENVS: dict = {}
_SPECTRES: dict = {}  # fichier → spectre de Jarvis toutes les 30 ms (pour reconnaître SON écho dans le micro)

# ── Ce que Jarvis vient de dire : si le micro le « réentend », ce n'est pas vous qui parlez ──
from collections import deque as _deque

_DIT: "_deque" = _deque(maxlen=80)  # (horodatage, mots)
_HALLUCINATIONS = ("sous-titr", "sous titr", "amara", "merci d'avoir regard", "abonnez-vous", "abonnez vous",
                   "merci de votre attention", "radio-canada", "www.", ".com", ".org")
_REPONSES_COURTES = {"oui", "non", "stop", "merci", "ok", "okay", "daccord", "vasy", "continue", "arrete",
                     "tais", "toi", "attends", "jarvis", "si", "bien", "parfait", "super", "go"}


def _mots(texte: str) -> list:
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", (texte or "").lower().replace("’", "'"))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("'", "")
    return re.findall(r"[a-z0-9]+", t)


def memoriser_dit(texte: str) -> None:
    """Appelé pour chaque phrase que Jarvis prononce."""
    m = _mots(texte)
    if m:
        _DIT.append((time.time(), m))


def est_parasite(texte: str) -> bool:
    """Vrai si la « phrase entendue » n'est pas de vous : la propre voix de Jarvis captée par le micro,
    ou une phrase fantôme inventée par la transcription sur du bruit."""
    t = (texte or "").lower()
    if any(h in t for h in _HALLUCINATIONS):
        return True
    m = _mots(texte)
    if not m:
        return True
    maintenant = time.time()
    recents = [w for ts, w in _DIT if maintenant - ts < 120]
    if not recents:
        return False
    if len(m) >= 3:
        bigrammes = set()
        for w in recents:
            bigrammes.update(zip(w, w[1:]))
        mb = list(zip(m, m[1:]))
        return sum(b in bigrammes for b in mb) / len(mb) >= .6
    if set(m) <= _REPONSES_COURTES:
        return False
    tres_recents = [" ".join(w) for ts, w in _DIT if maintenant - ts < 15]
    return any(f" {' '.join(m)} " in f" {w} " for w in tres_recents)


def enveloppe(fichier) -> Optional[list]:
    """Niveau sonore (RMS toutes les 30 ms) d'un fichier audio que Jarvis va prononcer."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    fichier = Path(fichier)
    if str(fichier) in _ENVS:
        return _ENVS[str(fichier)]
    if fichier.suffix.lower() == ".wav":
        wav = fichier
    else:
        wav = Path(tempfile.mkstemp(suffix=".wav")[1])
        if shutil.which("afconvert"):
            cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(fichier), str(wav)]
        elif shutil.which("ffmpeg"):
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(fichier), "-ac", "1", "-ar", "16000", str(wav)]
        else:
            return None
        if subprocess.run(cmd, capture_output=True).returncode != 0:
            return None
    try:
        import array

        with wave.open(str(wav), "rb") as w:
            taux, n = w.getframerate(), w.getnchannels()
            a = array.array("h", w.readframes(w.getnframes()))
        if n > 1:
            a = a[::n]
        pas = max(1, int(taux * ENV_PAS))
        env = [math.sqrt(sum((v / 32768) ** 2 for v in a[i:i + pas]) / pas) for i in range(0, len(a) - pas, pas)]
        if taux == TAUX:
            try:
                import numpy as np

                x = np.frombuffer(a.tobytes(), dtype="int16")
                _SPECTRES[str(fichier)] = np.array([spectre(x[i:i + pas]) for i in range(0, len(x) - pas, pas)],
                                                   dtype="float32")
            except Exception:  # noqa: BLE001
                pass
    finally:
        if wav != fichier:
            wav.unlink(missing_ok=True)
    _ENVS[str(fichier)] = env
    if len(_ENVS) > 80:
        _SPECTRES.pop(next(iter(_ENVS)), None)
        _ENVS.pop(next(iter(_ENVS)))
    return env


def lecture_commence(fichier, position: float = 0.0) -> None:
    cle = str(fichier)
    LECTURE.update(env=_ENVS.get(cle), spectres=_SPECTRES.get(cle), fichier=cle,
                   t0=time.monotonic() - position, actif=True)
    if LECTURE["env"] is None:
        def calc():
            env = enveloppe(fichier)
            if LECTURE["actif"] and LECTURE.get("fichier") == cle:
                LECTURE.update(env=env, spectres=_SPECTRES.get(cle))
        threading.Thread(target=calc, daemon=True).start()


def lecture_fin() -> None:
    LECTURE.update(actif=False, fin=time.monotonic())


def lecture_etat():
    """(enveloppe, position en pas de 30 ms) de ce que Jarvis prononce, 0 s'il se tait, None si inconnu."""
    maintenant = time.monotonic()
    if not LECTURE["actif"]:
        return 0 if maintenant - LECTURE.get("fin", 0) > .45 else None
    if LECTURE["env"] is None:
        return None
    return LECTURE["env"], int((maintenant - LECTURE["t0"]) / ENV_PAS)


def _correlation(a, b) -> float:
    n = len(a)
    if n < 5:
        return -1.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return -1.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def apprendre_echo(hist, env, decalage: Optional[int] = None):
    """Décalage (en pas de 30 ms) et gain entre ce que Jarvis dit et ce que le micro entend."""
    if decalage is None:
        meilleur, decalage = -2.0, 2
        for d in range(0, 16):
            paires = [(r, env[p - d]) for p, r in hist if 0 <= p - d < len(env)]
            c = _correlation([x for x, _ in paires], [y for _, y in paires])
            if c > meilleur:
                meilleur, decalage = c, d
    ratios = []
    for p, r in hist:
        seg = env[max(0, p - decalage - 1):max(0, p - decalage + 2)]
        if seg and max(seg) > .02:
            ratios.append(r / max(seg))
    ratios.sort()
    gain = ratios[min(len(ratios) - 1, int(len(ratios) * .9))] if ratios else .5
    return decalage, gain


SEUIL_VOIX = .45  # « voisement » minimum : une voix humaine (cordes vocales) ≈ 0,6–0,95 ; bruits, clics, claquements ≈ 0–0,35


def voisement(b) -> float:
    """0..1 : à quel point ce bout de son ressemble à une VOIX (vibration périodique entre 70 et 400 Hz).
    Les bruits — clavier, porte, vaisselle, claquement, souffle — ne sont pas périodiques et restent bas."""
    return analyser_voix(b)[0]


def analyser_voix(b) -> tuple:
    """(score de voix 0..1, période de la voix en échantillons — sa « note » —, 0 si inconnue)."""
    try:
        import numpy as np

        x = np.asarray(b, dtype="float32")
        x = x - x.mean()
        n = len(x)
        e = float(np.dot(x, x))
        if n < 240 or e <= 1e-9:
            return 0.0, 0
        spectre = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(spectre * np.conj(spectre))[:n]
        cumul = np.cumsum(x * x)
        kmax = min(TAUX // 70, n - 120)
        k = np.arange(1, kmax)
        e1, e2 = cumul[n - k - 1], e - cumul[k - 1]
        norme = np.where((e1 > 0) & (e2 > 0), ac[k] / np.sqrt(np.maximum(e1 * e2, 1e-18)), 0.0)  # norme[i] ↔ décalage i+1
        bas = TAUX // 400  # 40 échantillons = 400 Hz
        i_p = bas - 1 + int(np.argmax(norme[bas - 1:]))
        p = float(norme[i_p])
        if float(norme[:i_p].min()) > .2:
            return min(p, .2), 0  # pas de creux avant la « période » : grondement grave, souffle, pas une voix
        z = int(np.argmax(norme < 0)) if (norme < 0).any() else i_p
        if z < bas - 1 and float(norme[z:bas - 1].max(initial=0.0)) > p - .03:
            return min(p, .3), 0  # son périodique très aigu (tintement, sifflement, bip) : pas une voix
        return max(0.0, min(1.0, p)), i_p + 1
    except Exception:  # noqa: BLE001
        return 1.0, 0  # sans numpy : on ne filtre pas


_FENETRE_SPECTRE = None
BANDE = slice(3, 129)  # 94 Hz – 4 kHz : là où sont les harmoniques de la voix


def spectre(b):
    """Amplitude du spectre d'un bloc de 30 ms (257 fréquences, pas de 31 Hz)."""
    import numpy as np

    global _FENETRE_SPECTRE
    x = np.asarray(b, dtype="float32")
    if _FENETRE_SPECTRE is None or len(_FENETRE_SPECTRE) != len(x):
        _FENETRE_SPECTRE = np.hanning(len(x)).astype("float32")
    return np.abs(np.fft.rfft(x * _FENETRE_SPECTRE, 512)).astype("float32")


def retard_par_spectre(hist_spectres, spectres, maxi: int = 12):
    """Retard (en pas de 30 ms) entre ce que Jarvis dit et ce que le micro en entend : celui pour lequel
    le spectre entendu ressemble le plus au spectre prononcé (bien plus sûr que le seul volume)."""
    import numpy as np

    meilleur, retard = -1.0, None
    for d in range(0, maxi + 1):
        sims = []
        for p, m in hist_spectres:
            q = p - d
            if 0 <= q < len(spectres):
                r = spectres[q][BANDE]
                mb = m[BANDE]
                n = float(np.linalg.norm(r) * np.linalg.norm(mb))
                if n > 0 and r.max() > 1:
                    sims.append(float(np.dot(np.log1p(r), np.log1p(mb)) /
                                      (np.linalg.norm(np.log1p(r)) * np.linalg.norm(np.log1p(mb)) + 1e-9)))
        if len(sims) >= 10 and float(np.mean(sims)) > meilleur + .005:
            meilleur, retard = float(np.mean(sims)), d
    return retard


def _rms(b) -> float:
    try:
        import numpy as np

        x = b.astype("float32") / 32768.0
        return float(np.sqrt(np.mean(x * x)))
    except Exception:  # noqa: BLE001
        return math.sqrt(sum((int(v) / 32768) ** 2 for v in b) / len(b))


def enregistrer_phrase(attente_max: float = 8.0, silence_fin: float = 1.5, duree_max: float = 15.0,
                       sur_niveau: Optional[Callable[[float], None]] = None, journal: Optional[dict] = None,
                       interruption: bool = False, sur_debut: Optional[Callable[[], None]] = None,
                       sensibilite: float = 1.0) -> Optional[bytes]:
    """Renvoie un WAV (bytes) de la phrase prononcée, ou None si personne n'a parlé.
    Le seuil s'adapte au bruit de la pièce (mesuré pendant les 0,3 premières secondes)."""
    sd = _micro()

    from collections import deque

    j = journal if journal is not None else {}
    if interruption and time.monotonic() - DERNIER_STOP["t"] < .3:
        j.update(annule=True, maxi=1.0, parle=False)
        return None
    with VERROU:
        ANNULER.clear()
        trames, parle, silence, debut = [], False, 0.0, time.monotonic()
        calib, bruit, maxi = [], 0.0, 0.0
        echo, fort = deque(maxlen=50), 0  # mode interruption : niveau de la voix de Jarvis captée par le micro
        hist, echo_appris, fond = [], None, 0.003
        hist_spectres = []
        recents = deque(maxlen=9)  # 5 instants « voix » sur les 270 dernières ms
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
                    # Jarvis parle : on compare le micro, instant par instant, à ce que Jarvis est en train de dire
                    trames = (trames + [bytes(b)])[-12:]
                    etat = lecture_etat()
                    if etat is not None:
                        if etat == 0:
                            ref = 0.0
                            fond = .95 * fond + .05 * min(rms, fond * 3 + 1e-4)
                        else:
                            env, pos = etat
                            spectres = LECTURE.get("spectres")
                            if echo_appris is None:
                                hist.append((pos, rms))
                                if spectres is not None:
                                    hist_spectres.append((pos, spectre(b)))
                                actifs = sum(1 for p, _ in hist if 0 <= p < len(env) and env[p] > .02)
                                if actifs < 30:
                                    fort = 0
                                    continue  # ≈ 1 s pour apprendre l'écho de la pièce
                                d = retard_par_spectre(hist_spectres, spectres) if spectres is not None and hist_spectres else None
                                echo_appris = apprendre_echo(hist, env, d)
                            decalage, gain = echo_appris
                            seg = env[max(0, pos - decalage - 1):max(0, pos - decalage + 2)]
                            ref = max(seg) if seg else 0.0
                            if ref < .004:
                                fond = .95 * fond + .05 * min(rms, fond * 3 + 1e-4)
                        seuil_i = max(.006 / max(.3, sensibilite), (echo_appris[1] * ref * 1.25 if echo_appris else 0) / max(.3, sensibilite)
                                      + fond * 2.5 / max(.3, sensibilite))
                        n_fort = 5
                    else:
                        echo.append(rms)
                        r0 = sorted(echo)[int(len(echo) * .9)] if len(echo) >= 10 else 1.0
                        seuil_i, n_fort = max(0.03 / max(.3, sensibilite), r0 * 2.3 / max(.3, sensibilite)), 6
                    # il faut que ce soit FORT et que ce soit une VOIX : les bruits ne le coupent plus
                    voix = False
                    if rms > seuil_i:
                        score, note = analyser_voix(b)
                        voix = score >= SEUIL_VOIX
                    recents.append(voix)
                    fort = sum(recents)
                    if fort >= n_fort:
                        parle, bruit = True, max(fond, rms * .25)
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
                seuil = max(0.008, bruit * 2.2)  # plancher fixe : le silence d'une pièce calme ne compte pas comme parole
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
    if maxi < 0.010:  # rien d'assez fort pour être une voix : on n'envoie pas du silence à la transcription
        j.update(bruit=bruit, maxi=maxi, seuil=seuil, parle=False)
        niveau_actuel["v"] = 0.0
        return None
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
    if est_parasite(texte):
        log.info("Entendu (ignoré : écho de Jarvis ou bruit) : %r", texte)
        return ""
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
