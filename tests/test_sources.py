from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from jarvis_thibault.sources import stripe_fyxigo, taches

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
DISPUTES = [
    {"id": "dp1", "created": ts(18), "status": "needs_response"},
    {"id": "dp2", "created": ts(10), "status": "won"},
]


def _handler(req: httpx.Request, litiges_autorises: bool = True) -> httpx.Response:
    p = req.url.path
    if p.endswith("/charges"):
        data = CHARGES
    elif p.endswith("/customers"):
        data = CUSTOMERS
    elif p.endswith("/disputes"):
        if not litiges_autorises:
            return httpx.Response(403, json={"error": {"message": "permission"}})
        data = DISPUTES
    else:
        return httpx.Response(404)
    # pagination : 2 objets par page
    start = 0
    if "starting_after" in req.url.params:
        start = [d["id"] for d in data].index(req.url.params["starting_after"]) + 1
    page = data[start:start + 2]
    return httpx.Response(200, json={"data": page, "has_more": start + 2 < len(data)})


def test_chiffres_stripe():
    r = stripe_fyxigo.chiffres_stripe("rk_test", "Europe/Paris", "EUR", maintenant=NOW,
                                      transport=httpx.MockTransport(_handler))
    assert r["ca_hier"] == 70.0            # 50 + (30 - 10)
    assert r["ca_7j"] == 170.0             # + 100 le 15
    assert r["ca_mois"] == 240.0           # + 70 le 2
    assert r["paiements_echoues_7j"] == 1
    assert r["nouveaux_clients_hier"] == 1
    assert r["nouveaux_clients_7j"] == 2
    assert r["nouveaux_clients_mois"] == 3
    # Place de marché : commission de 30 % sur l'encaissé net, pas de MRR
    assert "mrr" not in r
    assert r["paiements_hier"] == 2
    assert r["paiements_7j"] == 3
    assert r["paiements_mois"] == 4
    assert r["commission_hier"] == 21.0    # 30 % de 70
    assert r["commission_7j"] == 51.0
    assert r["commission_mois"] == 72.0
    assert r["panier_moyen_mois"] == 60.0  # 240 / 4
    assert r["rembourse_7j"] == 10.0
    assert r["remboursements_7j"] == 1
    assert r["litiges_ouverts"] == 1
    assert r["litiges_mois"] == 2


def test_chiffres_stripe_taux_et_litiges_sans_droit():
    r = stripe_fyxigo.chiffres_stripe(
        "rk_test", "Europe/Paris", "EUR", taux_commission=0.25, maintenant=NOW,
        transport=httpx.MockTransport(lambda req: _handler(req, litiges_autorises=False)))
    assert r["commission_mois"] == 60.0    # 25 % de 240
    assert r["litiges_ouverts"] is None    # clé sans le droit « Disputes » : on n'invente pas


def test_migration_ancienne_section(tmp_path):
    from jarvis_thibault.config import DEFAUTS, Config, _fusion, migrer

    ancien = {"fixigo": {"stripe": False, "objectif_mrr": 5000, "base": {"active": True}}}
    data = _fusion(DEFAUTS, migrer(ancien))
    assert "fixigo" not in data
    assert data["fyxigo"]["stripe"] is False
    assert data["fyxigo"]["base"]["active"] is True
    assert data["fyxigo"]["taux_commission"] == 0.30
    # L'ancien fichier de tâches est repris s'il est le seul présent
    (tmp_path / "fixigo.md").write_text("# À faire\n", encoding="utf-8")
    cfg = Config(data=data, dossier=tmp_path)
    assert cfg.fichier_taches == tmp_path / "fixigo.md"
    (tmp_path / "fyxigo.md").write_text("# À faire\n", encoding="utf-8")
    assert cfg.fichier_taches == tmp_path / "fyxigo.md"


def test_taches(tmp_path):
    f = tmp_path / "fyxigo.md"
    f.write_text("# Objectifs\n- 3000 € de commission\n\n# À faire\n- [ ] Tâche simple\n"
                 "- [ ] !!! Urgente @2026-11-19\n- [x] Finie\n- [ ] !! Aujourd'hui @2026-11-20\n",
                 encoding="utf-8")
    d = taches.lire(f, date(2026, 11, 20))
    assert d["objectifs"] == ["3000 € de commission"]
    textes = [t["texte"] for t in d["taches"]]
    assert textes == ["Urgente", "Aujourd'hui", "Tâche simple", "Finie"]
    assert d["taches"][0]["en_retard"] and d["taches"][0]["priorite"] == 3
    ligne = d["taches"][2]["ligne"]
    assert taches.basculer(f, ligne) is True
    assert "- [x] Tâche simple" in f.read_text(encoding="utf-8")
    taches.ajouter(f, "Nouvelle")
    assert "# À faire\n- [ ] Nouvelle" in f.read_text(encoding="utf-8")


def test_base_sqlite(tmp_path):
    import sqlite3

    from jarvis_thibault.sources.base_fyxigo import indicateurs_base

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


def test_moodle(tmp_path):
    import httpx

    from jarvis_thibault.connexion_moodle import _ecrire
    from jarvis_thibault.sources.moodle import donnees_moodle, jeton_depuis_identifiants

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/login/token.php"):
            return httpx.Response(200, json={"token": "abc123"})
        f = dict(httpx.QueryParams(req.content.decode()))["wsfunction"]
        if f == "core_webservice_get_site_info":
            return httpx.Response(200, json={"sitename": "Moodle École", "userid": 7})
        if f == "core_calendar_get_action_events_by_timesort":
            return httpx.Response(200, json={"events": [
                {"name": "Devoir 2 est à remettre", "activityname": "Devoir 2", "course": {"fullname": "Finance"},
                 "modulename": "assign", "timesort": 4102444800, "overdue": False, "url": "u", "action": {"name": "Remettre"}}]})
        if f == "core_course_get_enrolled_courses_by_timeline_classification":
            return httpx.Response(200, json={"courses": [{"fullname": "Finance", "progress": 40}]})
        return httpx.Response(200, json={"exception": "x", "message": "inconnue"})

    t = httpx.MockTransport(handler)
    assert jeton_depuis_identifiants("https://m.ex", "a", "b", transport=t) == "abc123"
    d = donnees_moodle("https://m.ex/", "abc123", transport=t)
    assert d["site"] == "Moodle École" and d["devoirs"][0]["titre"] == "Devoir 2" and d["cours"][0]["nom"] == "Finance"

    conf = tmp_path / "config.toml"
    conf.write_text('[moi]\nville = "Paris"\n\n[serveur]\nport = 8765\n', encoding="utf-8")
    _ecrire("url", "https://m.ex", conf, "moodle")
    _ecrire("actif", True, conf, "moodle")
    _ecrire("actif", True, conf, "moodle")
    import tomllib
    c = tomllib.loads(conf.read_text(encoding="utf-8"))
    assert c["moodle"] == {"url": "https://m.ex", "actif": True} and c["serveur"]["port"] == 8765
