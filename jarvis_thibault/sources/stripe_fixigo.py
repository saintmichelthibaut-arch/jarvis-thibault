"""Chiffres Fixigo depuis Stripe (lecture seule).

Utilisez une **clé restreinte** (rk_live_...) avec uniquement les droits de
lecture : Charges, Customers, Subscriptions (Stripe → Développeurs → Clés API →
Créer une clé restreinte).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from typing import Any, Dict, Iterator, Optional
from zoneinfo import ZoneInfo

import httpx

API = "https://api.stripe.com/v1"

# Devises sans centimes (montants Stripe déjà en unités).
_SANS_DECIMALES = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
                   "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}


def _unites(montant: int, devise: str) -> float:
    return montant if devise.lower() in _SANS_DECIMALES else montant / 100


def mensualiser(montant: float, intervalle: str, nb: int) -> float:
    nb = max(int(nb or 1), 1)
    facteur = {"day": 365 / 12, "week": 52 / 12, "month": 1, "year": 1 / 12}.get(intervalle, 1)
    return montant * facteur / nb


class Stripe:
    def __init__(self, cle: str, transport: Optional[httpx.BaseTransport] = None):
        if not cle:
            raise ValueError("Clé Stripe manquante (stripe_api_key dans ~/.jarvis/secrets.toml)")
        self._c = httpx.Client(base_url=API, auth=(cle, ""), timeout=30, transport=transport)

    def lister(self, chemin: str, params: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        params = {**params, "limit": 100}
        for _ in range(200):  # garde-fou : 20 000 objets max
            r = self._c.get(chemin, params=params)
            if r.status_code == 401:
                raise PermissionError("Clé Stripe refusée (401) : vérifiez stripe_api_key")
            r.raise_for_status()
            j = r.json()
            data = j.get("data") or []
            yield from data
            if not j.get("has_more") or not data:
                return
            params["starting_after"] = data[-1]["id"]


def chiffres_stripe(cle: str, fuseau: str, devise: str = "EUR",
                    maintenant: Optional[datetime] = None,
                    transport: Optional[httpx.BaseTransport] = None) -> Dict[str, Any]:
    tz = ZoneInfo(fuseau)
    now = maintenant or datetime.now(tz)
    jour = datetime.combine(now.date(), time.min, tzinfo=tz)
    hier = jour - timedelta(days=1)
    il_y_a_7j = jour - timedelta(days=7)
    debut_mois = jour.replace(day=1)
    debut_mois_prec = (debut_mois - timedelta(days=1)).replace(day=1)
    devise = devise.lower()
    s = Stripe(cle, transport)

    # --- Chiffre d'affaires (paiements réussis, nets des remboursements) ---
    il_y_a_14j = jour - timedelta(days=13)
    depuis = min(il_y_a_14j, debut_mois_prec)
    ca = Counter()
    par_jour: Counter = Counter()
    derniers = []
    echecs_7j = 0
    for ch in s.lister("/charges", {"created[gte]": int(depuis.timestamp())}):
        if ch.get("currency", "").lower() != devise:
            continue
        quand = datetime.fromtimestamp(ch["created"], tz)
        if ch.get("status") == "failed":
            if quand >= il_y_a_7j:
                echecs_7j += 1
            continue
        if ch.get("status") != "succeeded" or not ch.get("paid"):
            continue
        net = _unites(ch["amount"] - ch.get("amount_refunded", 0), devise)
        if quand >= il_y_a_14j:
            par_jour[quand.date().isoformat()] += net
        derniers.append((ch["created"], net))
        if quand >= jour:
            ca["aujourdhui"] += net
        elif quand >= hier:
            ca["hier"] += net
        if il_y_a_7j <= quand < jour:
            ca["7j"] += net
        if quand >= debut_mois:
            ca["mois"] += net
        elif quand >= debut_mois_prec and quand.day <= now.day:
            # même période le mois dernier, pour comparer
            ca["mois_prec_meme_periode"] += net

    # --- Nouveaux clients ---
    clients = Counter()
    for cu in s.lister("/customers", {"created[gte]": int(min(il_y_a_7j, debut_mois).timestamp())}):
        quand = datetime.fromtimestamp(cu["created"], tz)
        if quand >= jour:
            clients["aujourdhui"] += 1
        elif quand >= hier:
            clients["hier"] += 1
        if il_y_a_7j <= quand < jour:
            clients["7j"] += 1
        if quand >= debut_mois:
            clients["mois"] += 1

    # --- MRR (abonnements actifs, hors remises) ---
    mrr = 0.0
    actifs = 0
    for sub in s.lister("/subscriptions", {"status": "active"}):
        actifs += 1
        for it in (sub.get("items") or {}).get("data", []):
            prix = it.get("price") or it.get("plan") or {}
            rec = prix.get("recurring") or {
                "interval": prix.get("interval"), "interval_count": prix.get("interval_count")
            }
            if (prix.get("currency") or "").lower() != devise:
                continue
            unitaire = prix.get("unit_amount")
            if unitaire is None:
                unitaire = float(prix.get("unit_amount_decimal") or prix.get("amount") or 0)
            montant = _unites(unitaire, devise) * (it.get("quantity") or 1)
            mrr += mensualiser(montant, rec.get("interval") or "month", rec.get("interval_count") or 1)
    essais = sum(1 for _ in s.lister("/subscriptions", {"status": "trialing"}))

    r2 = lambda x: round(x, 2)  # noqa: E731
    jours = [(il_y_a_14j + timedelta(days=i)).date().isoformat() for i in range(14)]
    derniers.sort(reverse=True)
    return {
        "devise": devise.upper(),
        "ca_aujourdhui": r2(ca["aujourdhui"]),
        "ca_hier": r2(ca["hier"]),
        "ca_7j": r2(ca["7j"]),
        "ca_mois": r2(ca["mois"]),
        "ca_mois_prec_meme_periode": r2(ca["mois_prec_meme_periode"]),
        "nouveaux_clients_aujourdhui": clients["aujourdhui"],
        "nouveaux_clients_hier": clients["hier"],
        "nouveaux_clients_7j": clients["7j"],
        "nouveaux_clients_mois": clients["mois"],
        "mrr": r2(mrr),
        "abonnements_actifs": actifs,
        "essais_en_cours": essais,
        "paiements_echoues_7j": echecs_7j,
        "ca_jours": [{"jour": j, "montant": r2(par_jour[j])} for j in jours],
        "derniers_paiements": [{"quand": datetime.fromtimestamp(t, tz).isoformat(timespec="minutes"), "montant": r2(m)}
                               for t, m in derniers[:5]],
    }


def nouveautes(cle: str, depuis_ts: int, devise: str = "EUR",
               transport: Optional[httpx.BaseTransport] = None) -> Dict[str, Any]:
    """Paiements, échecs et clients apparus après ``depuis_ts`` (pour les alertes en direct)."""
    s = Stripe(cle, transport)
    devise = devise.lower()
    paiements, echecs = [], []
    for ch in s.lister("/charges", {"created[gt]": int(depuis_ts)}):
        if ch.get("currency", "").lower() != devise:
            continue
        net = _unites(ch["amount"] - ch.get("amount_refunded", 0), devise)
        if ch.get("status") == "succeeded" and ch.get("paid"):
            paiements.append({"id": ch["id"], "montant": round(net, 2), "ts": ch["created"]})
        elif ch.get("status") == "failed":
            echecs.append({"id": ch["id"], "montant": round(_unites(ch["amount"], devise), 2), "ts": ch["created"]})
    clients = [{"id": c["id"], "ts": c["created"]} for c in s.lister("/customers", {"created[gt]": int(depuis_ts)})]
    return {"paiements": paiements, "echecs": echecs, "clients": clients}


def stripe(cfg) -> Dict[str, Any]:
    if cfg.demo:
        from .demo import stripe_demo

        return stripe_demo()
    return chiffres_stripe(cfg.secret("stripe_api_key"), cfg["moi"]["fuseau"],
                           cfg["fixigo"]["devise"])
