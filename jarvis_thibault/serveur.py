"""Serveur local de Jarvis : écran, conversation, briefing/bilan programmés, veilles en direct."""

from __future__ import annotations

import logging
import re
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import cerveau, voix
from .config import Config, charger
from .sources import taches as mod_taches
from .vie import (Evenements, Memoire, Rappels, VeilleDemo, VeilleStripe, sans_accents, veille_devoirs, veille_rappels,
                  veille_rendez_vous)

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
        self.ev = Evenements()
        self.memoire = Memoire(cfg.dossier / ("demo/memoire.md" if cfg.demo else "memoire.md"))
        self.rappels = Rappels(cfg.dossier / ("demo/rappels.json" if cfg.demo else "rappels.json"), cfg["moi"]["fuseau"])

    def rafraichir(self, force: bool = False) -> Dict[str, Any]:
        with self.verrou:
            if force or time.time() - self.maj > 600 or not self.donnees:
                self.donnees = cerveau.collecter(self.cfg)
                self.maj = time.time()
            return self.donnees


def appellation(cfg: Config) -> str:
    return (cfg["moi"]["appellations"] or ["Monsieur"])[0]


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


def lancer_briefing(etat: Etat, lire_sur_mac: bool = False, type_: str = "briefing") -> Dict[str, Any]:
    """Prépare le briefing du matin (ou le bilan du soir), sa voix, et le publie."""
    cfg = etat.cfg
    with cerveau.VERROU_BRIEFING:
        etat.statut = "briefing"
        try:
            d = etat.rafraichir(force=True)
            b = cerveau.bilan(cfg, d) if type_ == "bilan" else cerveau.briefing(cfg, d)
            b["type"] = type_
            audio = None
            try:
                audio = voix.synthetiser(cfg, b["texte"], nom=f"{type_}-{b['horodatage'][:10]}")
            except Exception as exc:  # noqa: BLE001
                log.warning("Voix indisponible : %s", exc)
                b["erreur_voix"] = expliquer_erreur(exc)
            b["audio"] = _url_audio(audio)
            cerveau.sauver_briefing(cfg, b)
            etat.ev.publier(type_, "Briefing du matin" if type_ == "briefing" else "Bilan du soir", "prêt", "raison")
            if lire_sur_mac and audio:
                voix.jouer(audio)
            return b
        finally:
            etat.statut = "veille"


def lire_heure(texte: str) -> tuple[int, int]:
    """Comprend « 08:00 », « 8h », « 8h30 », « 8 », « 8.30 »."""
    m = re.match(r"\s*(\d{1,2})\s*(?:[:hH.]\s*(\d{1,2})?)?\s*$", str(texte))
    if not m:
        raise ValueError(f"Heure illisible : {texte!r} (exemple : 08:00)")
    h, mn = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h < 24 and 0 <= mn < 60):
        raise ValueError(f"Heure invalide : {texte!r}")
    return h, mn


def ouvrir_ecran(cfg: Config) -> None:
    """Ouvre l'écran de Jarvis (l'app Jarvis sur Mac) ou, à défaut, le navigateur."""
    import platform
    import subprocess

    lancer = cfg.dossier / "app" / "lancer.sh"
    if platform.system() == "Darwin" and lancer.exists():
        subprocess.Popen(["/bin/bash", str(lancer)])
    else:
        webbrowser.open(f"http://localhost:{cfg['serveur']['port']}/")


def _planificateur(etat: Etat) -> None:
    """Briefing du matin, bilan du soir, rappels, rendez-vous imminents, veille Stripe."""
    cfg = etat.cfg
    faits: Dict[str, str] = {}
    annonces: set = set()
    stripe = VeilleStripe(etat, etat.ev)
    demo = VeilleDemo(etat.ev) if cfg.demo else None
    while True:
        try:
            now = datetime.now(ZoneInfo(cfg["moi"]["fuseau"]))
            jour = now.date().isoformat()
            # Briefing du matin
            bcfg = cfg["briefing"]
            dernier = cerveau.dernier_briefing(cfg, "briefing")
            if dernier and dernier["horodatage"][:10] == jour:
                faits["briefing"] = jour
            h, m = lire_heure(bcfg["heure"])
            if (faits.get("briefing") != jour and (now.hour, now.minute) >= (h, m) and now.hour < 12
                    and _JOURS[now.weekday()] in bcfg["jours"]):
                faits["briefing"] = jour
                log.info("Briefing du matin…")
                b = lancer_briefing(etat, lire_sur_mac=bcfg.get("lecture_auto", True))
                if bcfg.get("notification", True):
                    voix.notifier("Jarvis", b["texte"][:180])
                if bcfg.get("ouvrir_tableau", True):
                    ouvrir_ecran(cfg)
            # Bilan du soir
            soir = cfg["bilan"]
            if soir.get("actif"):
                dernier = cerveau.dernier_briefing(cfg, "bilan")
                if dernier and dernier["horodatage"][:10] == jour:
                    faits["bilan"] = jour
                h, m = lire_heure(soir.get("heure", "19:30"))
                if faits.get("bilan") != jour and (now.hour, now.minute) >= (h, m) and now.hour < 23:
                    faits["bilan"] = jour
                    log.info("Bilan du soir…")
                    b = lancer_briefing(etat, lire_sur_mac=soir.get("lecture_auto", False), type_="bilan")
                    voix.notifier("Jarvis · bilan du soir", b["texte"][:180])
            # Veilles
            veille_rappels(etat, etat.ev, etat.rappels)
            veille_rendez_vous(etat, etat.ev, annonces)
            veille_devoirs(etat, etat.ev, annonces)
            stripe.tic()
            if demo:
                demo.tic()
            if now.minute == 0 and now.second < 20:
                voix.nettoyer(cfg)
                threading.Thread(target=etat.rafraichir, kwargs={"force": True}, daemon=True).start()
        except Exception:  # noqa: BLE001
            log.exception("Erreur du planificateur")
        time.sleep(15)


class Message(BaseModel):
    message: str
    historique: List[Dict[str, str]] = []
    voix: bool = True


class Texte(BaseModel):
    texte: str


def executer_actions(etat: Etat, actions: List[tuple]) -> List[Dict[str, Any]]:
    """Exécute les balises d'action renvoyées par le cerveau."""
    cfg, faites = etat.cfg, []
    fichier = _fichier_taches(cfg)
    for nom, arg in actions:
        try:
            if nom == "AJOUT_TACHE" and arg:
                mod_taches.ajouter(fichier, arg)
                faites.append(etat.ev.publier("tache", "Tâche ajoutée", arg.lstrip("! "), "priorites"))
            elif nom == "TACHE_FAITE" and arg:
                mots = [w for w in sans_accents(arg).split() if len(w) > 2]
                for t in mod_taches.lire(fichier)["taches"]:
                    if not t["fait"] and mots and all(w in sans_accents(t["texte"]) for w in mots[:3]):
                        mod_taches.basculer(fichier, t["ligne"])
                        faites.append(etat.ev.publier("tache_faite", "Tâche terminée", t["texte"], "priorites"))
                        break
            elif nom == "MEMOIRE" and arg:
                etat.memoire.ajouter(arg)
                faites.append(etat.ev.publier("memoire", "Mémorisé", arg, "memoire"))
            elif nom == "OUBLIE" and arg:
                if etat.memoire.oublier(arg):
                    faites.append(etat.ev.publier("memoire", "Oublié", arg, "memoire"))
            elif nom == "RAPPEL" and arg:
                heure, _, texte = arg.partition("|")
                r = etat.rappels.ajouter(heure.strip(), texte.strip() or "rappel")
                faites.append(etat.ev.publier("rappel_prog", f"Rappel à {r['quand'][11:16]}", r["texte"], "memoire"))
            elif nom in ("BRIEFING", "BILAN"):
                faites.append({"type": "lancer", "quoi": nom.lower()})
        except Exception as exc:  # noqa: BLE001
            log.warning("Action %s impossible : %s", nom, exc)
    if any(a.get("type") in ("tache", "tache_faite", "memoire", "rappel_prog") for a in faites):
        etat.rafraichir(force=True)
    return faites


def creer_app(cfg: Optional[Config] = None, planifier: bool = True) -> FastAPI:
    cfg = cfg or charger()
    etat = Etat(cfg)
    app = FastAPI(title="Jarvis")
    app.state.etat = etat

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
            "moi": {"prenom": cfg["moi"]["prenom"], "appellation": appellation(cfg)},
            "donnees": d,
            "objectifs": d.get("objectifs_chiffres"),
            "briefing": cerveau.dernier_briefing(cfg),
            "statut": etat.statut,
            "cerveau": f"{cfg['cerveau']['fournisseur']} · {cfg['cerveau']['modele']}",
            "ecran": cfg["ecran"],
            "voix": {"fournisseur": cfg["voix"]["fournisseur"], "effet": cfg["voix"].get("effet", "jarvis"),
                     "realiste": cfg["voix"]["fournisseur"] == "openai" and bool(cfg.secret("openai_api_key"))},
            "transcription": bool(cfg.secret("openai_api_key")),
            "dernier_evenement": etat.ev.dernier_id,
            "demo": cfg.demo,
        }

    @app.get("/api/evenements")
    def api_evenements(depuis: int = 0):
        return {"dernier": etat.ev.dernier_id, "evenements": etat.ev.depuis(depuis)}

    def _lancer(type_: str):
        if cerveau.VERROU_BRIEFING.locked():
            raise HTTPException(409, "Briefing déjà en cours")
        try:
            return lancer_briefing(etat, type_=type_)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s impossible", type_)
            raise HTTPException(500, expliquer_erreur(exc)) from exc

    @app.post("/api/briefing")
    def api_briefing():
        return _lancer("briefing")

    @app.post("/api/bilan")
    def api_bilan():
        return _lancer("bilan")

    @app.post("/api/parler")
    def api_parler(m: Message):
        etat.statut = "reflexion"
        try:
            # 1) commandes reconnues à coup sûr (rappel, mémoire, tâche…) : exécutées tout de suite
            sures = cerveau.intentions(m.message, cfg["moi"]["fuseau"])
            faites = executer_actions(etat, sures)
            message = m.message
            if faites:
                resume = "; ".join(f"{a.get('titre', a.get('quoi', ''))} : {a.get('texte', '')}".strip(" :") for a in faites)
                message += f"\n\n(Note du système : c'est DÉJÀ fait → {resume}. Confirme-le simplement, sans balise.)"
            try:
                rep = cerveau.repondre(cfg, message, m.historique, etat.rafraichir())
            except Exception as exc:  # noqa: BLE001
                log.exception("Cerveau indisponible")
                if faites:
                    return {"reponse": f"C'est fait, {appellation(cfg)}.", "audio": None, "actions": faites,
                            "erreur": expliquer_erreur(exc)}
                return {"reponse": f"Mon cerveau ne répond pas, {appellation(cfg)}.", "erreur": expliquer_erreur(exc),
                        "audio": None, "actions": []}
            # 2) balises éventuelles du modèle (sans refaire ce qui est déjà fait)
            actions, rep = cerveau.extraire_actions(rep)
            deja = {n for n, _ in sures}
            faites += executer_actions(etat, [(n, a) for n, a in actions if n not in deja])
            rep = rep or f"C'est fait, {appellation(cfg)}."
            audio = None
            if m.voix:
                try:
                    audio = voix.synthetiser(cfg, rep)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Voix indisponible : %s", exc)
            return {"reponse": rep, "audio": _url_audio(audio), "actions": faites,
                    "tache_ajoutee": next((a["texte"] for a in faites if a.get("type") == "tache"), None)}
        finally:
            etat.statut = "veille"

    @app.post("/api/dire")
    def api_dire(t: Texte):
        try:
            return {"audio": _url_audio(voix.synthetiser(cfg, t.texte[:600]))}
        except Exception as exc:  # noqa: BLE001
            return {"audio": None, "erreur": expliquer_erreur(exc)}

    @app.post("/api/transcrire")
    async def api_transcrire(audio: UploadFile = File(...)):
        donnees = await audio.read()
        if len(donnees) < 2000:
            return {"texte": ""}
        cle = cfg.secret("openai_api_key")
        if not cle:
            raise HTTPException(400, "La reconnaissance vocale a besoin d'une clé OpenAI (ajouter-cle.sh).")
        from openai import OpenAI

        client = OpenAI(api_key=cle)
        nom = audio.filename or "voix.webm"
        for modele in (cfg["ecoute"].get("transcription") or "gpt-4o-mini-transcribe", "whisper-1"):
            try:
                r = client.audio.transcriptions.create(model=modele, file=(nom, donnees), language="fr")
                return {"texte": (r.text or "").strip()}
            except Exception as exc:  # noqa: BLE001
                log.warning("Transcription (%s) : %s", modele, exc)
                erreur = exc
        raise HTTPException(500, expliquer_erreur(erreur))

    @app.post("/api/taches/{ligne}/basculer")
    def api_basculer(ligne: int):
        fichier = _fichier_taches(cfg)
        fait = mod_taches.basculer(fichier, ligne)
        etat.rafraichir(force=True)
        if fait:
            etat.ev.publier("tache_faite", "Tâche terminée", "", "priorites")
        return {"fait": fait}

    @app.post("/api/taches")
    def api_ajouter(t: Texte):
        mod_taches.ajouter(_fichier_taches(cfg), t.texte)
        etat.rafraichir(force=True)
        etat.ev.publier("tache", "Tâche ajoutée", t.texte, "priorites")
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


__all__ = ["creer_app", "demarrer", "lancer_briefing", "lire_heure"]
