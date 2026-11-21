"""La « vie » de Jarvis : événements en direct, mémoire, rappels et veilles.

- Événements : chaque chose qui se passe (paiement Stripe, nouveau client, rappel,
  rendez-vous imminent, tâche ajoutée…) est publiée ici ; l'écran les affiche en
  direct (notification + éclat dans le cerveau) et Jarvis peut les dire à voix haute.
- Mémoire : ce que Thibault demande de retenir (« souviens-toi que… »).
- Rappels : « rappelle-moi à 15 h de… ».
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("jarvis.vie")


# --------------------------------------------------------------------------- #
# Événements
# --------------------------------------------------------------------------- #

class Evenements:
    def __init__(self, taille: int = 200):
        self._file: Deque[Dict[str, Any]] = deque(maxlen=taille)
        self._id = 0
        self._verrou = threading.Lock()

    def publier(self, type_: str, titre: str, texte: str = "", region: str = "",
                dire: Optional[str] = None) -> Dict[str, Any]:
        with self._verrou:
            self._id += 1
            e = {"id": self._id, "type": type_, "titre": titre, "texte": texte,
                 "region": region, "dire": dire, "ts": time.time()}
            self._file.append(e)
        log.info("Événement %s : %s %s", type_, titre, texte)
        return e

    def depuis(self, ident: int) -> List[Dict[str, Any]]:
        with self._verrou:
            return [e for e in self._file if e["id"] > ident]

    @property
    def dernier_id(self) -> int:
        return self._id


# --------------------------------------------------------------------------- #
# Petits fichiers JSON / Markdown
# --------------------------------------------------------------------------- #

def _lire_json(p: Path, defaut):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defaut


def _ecrire_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.casefold()) if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- #
# Mémoire
# --------------------------------------------------------------------------- #

class Memoire:
    def __init__(self, fichier: Path):
        self.fichier = fichier

    def lire(self) -> List[str]:
        if not self.fichier.exists():
            return []
        return [l[2:].strip() for l in self.fichier.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]

    def ajouter(self, texte: str) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        if not self.fichier.exists():
            self.fichier.write_text("# Ce que Jarvis sait de vous\n\n", encoding="utf-8")
        with self.fichier.open("a", encoding="utf-8") as f:
            f.write(f"- {texte.strip()} ({datetime.now():%d/%m/%Y})\n")

    def oublier(self, mots: str) -> bool:
        cle = sans_accents(mots)
        lignes = self.fichier.read_text(encoding="utf-8").splitlines() if self.fichier.exists() else []
        garde = [l for l in lignes if not (l.startswith("- ") and cle and cle in sans_accents(l))]
        if len(garde) == len(lignes):
            return False
        self.fichier.write_text("\n".join(garde) + "\n", encoding="utf-8")
        return True


# --------------------------------------------------------------------------- #
# Rappels
# --------------------------------------------------------------------------- #

class Rappels:
    def __init__(self, fichier: Path, fuseau: str):
        self.fichier = fichier
        self.tz = ZoneInfo(fuseau)

    def lire(self) -> List[Dict[str, Any]]:
        return _lire_json(self.fichier, [])

    def ajouter(self, heure: str, texte: str) -> Dict[str, Any]:
        m = re.match(r"\s*(\d{1,2})\s*[:hH.]?\s*(\d{2})?", heure)
        if not m:
            raise ValueError(f"heure illisible : {heure!r}")
        now = datetime.now(self.tz)
        quand = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2) or 0), second=0, microsecond=0)
        if quand <= now:
            quand += timedelta(days=1)
        r = {"id": int(time.time() * 1000), "quand": quand.isoformat(timespec="minutes"), "texte": texte.strip(), "fait": False}
        tous = self.lire()
        tous.append(r)
        _ecrire_json(self.fichier, tous)
        return r

    def a_declencher(self) -> List[Dict[str, Any]]:
        now = datetime.now(self.tz)
        tous, dus = self.lire(), []
        for r in tous:
            if not r.get("fait") and datetime.fromisoformat(r["quand"]) <= now:
                r["fait"] = True
                dus.append(r)
        if dus:
            # on garde les 50 derniers rappels passés
            faits = [r for r in tous if r.get("fait")][-50:]
            _ecrire_json(self.fichier, [r for r in tous if not r.get("fait")] + faits)
        return dus

    def a_venir(self) -> List[Dict[str, Any]]:
        return sorted((r for r in self.lire() if not r.get("fait")), key=lambda r: r["quand"])


# --------------------------------------------------------------------------- #
# Veilles (threads de fond)
# --------------------------------------------------------------------------- #

def veille_rendez_vous(etat, ev: Evenements, annonces: set) -> None:
    """Annonce les rendez-vous X minutes avant (X = [rappels] avant_rdv)."""
    cfg = etat.cfg
    avant = int(cfg["rappels"].get("avant_rdv", 10) or 0)
    if avant <= 0:
        return
    agenda = (etat.donnees or {}).get("agenda") or {}
    tz = ZoneInfo(cfg["moi"]["fuseau"])
    now = datetime.now(tz)
    appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
    for e in agenda.get("aujourdhui", []):
        if e.get("journee") or not e.get("debut"):
            continue
        h, m = (int(x) for x in e["debut"].split(":"))
        debut = now.replace(hour=h, minute=m, second=0, microsecond=0)
        reste = (debut - now).total_seconds() / 60
        cle = f"{now.date()}-{e['debut']}-{e['titre']}"
        if 0 < reste <= avant and cle not in annonces:
            annonces.add(cle)
            lieu = f", {e['lieu']}" if e.get("lieu") else ""
            minutes = max(1, round(reste))
            ev.publier("rdv", e["titre"], f"dans {minutes} min{lieu}", "agenda",
                       dire=f"{appel}, {e['titre']} commence dans {minutes} minutes{lieu}.")


def veille_rappels(etat, ev: Evenements, rappels: Rappels) -> None:
    appel = (etat.cfg["moi"]["appellations"] or ["Monsieur"])[0]
    for r in rappels.a_declencher():
        ev.publier("rappel", "Rappel", r["texte"], "memoire", dire=f"{appel}, petit rappel : {r['texte']}.")


class VeilleStripe:
    """Interroge Stripe toutes les 2 minutes pour annoncer paiements et nouveaux clients."""

    def __init__(self, etat, ev: Evenements):
        self.etat, self.ev = etat, ev
        self.depuis = int(time.time())
        self.vus: set = set()
        self.prochaine = 0.0

    def tic(self) -> None:
        cfg = self.etat.cfg
        if time.time() < self.prochaine or cfg.demo or not cfg["fixigo"].get("stripe") or not cfg.secret("stripe_api_key"):
            return
        self.prochaine = time.time() + 120
        from .sources.stripe_fixigo import nouveautes

        try:
            n = nouveautes(cfg.secret("stripe_api_key"), self.depuis - 5, cfg["fixigo"]["devise"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Veille Stripe : %s", exc)
            return
        appel = (cfg["moi"]["appellations"] or ["Monsieur"])[0]
        nouveau = False
        for p in n["paiements"]:
            if p["id"] in self.vus:
                continue
            self.vus.add(p["id"])
            nouveau = True
            montant = f"{p['montant']:.2f}".replace(".00", "").replace(".", ",")
            self.ev.publier("paiement", "Nouveau paiement", f"+{montant} €", "stripe",
                            dire=f"Ka-tching, {appel} : {montant} euros viennent de tomber.")
        for p in n["echecs"]:
            if p["id"] in self.vus:
                continue
            self.vus.add(p["id"])
            self.ev.publier("echec", "Paiement échoué", f"{p['montant']:.0f} €", "stripe")
        for c in n["clients"]:
            if c["id"] in self.vus:
                continue
            self.vus.add(c["id"])
            nouveau = True
            self.ev.publier("client", "Nouveau client Fixigo", "bienvenue à bord", "mrr",
                            dire=f"{appel}, un nouveau client vient de rejoindre Fixigo.")
        if nouveau:
            threading.Thread(target=self.etat.rafraichir, kwargs={"force": True}, daemon=True).start()


class VeilleDemo:
    """En mode démo : un faux paiement de temps en temps, pour voir l'écran s'animer."""

    def __init__(self, ev: Evenements):
        self.ev, self.prochaine = ev, time.time() + 25

    def tic(self) -> None:
        if time.time() < self.prochaine:
            return
        import random

        self.prochaine = time.time() + random.randint(40, 90)
        m = random.choice([29, 49, 79, 120, 240])
        self.ev.publier("paiement", "Nouveau paiement", f"+{m} €", "stripe")


def veille_devoirs(etat, ev: Evenements, annonces: set) -> None:
    """Annonce une fois chaque devoir Moodle à rendre dans moins de 24 h."""
    mo = (etat.donnees or {}).get("moodle") or {}
    tz = ZoneInfo(etat.cfg["moi"]["fuseau"])
    now = datetime.now(tz)
    appel = (etat.cfg["moi"]["appellations"] or ["Monsieur"])[0]
    for d in mo.get("devoirs") or []:
        q = datetime.fromisoformat(d["echeance"])
        heures = (q - now).total_seconds() / 3600
        cle = f"devoir-{d['titre']}-{d['echeance']}"
        if 0 < heures <= 24 and cle not in annonces and 8 <= now.hour < 22:
            annonces.add(cle)
            quand = "ce soir" if q.date() == now.date() and q.hour >= 17 else ("aujourd'hui" if q.date() == now.date() else "demain")
            ev.publier("devoir", f"Devoir · {d.get('cours') or 'Moodle'}", f"{d['titre']} — {quand} {q:%H:%M}", "moodle",
                       dire=f"{appel}, petit rappel scolaire : {d['titre']} est à rendre {quand} à {q.hour} heures {q.minute:02d}.".replace(" 00.", "."))
