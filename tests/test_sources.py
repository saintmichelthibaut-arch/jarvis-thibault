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


def _signal(evenements, duree=3.0, taux=16000):
    """Bruit de fond + claquements (t) ou paroles (t, 'voix')."""
    import math
    import random

    random.seed(1)
    n = int(duree * taux)
    x = [random.gauss(0, .004) for _ in range(n)]
    for e in evenements:
        t0 = int(e[0] * taux)
        if len(e) == 1:  # claquement : salve de bruit qui retombe en ~15 ms
            for i in range(int(.08 * taux)):
                if t0 + i < n:
                    x[t0 + i] += random.gauss(0, .5) * math.exp(-i / (.012 * taux))
        else:  # voix : son tenu 400 ms
            for i in range(int(.4 * taux)):
                if t0 + i < n:
                    x[t0 + i] += .25 * math.sin(2 * math.pi * 180 * i / taux) * (1 + .3 * math.sin(i / 300))
    return x


def _compter(x, taux=16000, bloc=256):
    from jarvis_thibault.claquement import Detecteur

    t = [0.0]
    d = Detecteur(horloge=lambda: t[0])
    n = 0
    for i in range(0, len(x) - bloc, bloc):
        t[0] = i / taux
        n += d.bloc(x[i:i + bloc])
    return n


def test_double_claquement():
    assert _compter(_signal([(.5,), (.9,)])) == 1          # clap-clap → réveil
    assert _compter(_signal([(.5,)])) == 0                 # un seul claquement → rien
    assert _compter(_signal([(.5,), (2.2,)])) == 0         # trop espacés → rien
    assert _compter(_signal([(.5, "voix"), (1.0, "voix")])) == 0  # quelqu'un parle → rien


def test_reponse_en_flux(tmp_path, monkeypatch):
    """La 1re phrase doit partir avant la fin de la réponse du modèle."""
    import json
    import time as _t

    from fastapi.testclient import TestClient

    from jarvis_thibault import cerveau, config, serveur

    monkeypatch.setattr(config, "DOSSIER", tmp_path)
    cfg = config.Config(data=config._fusion(config.DEFAUTS, {"voix": {"fournisseur": "aucune"}}), dossier=tmp_path, demo=True)

    def faux_flux(*a, **k):
        for morceau in ["Bonjour Monsieur, ", "tout va bien. ", "Deuxième phrase ", "un peu plus longue."]:
            _t.sleep(.3)
            yield morceau

    monkeypatch.setattr(cerveau, "repondre_flux", faux_flux)
    client = TestClient(serveur.creer_app(cfg, planifier=False))
    t0 = _t.time()
    instants, phrases = [], []
    with client.stream("POST", "/api/parler_flux", json={"message": "salut", "voix": False}) as r:
        for l in r.iter_lines():
            if l:
                o = json.loads(l)
                if o["type"] == "phrase":
                    instants.append(_t.time() - t0)
                    phrases.append(o["texte"])
    assert phrases == ["Bonjour Monsieur, tout va bien.", "Deuxième phrase un peu plus longue."]
    assert instants[0] < 1.0 < instants[1]
