from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from jarvis_thibault.sources import stripe_fixigo, taches

TZ = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=TZ)


def ts(j, h=12):
    return int(datetime(2026, 11, j, h, tzinfo=TZ).timestamp())


CHARGES = [
    {"id": "ch1", "created": ts(19), "currency": "eur", "status": "succeeded", "paid": True, "amount": 5000, "amount_refunded": 0},
    {"id": "ch2", "created": ts(19, 9), "currency": "eur", "status": "succeeded", "paid": True, "amount": 3000, "amount_refunded": 1000},
    {"id": "ch3", "created": ts(15), "currency": "eur", "status": "succeeded", "paid": True, "amount": 10000, "amount_refunded": 0},
    {"id": "ch4", "created": ts(18), "currency": "eur", "status": "failed", "paid": False, "amount": 2000, "amount_refunded": 0},
    {"id": "ch5", "created": ts(2), "currency": "eur", "status": "succeeded", "paid": True, "amount": 7000, "amount_refunded": 0},
    {"id": "ch6", "created": ts(19), "currency": "usd", "status": "succeeded", "paid": True, "amount": 99999, "amount_refunded": 0},
]
CUSTOMERS = [{"id": "c1", "created": ts(19)}, {"id": "c2", "created": ts(17)}, {"id": "c3", "created": ts(3)}]
SUBS = [
    {"id": "s1", "items": {"data": [{"quantity": 1, "price": {"currency": "eur", "unit_amount": 2900, "recurring": {"interval": "month", "interval_count": 1}}}]}},
    {"id": "s2", "items": {"data": [{"quantity": 2, "price": {"currency": "eur", "unit_amount": 24000, "recurring": {"interval": "year", "interval_count": 1}}}]}},
]


def _handler(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    if p.endswith("/charges"):
        data = CHARGES
    elif p.endswith("/customers"):
        data = CUSTOMERS
    elif p.endswith("/subscriptions"):
        data = SUBS if req.url.params.get("status") == "active" else [{"id": "t1"}]
    else:
        return httpx.Response(404)
    # pagination : 2 objets par page
    start = 0
    if "starting_after" in req.url.params:
        start = [d["id"] for d in data].index(req.url.params["starting_after"]) + 1
    page = data[start:start + 2]
    return httpx.Response(200, json={"data": page, "has_more": start + 2 < len(data)})


def test_chiffres_stripe():
    r = stripe_fixigo.chiffres_stripe("rk_test", "Europe/Paris", "EUR", maintenant=NOW,
                                      transport=httpx.MockTransport(_handler))
    assert r["ca_hier"] == 70.0            # 50 + (30 - 10)
    assert r["ca_7j"] == 170.0             # + 100 le 15
    assert r["ca_mois"] == 240.0           # + 70 le 2
    assert r["paiements_echoues_7j"] == 1
    assert r["nouveaux_clients_hier"] == 1
    assert r["nouveaux_clients_7j"] == 2
    assert r["nouveaux_clients_mois"] == 3
    assert r["mrr"] == 69.0                # 29 + 2*240/12
    assert r["abonnements_actifs"] == 2
    assert r["essais_en_cours"] == 1


def test_taches(tmp_path):
    f = tmp_path / "fixigo.md"
    f.write_text("# Objectifs\n- 5000 € MRR\n\n# À faire\n- [ ] Tâche simple\n"
                 "- [ ] !!! Urgente @2026-11-19\n- [x] Finie\n- [ ] !! Aujourd'hui @2026-11-20\n",
                 encoding="utf-8")
    d = taches.lire(f, date(2026, 11, 20))
    assert d["objectifs"] == ["5000 € MRR"]
    textes = [t["texte"] for t in d["taches"]]
    assert textes == ["Urgente", "Aujourd'hui", "Tâche simple", "Finie"]
    assert d["taches"][0]["en_retard"] and d["taches"][0]["priorite"] == 3
    ligne = d["taches"][2]["ligne"]
    assert taches.basculer(f, ligne) is True
    assert "- [x] Tâche simple" in f.read_text(encoding="utf-8")
    taches.ajouter(f, "Nouvelle")
    assert "# À faire\n- [ ] Nouvelle" in f.read_text(encoding="utf-8")


def test_mensualiser():
    assert stripe_fixigo.mensualiser(120, "year", 1) == 10
    assert stripe_fixigo.mensualiser(30, "month", 3) == 10


def test_base_sqlite(tmp_path):
    import sqlite3

    from jarvis_thibault.sources.base_fixigo import indicateurs_base

    db = tmp_path / "app.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE missions(id INTEGER, prix REAL); INSERT INTO missions VALUES (1, 80), (2, 120);")
    c.commit()
    c.close()
    r = indicateurs_base(f"sqlite:///{db}", [
        {"nom": "Missions", "sql": "SELECT count(*) FROM missions"},
        {"nom": "CA", "sql": "SELECT sum(prix) FROM missions", "format": "euros"},
        {"nom": "Cassé", "sql": "SELECT * FROM inexistante"},
    ])
    assert [x["valeur"] for x in r] == [2, 200, None]
    assert "erreur" in r[2]


def test_lire_heure():
    from jarvis_thibault.serveur import lire_heure

    assert lire_heure("08:00") == (8, 0)
    assert lire_heure("8h") == (8, 0)
    assert lire_heure("8h30") == (8, 30)
    assert lire_heure("7") == (7, 0)


def test_intentions():
    from jarvis_thibault.cerveau import intentions

    assert intentions("Rappelle-moi à 18h30 d'appeler le comptable.") == [("RAPPEL", "18:30 | appeler le comptable")]
    assert intentions("Souviens-toi que je préfère le matin")[0] == ("MEMOIRE", "je préfère le matin")
    assert intentions("Ajoute une tâche urgente : relancer Paul") == [("AJOUT_TACHE", "!!! relancer Paul")]
    assert intentions("J'ai fini de préparer la démo") == [("TACHE_FAITE", "préparer la démo")]
    assert intentions("Combien on a encaissé cette semaine ?") == []
