"""Serveur local de Jarvis : tableau de bord, conversation, briefing programmé."""

from __future__ import annotations

import logging
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import cerveau, voix
from .config import Config, charger
from .sources import taches as mod_taches

log = logging.getLogger("jarvis")
STATIC = Path(__file__).parent / "static"
_JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


class Etat:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.donnees: Dict[str, Any] = {}
        self.maj = 0.0
        self.statut = "veille"  # veille | briefing | reflexion | parole
        self.verrou = threading.Lock()

    def rafraichir(self, force: bool = False) -> Dict[str, Any]:
        with self.verrou:
            if force or time.time() - self.maj > 600 or not self.donnees:
                self.donnees = cerveau.collecter(self.cfg)
                self.maj = time.time()
            return self.donnees


def expliquer_erreur(exc: Exception) -> str:
    """Traduit les erreurs courantes en français compréhensible."""
    t = f"{type(exc).__name__}: {exc}"
    bas = t.lower()
    if "api_key" in bas or "authentication" in bas or "401" in bas or "incorrect api key" in bas:
        return "clé OpenAI absente ou refusée : vérifiez openai_api_key dans ~/.jarvis/secrets.toml"
    if "insufficient_quota" in bas or "quota" in bas or "billing" in bas:
        return "crédit OpenAI épuisé : ajoutez du crédit sur platform.openai.com"
    if "model" in bas and ("not found" in bas or "does not exist" in bas or "404" in bas):
        return f"modèle introuvable ({t[:160]}) : vérifiez « modele » dans ~/.jarvis/config.toml"
    if "connect" in bas or "connection" in bas:
        return "le cerveau est injoignable (Ollama éteint ou pas d'Internet)"
    return t[:300]


def _url_audio(p: Optional[Path]) -> Optional[str]:
    return f"/audio/{p.name}" if p else None


def lancer_briefing(etat: Etat, lire_sur_mac: bool = False) -> Dict[str, Any]:
    cfg = etat.cfg
    with cerveau.VERROU_BRIEFING:
        etat.statut = "briefing"
        try:
            d = etat.rafraichir(force=True)
            b = cerveau.briefing(cfg, d)
            audio = None
            try:
                audio = voix.synthetiser(cfg, b["texte"], nom=f"briefing-{b['horodatage'][:10]}")
            except Exception as exc:  # noqa: BLE001
                log.warning("Voix indisponible : %s", exc)
                b["erreur_voix"] = str(exc)[:200]
            b["audio"] = _url_audio(audio)
            cerveau.sauver_briefing(cfg, b)
            if lire_sur_mac and audio:
                voix.jouer(audio)
            return b
        finally:
            etat.statut = "veille"


def lire_heure(texte: str) -> tuple[int, int]:
    """Comprend « 08:00 », « 8h », « 8h30 », « 8 », « 8.30 »."""
    import re

    m = re.match(r"\s*(\d{1,2})\s*(?:[:hH.]\s*(\d{1,2})?)?\s*$", str(texte))
    if not m:
        raise ValueError(f"Heure du briefing illisible : {texte!r} (exemple : 08:00)")
    h, mn = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h < 24 and 0 <= mn < 60):
        raise ValueError(f"Heure du briefing invalide : {texte!r}")
    return h, mn


def ouvrir_ecran(cfg: Config) -> None:
    """Ouvre l'écran de Jarvis dans sa fenêtre à lui (via lancer.sh) ou, à défaut, le navigateur."""
    import platform
    import subprocess

    lancer = cfg.dossier / "app" / "lancer.sh"
    if platform.system() == "Darwin" and lancer.exists():
        subprocess.Popen(["/bin/bash", str(lancer)])
    else:
        webbrowser.open(f"http://localhost:{cfg['serveur']['port']}/")


def _planificateur(etat: Etat) -> None:
    """Déclenche le briefing chaque matin à l'heure prévue."""
    cfg = etat.cfg
    fait_le = ""
    while True:
        try:
            bcfg = cfg["briefing"]
            now = datetime.now(ZoneInfo(cfg["moi"]["fuseau"]))
            jour = now.date().isoformat()
            dernier = cerveau.dernier_briefing(cfg)
            if dernier and dernier["horodatage"][:10] == jour:
                fait_le = jour
            h, m = lire_heure(bcfg["heure"])
            heure_passee = (now.hour, now.minute) >= (h, m) and now.hour < 12
            if (fait_le != jour and heure_passee and _JOURS[now.weekday()] in bcfg["jours"]):
                fait_le = jour
                log.info("Briefing du matin…")
                b = lancer_briefing(etat, lire_sur_mac=bcfg.get("lecture_auto", True))
                if bcfg.get("notification", True):
                    voix.notifier("Jarvis", b["texte"][:180])
                if bcfg.get("ouvrir_tableau", True):
                    ouvrir_ecran(cfg)
            if now.minute == 0:
                voix.nettoyer(cfg)
        except Exception:  # noqa: BLE001
            log.exception("Erreur du planificateur")
        time.sleep(30)


class Message(BaseModel):
    message: str
    historique: List[Dict[str, str]] = []
    voix: bool = True


class NouvelleTache(BaseModel):
    texte: str


def creer_app(cfg: Optional[Config] = None, planifier: bool = True) -> FastAPI:
    cfg = cfg or charger()
    etat = Etat(cfg)
    app = FastAPI(title="Jarvis")

    if planifier:
        threading.Thread(target=_planificateur, args=(etat,), daemon=True).start()
    threading.Thread(target=etat.rafraichir, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def accueil():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/etat")
    def api_etat(rafraichir: bool = False):
        d = etat.rafraichir(force=rafraichir)
        return {
            "moi": {"prenom": cfg["moi"]["prenom"], "appellation": (cfg["moi"]["appellations"] or ["Monsieur"])[0]},
            "donnees": d,
            "objectifs": d.get("objectifs_chiffres"),
            "briefing": cerveau.dernier_briefing(cfg),
            "statut": etat.statut,
            "cerveau": f"{cfg['cerveau']['fournisseur']} · {cfg['cerveau']['modele']}",
            "demo": cfg.demo,
        }

    @app.post("/api/briefing")
    def api_briefing():
        if cerveau.VERROU_BRIEFING.locked():
            raise HTTPException(409, "Briefing déjà en cours")
        try:
            return lancer_briefing(etat)
        except Exception as exc:  # noqa: BLE001
            log.exception("Briefing impossible")
            raise HTTPException(500, expliquer_erreur(exc)) from exc

    @app.post("/api/parler")
    def api_parler(m: Message):
        etat.statut = "reflexion"
        try:
            try:
                rep = cerveau.repondre(cfg, m.message, m.historique, etat.rafraichir())
            except Exception as exc:  # noqa: BLE001
                log.exception("Cerveau indisponible")
                appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
                return {"reponse": f"Mon cerveau ne répond pas, {appel}.", "erreur": expliquer_erreur(exc),
                        "audio": None, "tache_ajoutee": None}
            tache_ajoutee, rep = cerveau.extraire_ajout_tache(rep)
            if tache_ajoutee:
                mod_taches.ajouter(_fichier_taches(cfg), tache_ajoutee)
                rep = rep or f"C'est noté, {(cfg['moi']['appellations'] or ['Monsieur'])[0]}."
                etat.rafraichir(force=True)
            audio = None
            if m.voix:
                try:
                    audio = voix.synthetiser(cfg, rep)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Voix indisponible : %s", exc)
            return {"reponse": rep, "audio": _url_audio(audio), "tache_ajoutee": tache_ajoutee}
        finally:
            etat.statut = "veille"

    @app.post("/api/taches/{ligne}/basculer")
    def api_basculer(ligne: int):
        fichier = _fichier_taches(cfg)
        fait = mod_taches.basculer(fichier, ligne)
        etat.rafraichir(force=True)
        return {"fait": fait}

    @app.post("/api/taches")
    def api_ajouter(t: NouvelleTache):
        mod_taches.ajouter(_fichier_taches(cfg), t.texte)
        etat.rafraichir(force=True)
        return {"ok": True}

    @app.get("/audio/{nom}")
    def audio(nom: str):
        p = voix.dossier_audio(cfg) / Path(nom).name
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p)

    return app


def _fichier_taches(cfg: Config) -> Path:
    if cfg.demo:
        from .sources.demo import FICHIER_DEMO

        return FICHIER_DEMO()
    return cfg.fichier_taches


def demarrer(port: Optional[int] = None, demo: Optional[bool] = None, ouvrir: bool = False) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = charger(demo=demo)
    port = port or cfg["serveur"]["port"]
    if ouvrir:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}/")).start()
    uvicorn.run(creer_app(cfg), host="127.0.0.1", port=port, log_level="warning")


__all__ = ["creer_app", "demarrer", "lancer_briefing"]
