"""Chargement de la configuration (~/.jarvis/config.toml + secrets.toml)."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

DOSSIER = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis")).expanduser()

DEFAUTS: Dict[str, Any] = {
    "moi": {
        "prenom": "Thibault",
        "appellations": ["Monsieur", "Thibault"],
        "ville": "Paris",
        "fuseau": "Europe/Paris",
    },
    "briefing": {
        "heure": "07:00",
        "jours": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
        "lecture_auto": True,
        "notification": True,
        "ouvrir_tableau": True,
    },
    "cerveau": {
        "fournisseur": "ollama",
        "modele": "qwen3.5:9b",
        "url": "",
        "temperature": 0.7,
    },
    "voix": {
        "fournisseur": "openai",
        "modele": "gpt-4o-mini-tts",
        "voix": "onyx",
        "style": "jarvis",
        "effet": "jarvis",
        "consignes": (
            "Parle en français de France, voix grave et posée de majordome "
            "élégant, légèrement amusé, débit naturel."
        ),
        "voix_mac": "Thomas",
    },
    "agenda": {
        "source": "mac",
        "calendriers_ignores": [],
    },
    "fyxigo": {
        "stripe": True,
        "devise": "EUR",
        "taux_commission": 0.30,
        "objectif_commission_mois": 0,
        "objectif_paiements_mois": 0,
        "objectif_clients_mois": 0,
        "fichier_taches": "fyxigo.md",
        "base": {"active": False, "indicateurs": []},
    },
    "ecran": {"forme": "cerveau", "couleurs": "video", "plein_ecran": False, "panneaux": "auto"},
    "rappels": {"avant_rdv": 10},
    "moodle": {"actif": False, "url": ""},
    "bilan": {"actif": True, "heure": "19:30", "lecture_auto": False},
    "ecoute": {"transcription": "gpt-4o-mini-transcribe"},
    "serveur": {"port": 8765},
}


def _fusion(base: Dict[str, Any], ajout: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for cle, val in ajout.items():
        if isinstance(val, dict) and isinstance(out.get(cle), dict):
            out[cle] = _fusion(out[cle], val)
        else:
            out[cle] = val
    return out


@dataclass
class Config:
    data: Dict[str, Any]
    secrets: Dict[str, Any] = field(default_factory=dict)
    dossier: Path = DOSSIER
    demo: bool = False

    def __getitem__(self, cle: str) -> Any:
        return self.data[cle]

    def secret(self, nom: str) -> str:
        env = os.environ.get(nom.upper(), "")
        return env or str(self.secrets.get(nom, "") or "")

    @property
    def dossier_briefings(self) -> Path:
        p = self.dossier / "briefings"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def fichier_taches(self) -> Path:
        p = Path(self.data["fyxigo"]["fichier_taches"]).expanduser()
        p = p if p.is_absolute() else self.dossier / p
        ancien = self.dossier / "fixigo.md"
        if not p.exists() and ancien.exists():
            return ancien  # installation antérieure au changement de nom
        return p


def migrer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Accepte l'ancienne section ``[fixigo]`` (avant le changement de nom en Fyxigo)."""
    data = copy.deepcopy(data)
    ancien = data.pop("fixigo", None)
    if isinstance(ancien, dict):
        data["fyxigo"] = _fusion(ancien, data.get("fyxigo") or {})
    return data


def charger(demo: bool | None = None) -> Config:
    data: Dict[str, Any] = {}
    secrets: Dict[str, Any] = {}
    fc = DOSSIER / "config.toml"
    fs = DOSSIER / "secrets.toml"
    if fc.exists():
        data = migrer(tomllib.loads(fc.read_text(encoding="utf-8")))
    if fs.exists():
        secrets = tomllib.loads(fs.read_text(encoding="utf-8"))
    if demo is None:
        demo = os.environ.get("JARVIS_DEMO", "") not in ("", "0")
    return Config(data=_fusion(DEFAUTS, data), secrets=secrets, dossier=DOSSIER, demo=demo)
