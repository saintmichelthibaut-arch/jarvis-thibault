"""Le cerveau de Jarvis : collecte des données, personnalité, briefing et conversation."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from openai import OpenAI

from .sources import agenda, base_fixigo, meteo, moodle, stripe_fixigo, taches

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
    "moodle": moodle.moodle,
}


def collecter(cfg) -> Dict[str, Any]:
    """Interroge toutes les sources en parallèle ; une source en panne n'arrête pas les autres."""
    actives = dict(SOURCES)
    if not cfg["fixigo"].get("stripe") and not cfg.demo:
        actives.pop("stripe")
    if not cfg["moodle"].get("actif") and not cfg.demo:
        actives.pop("moodle")
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
    try:
        from .vie import Memoire, Rappels

        base = cfg.dossier / "demo" if cfg.demo else cfg.dossier
        out["memoire"] = Memoire(base / "memoire.md").lire()[-40:]
        out["rappels"] = Rappels(base / "rappels.json", cfg["moi"]["fuseau"]).a_venir()[:10]
    except Exception:  # noqa: BLE001
        out["memoire"], out["rappels"] = [], []
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

    mo = d.get("moodle")
    if mo:
        dv = mo.get("devoirs") or []
        if dv:
            L.append(f"MOODLE ({mo.get('site', 'école')}) — DEVOIRS ET ÉCHÉANCES À VENIR :")
            for x in dv[:12]:
                q = datetime.fromisoformat(x["echeance"])
                retard = " — EN RETARD" if x.get("en_retard") else ""
                L.append(f"  - {JOURS[q.weekday()]} {q.day} {MOIS[q.month - 1]} à {q:%H:%M} : {x['titre']}"
                         f" ({x.get('cours') or 'cours'}){retard}")
        else:
            L.append("MOODLE : aucun devoir à rendre dans les 3 prochaines semaines.")
        if mo.get("cours"):
            L.append("COURS EN COURS : " + " ; ".join(
                f"{c['nom']}" + (f" ({c['progression']:.0f} %)" if isinstance(c.get("progression"), (int, float)) else "")
                for c in mo["cours"][:8]))
    if s and s.get("ca_jours"):
        L.append("FIXIGO — ENCAISSEMENTS PAR JOUR (14 j) : " + ", ".join(
            f"{x['jour'][8:10]}/{x['jour'][5:7]} {x['montant']:.0f} €" for x in s["ca_jours"]))
    if d.get("rappels"):
        L.append("RAPPELS PROGRAMMÉS : " + " ; ".join(f"{r['quand'][11:16]} {r['texte']}" for r in d["rappels"]))
    if d.get("memoire"):
        L.append("CE QUE TU SAIS DE LUI (mémoire, à utiliser à bon escient) :")
        L.extend(f"  - {m}" for m in d["memoire"])

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
- Tu as l'humour d'un majordome britannique d'IA de film : pince-sans-rire, ironie fine, petites piques affectueuses (« Je me permets de noter que… », « Fascinant, Monsieur. », « Je prépare déjà les excuses pour votre retard. »). Une touche drôle par réponse, dite avec un sérieux parfait, jamais lourde.
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
6. Si des devoirs Moodle sont fournis : ceux à rendre dans les prochains jours, avec la date, le plus urgent d'abord.
7. Une phrase de conclusion motivante et légèrement drôle.
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


def _messages_conversation(cfg, message, historique, donnees) -> List[Dict[str, str]]:
    ctx = contexte_texte(donnees, cfg)
    msgs = [{"role": "system", "content": persona(cfg)
             + "\n\nDONNÉES À JOUR (ta seule source de vérité) :\n" + ctx + "\n\n" + ACTIONS
             + "\n\nRÉPONDS VITE : commence directement par l'essentiel, première phrase courte."}]
    for h in historique[-12:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": message})
    return msgs


def repondre_flux(cfg, message: str, historique: List[Dict[str, str]], donnees: Dict[str, Any]):
    """Comme repondre(), mais renvoie le texte morceau par morceau, dès qu'il est écrit."""
    c = cfg["cerveau"]
    extra: Dict[str, Any] = {}
    if c["fournisseur"] == "ollama":
        extra["reasoning_effort"] = "none"
    flux = _client(cfg).chat.completions.create(
        model=c["modele"], messages=_messages_conversation(cfg, message, historique, donnees),
        temperature=c.get("temperature", 0.7), max_tokens=500, stream=True, **extra)
    dans_pensee = False
    for morceau in flux:
        if not morceau.choices:
            continue
        t = morceau.choices[0].delta.content or ""
        if "<think>" in t:
            dans_pensee = True
        if dans_pensee:
            if "</think>" in t:
                dans_pensee = False
                t = t.split("</think>", 1)[1]
            else:
                continue
        if t:
            yield t.replace("**", "").replace("#", "")


_FIN_PHRASE = re.compile(r"(.+?[.!?…])(\s+|$)", re.S)


def decouper_phrases(tampon: str, fin: bool = False) -> tuple[List[str], str]:
    """Extrait les phrases complètes d'un tampon de texte (la 1re le plus tôt possible)."""
    phrases = []
    while True:
        m = _FIN_PHRASE.match(tampon)
        if not m or (not m.group(2) and not fin):
            break
        p = m.group(1).strip()
        if len(p) < 18 and not fin and len(tampon) > m.end():
            # phrase trop courte : on l'accole à la suivante
            m2 = _FIN_PHRASE.match(tampon, m.end())
            if not m2 or (not m2.group(2)):
                break
            p = tampon[:m2.end(1)].strip()
            tampon = tampon[m2.end():]
        else:
            tampon = tampon[m.end():]
        if p:
            phrases.append(p)
    if fin and tampon.strip():
        phrases.append(tampon.strip())
        tampon = ""
    return phrases, tampon


def repondre(cfg, message: str, historique: List[Dict[str, str]],
             donnees: Dict[str, Any]) -> str:
    ctx = contexte_texte(donnees, cfg)
    msgs = [{"role": "system", "content": persona(cfg)
             + "\n\nDONNÉES À JOUR (ta seule source de vérité) :\n" + ctx + "\n\n" + ACTIONS}]
    for h in historique[-12:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": message})
    return generer(cfg, msgs, max_tokens=500)


ACTIONS = """TES POUVOIRS — quand on te le demande, ajoute la ou les balises correspondantes AU DÉBUT de ta réponse, puis confirme naturellement :
- [AJOUT_TACHE: texte]  → ajoute une tâche Fixigo (mets « !!! » devant le texte si c'est urgent, « @AAAA-MM-JJ » à la fin pour une échéance)
- [TACHE_FAITE: mots-clés]  → coche une tâche terminée (« j'ai fini / c'est fait … »)
- [MEMOIRE: fait à retenir]  → retient une information durable (« souviens-toi que… », préférences, personnes, objectifs)
- [OUBLIE: mots-clés]  → efface un souvenir
- [RAPPEL: HH:MM | texte]  → programme un rappel vocal (« rappelle-moi à 15 h de… » ; « dans 20 minutes » = calcule l'heure)
- [BRIEFING]  → lance le briefing complet ; [BILAN]  → lance le bilan de la journée
N'utilise une balise que si la demande est claire. N'en parle jamais à voix haute."""

_BALISE = re.compile(r"\[(AJOUT_TACHE|TACHE_FAITE|MEMOIRE|OUBLIE|RAPPEL|BRIEFING|BILAN)(?:\s*:\s*([^\]]*))?\]")


def extraire_actions(reponse: str) -> tuple[List[tuple[str, str]], str]:
    """Sépare les balises d'action (où qu'elles soient) du texte à dire."""
    actions = [(m.group(1), (m.group(2) or "").strip()) for m in _BALISE.finditer(reponse)]
    texte = re.sub(r"\s{2,}", " ", _BALISE.sub("", reponse)).strip()
    return actions, texte


_NOMBRES = {"une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "quinze": 15,
            "vingt": 20, "trente": 30, "quarante": 40, "quarante-cinq": 45, "cinquante": 50, "soixante": 60}


def intentions(message: str, fuseau: str = "Europe/Paris") -> List[tuple[str, str]]:
    """Détection fiable des commandes courantes, sans dépendre du modèle."""
    t = " ".join(message.strip().split())
    bas = t.casefold()
    acts: List[tuple[str, str]] = []
    # Rappels : « rappelle-moi à 15h30 de … », « rappelle-moi dans 20 minutes de … »
    m = re.search(r"rappelle[- ]moi\s+(?:demain\s+)?(?:à|a|vers)\s+(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?\s*(?:de |d'|d’|que |qu'|pour |:)?\s*(.*)", bas)
    if m:
        acts.append(("RAPPEL", f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d} | {t[m.start(3):].strip(' .!') or 'rappel'}"))
    else:
        m = re.search(r"rappelle[- ]moi\s+dans\s+(\d+|[a-z-]+)\s*(minutes?|min|heures?|h)\s*(?:de |d'|d’|que |qu'|pour |:)?\s*(.*)", bas)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else _NOMBRES.get(m.group(1), 0)
            if n:
                quand = datetime.now(ZoneInfo(fuseau)) + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n))
                acts.append(("RAPPEL", f"{quand:%H:%M} | {t[m.start(3):].strip(' .!') or 'rappel'}"))
    # Mémoire
    m = re.search(r"(?:souviens[- ]toi|rappelle[- ]toi|retiens|n'oublie pas|n’oublie pas|note bien)\s+(?:que|qu'|qu’|de|bien que)?\s*(.+)", bas)
    if m and "rappelle-moi" not in bas:
        acts.append(("MEMOIRE", t[m.start(1):].strip(" .!")))
    m = re.search(r"oublie\s+(?:que|qu'|qu’|ce que je t'ai dit sur|le souvenir)\s*(.+)", bas)
    if m and not acts:
        acts.append(("OUBLIE", t[m.start(1):].strip(" .!")))
    # Tâches
    m = re.search(r"ajoute(?:r)?\s+(?:une\s+|la\s+)?t[aâ]che\s*(?:fixigo)?\s*[:,]?\s*(?:de |d'|d’|pour |:)?\s*(.+)", bas)
    if m:
        urgent = "urgent" in bas or "important" in bas
        texte = re.sub(r"^(?:urgente?|importante?)\s*[:,]?\s*", "", t[m.start(1):].strip(" .!"), flags=re.I)
        acts.append(("AJOUT_TACHE", ("!!! " if urgent else "") + texte))
    m = re.search(r"(?:j'ai|j’ai)\s+(?:fini|termin[ée]|bouclé|fait)\s+(?:de\s+|la\s+tâche\s+|la\s+tache\s+)?(.+)", bas)
    if m:
        acts.append(("TACHE_FAITE", t[m.start(1):].strip(" .!")))
    # Briefing / bilan
    if re.search(r"\b(briefing|r[ée]cap(?:itulatif)?)\b", bas) and not acts and len(bas) < 90:
        acts.append(("BRIEFING", ""))
    elif re.search(r"\bbilan\b", bas) and not acts and len(bas) < 90:
        acts.append(("BILAN", ""))
    return acts


def _consigne_bilan() -> str:
    return """Rédige le BILAN DU SOIR, à lire à voix haute (45 secondes, 100 à 160 mots) :
1. Un mot pour clôturer la journée, avec humour léger.
2. Fixigo aujourd'hui : ce qui a été encaissé et les nouveaux clients du jour s'ils sont fournis, la tendance des 14 derniers jours.
3. Les tâches : ce qui reste ouvert et ce qu'il faudra attaquer en premier demain.
4. Demain dans l'agenda, s'il y a quelque chose.
5. Une phrase pour finir la soirée (repos, sport, famille…).
Uniquement les données fournies, texte parlé fluide sans listes ni markdown."""


def bilan(cfg, donnees: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    donnees = donnees or collecter(cfg)
    ctx = contexte_texte(donnees, cfg)
    texte = generer(cfg, [
        {"role": "system", "content": persona(cfg)},
        {"role": "user", "content": f"Voici les données :\n\n{ctx}\n\n{_consigne_bilan()}"},
    ], max_tokens=700)
    return {"texte": texte, "contexte": ctx, "horodatage": donnees["horodatage"], "type": "bilan"}


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
    suffixe = "-bilan" if b.get("type") == "bilan" else ""
    (cfg.dossier_briefings / f"{jour}{suffixe}.json").write_text(
        json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")


def dernier_briefing(cfg, type_: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Le dernier briefing (type_="briefing"), le dernier bilan ("bilan") ou le plus récent des deux."""
    fichiers = list(cfg.dossier_briefings.glob("*.json"))
    if type_ == "briefing":
        fichiers = [f for f in fichiers if not f.stem.endswith("-bilan")]
    elif type_ == "bilan":
        fichiers = [f for f in fichiers if f.stem.endswith("-bilan")]
    if not fichiers:
        return None
    f = max(fichiers, key=lambda x: x.stat().st_mtime)
    return json.loads(f.read_text(encoding="utf-8"))
