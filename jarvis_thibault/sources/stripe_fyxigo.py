"""Chiffres Fyxigo depuis Stripe (lecture seule).

Fyxigo est une place de marché : le client paie l'intervention, Fyxigo garde
une commission (30 % par défaut, ``taux_commission`` dans config.toml) et
reverse le reste à l'artisan. Il n'y a pas d'abonnement, donc pas de MRR.

Utilisez une **clé restreinte** (rk_live_...) avec uniquement les droits de
lecture : Charges, Customers, Disputes (Stripe → Développeurs → Clés API →
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


# Litiges (contestations bancaires) encore ouverts.
_LITIGES_OUVERTS = {"needs_response", "warning_needs_response", "under_review", "warning_under_review"}


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
                    taux_commission: float = 0.30,
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
    nb = Counter()
    rembourse = Counter()
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
        rembourse_ch = _unites(ch.get("amount_refunded", 0), devise)
        if quand >= il_y_a_14j:
            par_jour[quand.date().isoformat()] += net
        derniers.append((ch["created"], net))
        periodes = []
        if quand >= jour:
            periodes.append("aujourdhui")
        elif quand >= hier:
            periodes.append("hier")
        if il_y_a_7j <= quand < jour:
            periodes.append("7j")
        if quand >= debut_mois:
            periodes.append("mois")
        elif quand >= debut_mois_prec and quand.day <= now.day:
            # même période le mois dernier, pour comparer
            periodes.append("mois_prec_meme_periode")
        for p in periodes:
            ca[p] += net
            nb[p] += 1
            if rembourse_ch:
                rembourse[p] += rembourse_ch
                rembourse["nb_" + p] += 1

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

    # --- Litiges (contestations bancaires) ---
    # Optionnel : si la clé n'a pas le droit de lecture « Disputes », on l'indique sans planter.
    litiges_ouverts: Optional[int] = None
    litiges_mois: Optional[int] = None
    try:
        ouverts = mois = 0
        for di in s.lister("/disputes", {"created[gte]": int((jour - timedelta(days=120)).timestamp())}):
            if di.get("status") in _LITIGES_OUVERTS:
                ouverts += 1
            if datetime.fromtimestamp(di["created"], tz) >= debut_mois:
                mois += 1
        litiges_ouverts, litiges_mois = ouverts, mois
    except (PermissionError, httpx.HTTPStatusError):
        pass

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
        "taux_commission": taux_commission,
        "commission_hier": r2(ca["hier"] * taux_commission),
        "commission_7j": r2(ca["7j"] * taux_commission),
        "commission_mois": r2(ca["mois"] * taux_commission),
        "paiements_hier": nb["hier"],
        "paiements_7j": nb["7j"],
        "paiements_mois": nb["mois"],
        "panier_moyen_mois": r2(ca["mois"] / nb["mois"]) if nb["mois"] else 0.0,
        "rembourse_7j": r2(rembourse["7j"]),
        "remboursements_7j": rembourse["nb_7j"],
        "rembourse_mois": r2(rembourse["mois"]),
        "litiges_ouverts": litiges_ouverts,
        "litiges_mois": litiges_mois,
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
                           cfg["fyxigo"]["devise"],
                           float(cfg["fyxigo"].get("taux_commission") or 0.30))
