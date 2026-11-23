"""Données fictives pour tester Jarvis sans rien connecter (JARVIS_DEMO=1)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ..config import DOSSIER

_TACHES_DEMO = """# Objectifs
- 3 000 € de commission par mois
- 3 artisans vérifiés par métier dans le 11e

# À faire
- [ ] !!! Relancer les 3 artisans en attente de vérification @{hier}
- [ ] !! Rendez-vous avec le plombier de la rue Oberkampf @{auj}
- [ ] !! Passer Stripe en clés live @{demain}
- [ ] ! Désigner le médiateur de la consommation
- [ ] Créer la fiche Google Business Profile
- [x] Corriger le suivi de l'artisan sur la carte
"""


def FICHIER_DEMO() -> Path:
    p = DOSSIER / "demo" / "fyxigo.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        j = date.today()
        p.write_text(_TACHES_DEMO.format(hier=j - timedelta(days=1), auj=j,
                                         demain=j + timedelta(days=1)), encoding="utf-8")
    return p


def agenda_demo(jour: date) -> List[Dict[str, Any]]:
    a, d = jour.isoformat(), (jour + timedelta(days=1)).isoformat()
    return [
        {"titre": "Point hebdo Fyxigo", "jour": a, "debut": "09:30", "fin": "10:00",
         "journee": False, "lieu": "Teams", "calendrier": "Outlook"},
        {"titre": "Rencontre artisan — plomberie Martin", "jour": a, "debut": "11:00", "fin": "11:45",
         "journee": False, "lieu": "Paris 11e", "calendrier": "Outlook"},
        {"titre": "Déjeuner avec Julien", "jour": a, "debut": "12:30", "fin": "14:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Appel investisseur", "jour": a, "debut": "16:00", "fin": "16:30",
         "journee": False, "lieu": "", "calendrier": "Outlook"},
        {"titre": "Salle de sport", "jour": a, "debut": "19:00", "fin": "20:00",
         "journee": False, "lieu": "", "calendrier": "iCloud"},
        {"titre": "Salon de l'artisanat", "jour": d, "debut": None, "fin": None,
         "journee": True, "lieu": "Paris Expo, porte de Versailles", "calendrier": "Outlook"},
    ]


def meteo_demo() -> Dict[str, Any]:
    return {"ville": "Paris", "maintenant": 6, "ressenti": 3, "min": 4, "max": 11,
            "pluie_proba": 60, "vent_kmh": 18, "description": "averses",
            "description_actuelle": "couvert", "icone": "🌦", "lever": "07:52",
            "coucher": "17:01"}


def stripe_demo() -> Dict[str, Any]:
    jours = [0, 109, 0, 218, 149, 0, 109, 258, 109, 0, 327, 149, 218, 0]
    return {"devise": "EUR", "ca_aujourdhui": 0, "ca_hier": 218.0, "ca_7j": 1170.0,
            "ca_mois": 3270.0, "ca_mois_prec_meme_periode": 2507.0,
            "taux_commission": 0.30, "commission_hier": 65.4, "commission_7j": 351.0,
            "commission_mois": 981.0, "paiements_hier": 2, "paiements_7j": 10, "paiements_mois": 25,
            "panier_moyen_mois": 130.8, "rembourse_7j": 109.0, "remboursements_7j": 1,
            "rembourse_mois": 109.0, "litiges_ouverts": 0, "litiges_mois": 0,
            "nouveaux_clients_aujourdhui": 0, "nouveaux_clients_hier": 2,
            "nouveaux_clients_7j": 8, "nouveaux_clients_mois": 21, "paiements_echoues_7j": 1,
            "ca_jours": [{"jour": (date.today() - timedelta(days=13 - i)).isoformat(), "montant": float(m)}
                         for i, m in enumerate(jours)],
            "derniers_paiements": [{"quand": date.today().isoformat() + "T09:12", "montant": 109.0},
                                   {"quand": date.today().isoformat() + "T08:40", "montant": 149.0}]}


def base_demo() -> List[Dict[str, Any]]:
    return [
        {"nom": "Demandes d'intervention hier", "valeur": 4, "format": "nombre", "panneau": "hier"},
        {"nom": "Demandes sans artisan (7 j)", "valeur": 2, "format": "nombre", "panneau": "hier"},
        {"nom": "Taux d'acceptation (7 j)", "valeur": 82, "format": "pourcent", "panneau": "semaine"},
        {"nom": "Artisans vérifiés", "valeur": 6, "format": "nombre", "panneau": "semaine"},
        {"nom": "Note moyenne clients", "valeur": 4.6, "format": "note", "panneau": "semaine"},
    ]
