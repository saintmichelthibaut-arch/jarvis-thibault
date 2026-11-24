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
GEORGE = "JBFqnCBsd6RMkjVDRZzb"
import threading as _threading
import time as _time

_ELEVEN_SEM = _threading.BoundedSemaphore(2)  # le compte gratuit n'accepte que 2 demandes à la fois
_VOIX_REFUSEES: set = set()
_MODELES_REFUSES: set = set()
_ELEVEN_PAUSE = {"jusqua": 0.0}  # voix « George » d'ElevenLabs (voix de base, offre gratuite)


def elevenlabs_tts(cle: str, voix_id: str, texte: str, sortie: Path, modele: str = "eleven_flash_v2_5",
                   reglages: Optional[dict] = None, transport=None, avec_langue: bool = True) -> Path:
    """Synthèse ElevenLabs → fichier mp3."""
    import httpx

    if not voix_id:
        raise ValueError("Aucune voix ElevenLabs choisie : lancez « jarvis-thibault elevenlabs »")
    corps = {"text": texte[:4500], "model_id": modele, "seed": 4242,
             "voice_settings": reglages or {"stability": .5, "similarity_boost": .8, "style": .25, "use_speaker_boost": True}}
    if avec_langue:
        corps["language_code"] = "fr"
    for essai in range(6):
        with _ELEVEN_SEM, httpx.Client(timeout=40, transport=transport) as c:
            r = c.post(f"{ELEVEN}/text-to-speech/{voix_id}", params={"output_format": "mp3_44100_128"},
                       headers={"xi-api-key": cle, "accept": "audio/mpeg"}, json=corps)
        if r.status_code == 429 and "quota" not in r.text.lower():
            _time.sleep(.35 * (essai + 1))  # trop de demandes en même temps : on patiente, même voix
            continue
        break
    if r.status_code == 401:
        raise PermissionError("Clé ElevenLabs refusée (401) : vérifiez-la avec ajouter-cle.sh")
    if r.status_code in (400, 422) and avec_langue and "language" in r.text.lower():
        return elevenlabs_tts(cle, voix_id, texte, sortie, modele, reglages, transport, avec_langue=False)
    if r.status_code >= 400:
        raise ValueError(f"ElevenLabs {r.status_code} : {r.text[:200]}")
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
    nom_origine = nom
    fournisseur = v.get("fournisseur", "openai")
    if fournisseur == "aucune" or not texte.strip():
        return None
    try:
        from . import ecoute

        ecoute.memoriser_dit(texte)  # pour ne pas prendre sa propre voix pour la vôtre
    except Exception:  # noqa: BLE001
        pass
    # Clé ElevenLabs présente → George (ou la voix choisie) d'office, OpenAI en secours
    if fournisseur == "openai" and cfg.secret("elevenlabs_api_key") and v.get("auto_elevenlabs", True):
        fournisseur = "elevenlabs"
    voix_el = v.get("elevenlabs_voix") or GEORGE
    modele_el = v.get("elevenlabs_modele") or "eleven_turbo_v2_5"
    if modele_el in _MODELES_REFUSES:
        modele_el = "eleven_multilingual_v2"
    suffixe = f"-el-{voix_el[:6]}-{modele_el.replace('eleven_', '')[:12]}" if fournisseur == "elevenlabs" else ""
    nom = (nom or hashlib.sha1(f"{fournisseur}{v}{texte}".encode()).hexdigest()[:16]) + suffixe
    dossier = dossier_audio(cfg)

    if fournisseur == "elevenlabs":
        cle = cfg.secret("elevenlabs_api_key")
        if cle:
            sortie = dossier / f"{nom}.mp3"
            if sortie.exists() and sortie.stat().st_size > 1000:
                return sortie
            import logging

            reglages = {"stability": .7, "similarity_boost": .85, "style": .15, "use_speaker_boost": True}
            modele = modele_el
            refus = cfg.dossier / "voix_refusees.txt"  # voix refusées par ElevenLabs : mémorisées, plus jamais réessayées
            if refus.exists():
                _VOIX_REFUSEES.update(refus.read_text().split())
            if _time.time() > _ELEVEN_PAUSE["jusqua"]:
                for vid in [x for x in dict.fromkeys([voix_el, GEORGE]) if x not in _VOIX_REFUSEES]:
                    try:
                        return elevenlabs_tts(cle, vid, texte, sortie, modele, reglages)
                    except Exception as exc:  # noqa: BLE001
                        m = str(exc).lower()
                        if modele != "eleven_multilingual_v2" and "model" in m and any(c in m for c in ("400", "404", "422")):
                            _MODELES_REFUSES.add(modele)  # modèle rapide indisponible : modèle classique, même voix
                            return synthetiser(cfg, texte, nom=nom_origine)
                        logging.getLogger("jarvis.voix").warning("ElevenLabs (voix %s) refusée : %s", vid, m[:200])
                        if "quota" in m or "401" in m:
                            _ELEVEN_PAUSE["jusqua"] = _time.time() + 6 * 3600  # crédit épuisé : OpenAI pour 6 h, sans mélanger
                            break
                        if "402" in m or "403" in m or "free" in m or "not found" in m or "404" in m:
                            _VOIX_REFUSEES.add(vid)  # voix inutilisable : on n'y revient plus
                            try:
                                refus.write_text("\n".join(sorted(_VOIX_REFUSEES)))
                            except OSError:
                                pass
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


_AFPLAY = {"n": 0, "fin": -1e9}


def parle_sur_le_mac() -> bool:
    """Vrai pendant qu'une phrase est jouée directement par le Mac (et 2,5 s après, le temps de l'écho)."""
    return _AFPLAY["n"] > 0 or _time.monotonic() - _AFPLAY["fin"] < 2.5


def jouer(fichier: Path, attendre: bool = False) -> None:
    """Joue un fichier audio sur les haut-parleurs du Mac (sans navigateur).
    Pendant la lecture, Jarvis sait qu'il parle : le clap-clap ne réagit pas à sa propre voix."""
    from . import ecoute, son_mac

    if son_mac.actif():  # par le moteur avec annulation d'écho : il ne s'entend pas lui-même
        try:
            num = son_mac.MOTEUR.jouer(Path(fichier))
            _AFPLAY["n"] += 1
            ecoute.lecture_commence(fichier)

            def attendre_moteur():
                t0 = _time.monotonic()
                while son_mac.MOTEUR.id == num and not son_mac.MOTEUR.fini and _time.monotonic() - t0 < 300:
                    _time.sleep(.05)
                _AFPLAY["n"] -= 1
                _AFPLAY["fin"] = _time.monotonic()

            if attendre:
                attendre_moteur()
            else:
                _threading.Thread(target=attendre_moteur, daemon=True).start()
            return
        except Exception:  # noqa: BLE001
            pass  # on retombe sur afplay
    if not (platform.system() == "Darwin" and shutil.which("afplay")):
        return

    p = subprocess.Popen(["afplay", str(fichier)])
    _AFPLAY["n"] += 1
    ecoute.lecture_commence(fichier)

    def attendre_fin():
        try:
            p.wait(timeout=300)
        except Exception:  # noqa: BLE001
            p.kill()
        _AFPLAY["n"] -= 1
        _AFPLAY["fin"] = _time.monotonic()
        ecoute.lecture_fin()

    if attendre:
        attendre_fin()
    else:
        _threading.Thread(target=attendre_fin, daemon=True).start()


def notifier(titre: str, message: str) -> None:
    if platform.system() == "Darwin":
        msg = message.replace('"', "'")[:200]
        subprocess.Popen(["osascript", "-e",
                          f'display notification "{msg}" with title "{titre}" sound name "Glass"'])


def nettoyer(cfg, garder: int = 200) -> None:
    fichiers = sorted(dossier_audio(cfg).iterdir(), key=lambda p: p.stat().st_mtime)
    for f in fichiers[:-garder]:
        f.unlink(missing_ok=True)
