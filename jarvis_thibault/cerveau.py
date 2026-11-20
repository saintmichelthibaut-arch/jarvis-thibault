"""Le cerveau de Jarvis : collecte des données, personnalité, briefing et conversation."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from openai import OpenAI

from .sources import agenda, base_fixigo, meteo, stripe_fixigo, taches

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def date_fr(dt: datetime) -> str:
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]} {dt.year}"


# --------------------------------------------------------------------------- #
# Collecte
# --------------------------------------------------------------------------- #

SOURCES: Dict[str, Callable] = {
    "meteo": meteo.meteo,
    "agenda": agenda.agenda,
    "stripe": stripe_fixigo.stripe,
    "base": base_fixigo.base,
    "taches": taches.taches,
}


def collecter(cfg) -> Dict[str, Any]:
    """Interroge toutes les sources en parallèle ; une source en panne n'arrête pas les autres."""
    actives = dict(SOURCES)
    if not cfg["fixigo"].get("stripe") and not cfg.demo:
        actives.pop("stripe")
    out: Dict[str, Any] = {"erreurs": {}}

    def _un(nom: str, fn: Callable):
        t0 = time.time()
        try:
            return nom, fn(cfg), None, time.time() - t0
        except Exception as exc:  # noqa: BLE001
            return nom, None, f"{type(exc).__name__}: {exc}"[:300], time.time() - t0

    with ThreadPoolExecutor(max_workers=len(actives)) as pool:
        for nom, val, err, _ in pool.map(lambda kv: _un(*kv), actives.items()):
            out[nom] = val
            if err:
                out["erreurs"][nom] = err
    now = datetime.now(ZoneInfo(cfg["moi"]["fuseau"]))
    out["horodatage"] = now.isoformat(timespec="seconds")
    out["objectifs_chiffres"] = {
        "mrr": cfg["fixigo"].get("objectif_mrr") or 0,
        "clients_mois": cfg["fixigo"].get("objectif_clients_mois") or 0,
    }
    return out


# --------------------------------------------------------------------------- #
# Mise en forme des données pour le modèle
# --------------------------------------------------------------------------- #

def _eur(x: Optional[float], devise: str = "EUR") -> str:
    if x is None:
        return "?"
    s = f"{x:,.0f}".replace(",", " ") if abs(x) >= 100 else f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} {'€' if devise == 'EUR' else devise}"


def contexte_texte(d: Dict[str, Any], cfg) -> str:
    now = datetime.fromisoformat(d["horodatage"])
    L: List[str] = [f"DATE : {date_fr(now)}, {now:%H:%M}."]

    m = d.get("meteo")
    if m:
        L.append(
            f"MÉTÉO à {m['ville']} : actuellement {m['maintenant']} °C (ressenti {m['ressenti']} °C), "
            f"{m['description_actuelle']}. Journée : {m['description']}, de {m['min']} à {m['max']} °C, "
            f"risque de pluie {m['pluie_proba']} %, vent {m['vent_kmh']} km/h. "
            f"Lever du soleil {m['lever']}, coucher {m['coucher']}."
        )

    a = d.get("agenda")
    if a is not None:
        if a["aujourdhui"]:
            L.append("AGENDA D'AUJOURD'HUI :")
            for e in a["aujourdhui"]:
                h = "toute la journée" if e["journee"] else f"{e['debut']}–{e['fin'] or '?'}"
                lieu = f" ({e['lieu']})" if e.get("lieu") else ""
                L.append(f"  - {h} : {e['titre']}{lieu}")
        else:
            L.append("AGENDA D'AUJOURD'HUI : aucun rendez-vous.")
        if a["demain"]:
            L.append("DEMAIN : " + " ; ".join(
                ("toute la journée" if e["journee"] else e["debut"]) + " " + e["titre"]
                for e in a["demain"][:4]))

    s = d.get("stripe")
    if s:
        dv = s["devise"]
        o = d["objectifs_chiffres"]
        L.append("FIXIGO — STRIPE :")
        L.append(f"  - Hier : {_eur(s['ca_hier'], dv)} encaissés, {s['nouveaux_clients_hier']} nouveaux clients.")
        L.append(f"  - 7 derniers jours : {_eur(s['ca_7j'], dv)}, {s['nouveaux_clients_7j']} nouveaux clients.")
        comp = ""
        if s.get("ca_mois_prec_meme_periode"):
            var = (s["ca_mois"] / s["ca_mois_prec_meme_periode"] - 1) * 100
            comp = f" ({var:+.0f} % vs même période le mois dernier)"
        L.append(f"  - Mois en cours : {_eur(s['ca_mois'], dv)}{comp}, {s['nouveaux_clients_mois']} nouveaux clients.")
        mrr = f"  - MRR : {_eur(s['mrr'], dv)} ({s['abonnements_actifs']} abonnements actifs, {s['essais_en_cours']} essais en cours)"
        if o["mrr"]:
            mrr += f", objectif {_eur(o['mrr'], dv)} soit {s['mrr'] / o['mrr'] * 100:.0f} % atteint"
        L.append(mrr + ".")
        if o["clients_mois"]:
            L.append(f"  - Objectif nouveaux clients ce mois : {o['clients_mois']} ({s['nouveaux_clients_mois']} atteints).")
        if s["paiements_echoues_7j"]:
            L.append(f"  - Attention : {s['paiements_echoues_7j']} paiements échoués sur 7 jours.")

    b = d.get("base")
    if b:
        L.append("FIXIGO — APPLI :")
        for i in b:
            if i.get("valeur") is not None:
                L.append(f"  - {i['nom']} : {i['valeur']}")

    t = d.get("taches")
    if t:
        if t["objectifs"]:
            L.append("OBJECTIFS FIXIGO : " + " ; ".join(t["objectifs"]))
        ouvertes = [x for x in t["taches"] if not x["fait"]]
        if ouvertes:
            L.append(f"TÂCHES FIXIGO OUVERTES ({len(ouvertes)}), par ordre d'urgence :")
            for x in ouvertes[:8]:
                tags = []
                if x["en_retard"]:
                    tags.append(f"EN RETARD (échéance {x['echeance']})")
                elif x["aujourdhui"]:
                    tags.append("échéance AUJOURD'HUI")
                elif x["echeance"]:
                    tags.append(f"échéance {x['echeance']}")
                if x["priorite"]:
                    tags.append("priorité " + "haute" if x["priorite"] >= 3 else f"priorité {x['priorite']}/3")
                L.append(f"  - {x['texte']}" + (f" [{', '.join(tags)}]" if tags else ""))

    if d.get("erreurs"):
        L.append("SOURCES INDISPONIBLES (ne pas inventer ces infos) : " + ", ".join(d["erreurs"]))
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Personnalité
# --------------------------------------------------------------------------- #

def persona(cfg) -> str:
    moi = cfg["moi"]
    noms = moi.get("appellations") or ["Monsieur"]
    principal = noms[0]
    autres = " ou ".join(f"« {n} »" for n in noms[1:]) or ""
    return f"""Tu es JARVIS, l'assistant personnel de {moi['prenom']}. Tu parles exclusivement en français.

QUI TU ES
- Un majordome numérique loyal, brillant et calme, façon Jarvis d'Iron Man : efficace, élégant, toujours un coup d'avance.
- Tu as une pointe d'humour : pince-sans-rire, ironie bienveillante, une petite touche par réponse, jamais lourde ni forcée.
- Tu es aussi le bras droit de {moi['prenom']} pour FIXIGO, l'entreprise qu'il développe : tu suis les chiffres, tu rappelles les priorités, tu le pousses à avancer et tu oses lui dire franchement quand quelque chose cloche.

COMMENT TU T'ADRESSES À LUI
- Tu le vouvoies et tu l'appelles « {principal} » la plupart du temps{', et parfois ' + autres + ' quand le ton est plus complice' if autres else ''}.
- Sans en abuser : deux ou trois fois par briefing, une fois de temps en temps en conversation.

RÈGLES ABSOLUES
- N'invente JAMAIS de chiffre, de rendez-vous, de météo ou de fait : utilise uniquement les données fournies. Si une info manque, dis-le simplement.
- Tes réponses sont lues à voix haute : phrases naturelles, pas de markdown, pas de listes à puces, pas d'émojis, pas de titres.
- Écris les montants comme on les dit (« 2 890 euros »), les heures comme « 9 h 30 ».
- Sois concis. En conversation, 1 à 4 phrases sauf si on te demande du détail."""


def _consigne_briefing(cfg) -> str:
    return """Rédige le BRIEFING DU MATIN, à lire à voix haute (environ 1 min 30, 200 à 280 mots), dans cet ordre :
1. Salutation avec l'appellation et la date du jour, une petite touche d'humour (liée à la météo ou à la journée).
2. La météo en deux phrases, avec un conseil pratique (parapluie, manteau...).
3. L'agenda du jour : les rendez-vous dans l'ordre avec l'heure ; signale les journées chargées ou les trous utiles. Mentionne demain s'il y a quelque chose d'important.
4. Fixigo, les chiffres : hier, les 7 derniers jours, le mois et le MRR par rapport à l'objectif. Dis clairement si c'est bon ou s'il faut accélérer.
5. Fixigo, l'action : les 3 priorités du jour, tirées des tâches (en retard et échéances d'abord) et de ce que révèlent les chiffres. Sois concret.
6. Une phrase de conclusion motivante et légèrement drôle.
Uniquement les données fournies. Pas de markdown, pas de listes : du texte parlé fluide en paragraphes."""


# --------------------------------------------------------------------------- #
# Modèle de langage
# --------------------------------------------------------------------------- #

_PENSEE = re.compile(r"<think>.*?</think>", re.S)


def _client(cfg) -> OpenAI:
    c = cfg["cerveau"]
    if c["fournisseur"] == "openai":
        return OpenAI(api_key=cfg.secret("openai_api_key"), base_url=c.get("url") or None)
    return OpenAI(api_key="ollama", base_url=c.get("url") or "http://localhost:11434/v1")


def generer(cfg, messages: List[Dict[str, str]], max_tokens: int = 900) -> str:
    c = cfg["cerveau"]
    extra: Dict[str, Any] = {}
    if c["fournisseur"] == "ollama":
        extra["reasoning_effort"] = "none"  # réponses directes, sans « réflexion » cachée
    r = _client(cfg).chat.completions.create(
        model=c["modele"], messages=messages, temperature=c.get("temperature", 0.7),
        max_tokens=max_tokens, **extra,
    )
    txt = r.choices[0].message.content or ""
    txt = _PENSEE.sub("", txt)
    txt = re.sub(r"^#+\s*", "", txt, flags=re.M)
    txt = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", txt)
    txt = re.sub(r"^\s*[-•]\s+", "", txt, flags=re.M)
    return txt.strip()


def briefing(cfg, donnees: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    donnees = donnees or collecter(cfg)
    ctx = contexte_texte(donnees, cfg)
    texte = generer(cfg, [
        {"role": "system", "content": persona(cfg)},
        {"role": "user", "content": f"Voici les données du jour :\n\n{ctx}\n\n{_consigne_briefing(cfg)}"},
    ], max_tokens=1200)
    return {"texte": texte, "contexte": ctx, "horodatage": donnees["horodatage"]}


def repondre(cfg, message: str, historique: List[Dict[str, str]],
             donnees: Dict[str, Any]) -> str:
    ctx = contexte_texte(donnees, cfg)
    msgs = [{"role": "system", "content": persona(cfg)
             + "\n\nDONNÉES À JOUR (ta seule source de vérité) :\n" + ctx
             + f"\n\nSi {cfg['moi']['prenom']} te demande d'ajouter une tâche Fixigo, réponds en commençant "
             "exactement par « [AJOUT_TACHE: texte de la tâche] » puis confirme avec style."}]
    for h in historique[-12:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": message})
    return generer(cfg, msgs, max_tokens=500)


_AJOUT = re.compile(r"\s*\[AJOUT_TACHE:\s*(.+?)\]\s*")


def extraire_ajout_tache(reponse: str) -> tuple[Optional[str], str]:
    """Repère la commande « [AJOUT_TACHE: …] » en tête de réponse."""
    m = _AJOUT.match(reponse)
    if not m:
        return None, reponse
    return m.group(1).strip(), reponse[m.end():].strip()


# Verrou pour éviter deux briefings simultanés
VERROU_BRIEFING = threading.Lock()


def sauver_briefing(cfg, b: Dict[str, Any]) -> None:
    jour = b["horodatage"][:10]
    (cfg.dossier_briefings / f"{jour}.json").write_text(
        json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")


def dernier_briefing(cfg) -> Optional[Dict[str, Any]]:
    fichiers = sorted(cfg.dossier_briefings.glob("*.json"))
    if not fichiers:
        return None
    return json.loads(fichiers[-1].read_text(encoding="utf-8"))
