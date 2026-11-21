"""Données fictives pour tester Jarvis sans rien connecter (JARVIS_DEMO=1)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ..config import DOSSIER

_TACHES_DEMO = """# Objectifs
- Atteindre 5 000 € de MRR avant fin mars
- 40 nouveaux artisans inscrits par mois

# À faire
- [ ] !!! Relancer les 3 artisans en attente de validation @{hier}
- [ ] !! Préparer la démo pour le rendez-vous avec le plombier de Lyon @{auj}
- [ ] !! Lancer la campagne d'e-mails « hiver » @{demain}
- [ ] ! Répondre aux 2 avis clients négatifs
- [ ] Mettre à jour la page tarifs
- [x] Corriger le bug du paiement en 3 fois
"""


def FICHIER_DEMO() -> Path:
    p = DOSSIER / "demo" / "fixigo.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        j = date.today()
        p.write_text(_TACHES_DEMO.format(hier=j - timedelta(days=1), auj=j,
                                         demain=j + timedelta(days=1)), encoding="utf-8")
    return p


def agenda_demo(jour: date) -> List[Dict[str, Any]]:
    a, d = jour.isoformat(), (jour + timedelta(days=1)).isoformat()
    return [
        {"titre": "Point hebdo équipe Fixigo", "jour": a, "debut": "09:30", "fin": "10:00",
         "journee": False, "lieu": "Teams", "calendrier": "Outlook"},
        {"titre": "Démo Fixigo — plomberie Martin", "jour": a, "debut": "11:00", "fin": "11:45",
         "journee": False, "lieu": "Lyon 3e", "calendrier": "Outlook"},
        {"titre": "Déjeuner avec Julien", "jour": a, "debut": "12:30", "fin": "14:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Appel investisseur", "jour": a, "debut": "16:00", "fin": "16:30",
         "journee": False, "lieu": "", "calendrier": "Outlook"},
        {"titre": "Salle de sport", "jour": a, "debut": "19:00", "fin": "20:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Salon de l'artisanat", "jour": d, "debut": None, "fin": None,
         "journee": True, "lieu": "Eurexpo", "calendrier": "Outlook"},
    ]


def meteo_demo() -> Dict[str, Any]:
    return {"ville": "Lyon", "maintenant": 6, "ressenti": 3, "min": 4, "max": 11,
            "pluie_proba": 60, "vent_kmh": 18, "description": "averses",
            "description_actuelle": "couvert", "icone": "🌦", "lever": "07:52",
            "coucher": "17:01"}


def stripe_demo() -> Dict[str, Any]:
    return {"devise": "EUR", "ca_aujourdhui": 0, "ca_hier": 412.0, "ca_7j": 2890.5,
            "ca_mois": 7340.0, "ca_mois_prec_meme_periode": 6120.0,
            "nouveaux_clients_aujourdhui": 0, "nouveaux_clients_hier": 3,
            "nouveaux_clients_7j": 14, "nouveaux_clients_mois": 31, "mrr": 3870.0,
            "abonnements_actifs": 129, "essais_en_cours": 11, "paiements_echoues_7j": 2,
            "ca_jours": [{"jour": (date.today() - timedelta(days=13 - i)).isoformat(), "montant": m}
                         for i, m in enumerate([180, 260, 95, 410, 330, 0, 120, 290, 455, 380, 610, 270, 412, 0])],
            "derniers_paiements": [{"quand": date.today().isoformat() + "T09:12", "montant": 49.0},
                                   {"quand": date.today().isoformat() + "T08:40", "montant": 29.0}]}


def base_demo() -> List[Dict[str, Any]]:
    return [
        {"nom": "Demandes d'intervention hier", "valeur": 47, "format": "nombre", "panneau": "hier"},
        {"nom": "Artisans inscrits hier", "valeur": 5, "format": "nombre", "panneau": "hier"},
        {"nom": "Missions terminées (7 j)", "valeur": 186, "format": "nombre", "panneau": "semaine"},
        {"nom": "Note moyenne clients", "valeur": 4.6, "format": "note", "panneau": "semaine"},
    ]
