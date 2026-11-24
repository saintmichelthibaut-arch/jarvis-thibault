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
- [ ] !! Préparer la démo pour le rendez-vous avec le serrurier du 11e @{auj}
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
        {"titre": "Point hebdo équipe Fyxigo", "jour": a, "debut": "09:30", "fin": "10:00",
         "journee": False, "lieu": "Teams", "calendrier": "Outlook"},
        {"titre": "Démo Fyxigo — serrurerie Martin", "jour": a, "debut": "11:00", "fin": "11:45",
         "journee": False, "lieu": "Paris 11e", "calendrier": "Outlook"},
        {"titre": "Déjeuner avec Julien", "jour": a, "debut": "12:30", "fin": "14:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Appel investisseur", "jour": a, "debut": "16:00", "fin": "16:30",
         "journee": False, "lieu": "", "calendrier": "Outlook"},
        {"titre": "Salle de sport", "jour": a, "debut": "19:00", "fin": "20:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Salon de l'artisanat", "jour": d, "debut": None, "fin": None,
         "journee": True, "lieu": "Paris Expo", "calendrier": "Outlook"},
    ]


def meteo_demo() -> Dict[str, Any]:
    return {"ville": "Paris", "maintenant": 6, "ressenti": 3, "min": 4, "max": 11,
            "pluie_proba": 60, "vent_kmh": 18, "description": "averses",
            "description_actuelle": "couvert", "icone": "🌦", "lever": "07:52",
            "coucher": "17:01"}


def stripe_demo() -> Dict[str, Any]:
    return {"devise": "EUR", "taux_commission": .30, "ca_aujourdhui": 0, "ca_hier": 327.0, "ca_7j": 2071.0,
            "ca_mois": 5341.0, "ca_mois_prec_meme_periode": 4470.0,
            "commission_hier": 98.1, "commission_7j": 621.3, "commission_mois": 1602.3,
            "interventions_aujourdhui": 0, "interventions_hier": 3, "interventions_7j": 19, "interventions_mois": 49,
            "panier_moyen_7j": 109.0, "panier_moyen_mois": 109.0, "rembourse_7j": 109.0, "rembourse_mois": 218.0,
            "litiges_ouverts": 0,
            "nouveaux_clients_aujourdhui": 0, "nouveaux_clients_hier": 3,
            "nouveaux_clients_7j": 14, "nouveaux_clients_mois": 31, "mrr": 0.0,
            "abonnements_actifs": 0, "essais_en_cours": 0, "paiements_echoues_7j": 1,
            "ca_jours": [{"jour": (date.today() - timedelta(days=13 - i)).isoformat(), "montant": m}
                         for i, m in enumerate([109, 218, 0, 327, 218, 109, 0, 218, 436, 327, 545, 218, 327, 0])],
            "derniers_paiements": [{"quand": date.today().isoformat() + "T09:12", "montant": 109.0}]}


def base_demo() -> List[Dict[str, Any]]:
    return [
        {"nom": "Demandes d'intervention hier", "valeur": 47, "format": "nombre", "panneau": "hier"},
        {"nom": "Artisans inscrits hier", "valeur": 5, "format": "nombre", "panneau": "hier"},
        {"nom": "Missions terminées (7 j)", "valeur": 186, "format": "nombre", "panneau": "semaine"},
        {"nom": "Note moyenne clients", "valeur": 4.6, "format": "note", "panneau": "semaine"},
    ]
