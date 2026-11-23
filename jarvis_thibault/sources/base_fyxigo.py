"""Indicateurs Fyxigo depuis la base de données de l'appli.

Chaque indicateur est une requête SQL (définie dans config.toml) qui renvoie
UN nombre. Compatible PostgreSQL (Supabase, Neon, Railway, Render...), MySQL
et SQLite. L'URL de connexion va dans ~/.jarvis/secrets.toml (clé ``base_url``).

Conseil : créez un utilisateur de base en LECTURE SEULE pour Jarvis.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import create_engine, text

_moteurs: Dict[str, Any] = {}


def _moteur(url: str):
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    elif url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url not in _moteurs:
        args: Dict[str, Any] = {}
        if url.startswith("postgresql"):
            args = {"connect_timeout": 10, "options": "-c default_transaction_read_only=on"}
        _moteurs[url] = create_engine(url, pool_pre_ping=True, connect_args=args)
    return _moteurs[url]


def indicateurs_base(url: str, indicateurs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not url:
        raise ValueError("URL de base manquante (base_url dans ~/.jarvis/secrets.toml)")
    out = []
    with _moteur(url).connect() as conn:
        for ind in indicateurs:
            try:
                val = conn.execute(text(ind["sql"])).scalar()
                val = float(val) if val is not None else 0.0
                if val.is_integer():
                    val = int(val)
                out.append({"nom": ind["nom"], "valeur": val,
                            "format": ind.get("format", "nombre"),
                            "panneau": ind.get("panneau", "hier")})
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                out.append({"nom": ind["nom"], "valeur": None, "erreur": str(exc)[:200],
                            "format": ind.get("format", "nombre"),
                            "panneau": ind.get("panneau", "hier")})
    return out


def base(cfg) -> List[Dict[str, Any]]:
    if cfg.demo:
        from .demo import base_demo

        return base_demo()
    b = cfg["fyxigo"]["base"]
    if not b.get("active"):
        return []
    return indicateurs_base(cfg.secret("base_url"), b.get("indicateurs") or [])
