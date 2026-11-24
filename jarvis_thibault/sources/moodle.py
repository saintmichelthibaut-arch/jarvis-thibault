"""Moodle : devoirs à rendre, échéances et cours (API web service de Moodle).

Connexion : ``jarvis-thibault moodle`` (ou le script connecter-moodle.sh) demande
l'adresse du Moodle, l'identifiant et le mot de passe, récupère un « jeton »
(token) et ne garde QUE ce jeton dans ~/.jarvis/secrets.toml.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx


class Moodle:
    def __init__(self, url: str, jeton: str, transport: Optional[httpx.BaseTransport] = None):
        if not url or not jeton:
            raise ValueError("Moodle non connecté : lancez « bash ~/jarvis-thibault-main/connecter-moodle.sh »")
        self.url = url.rstrip("/")
        self.jeton = jeton
        self._c = httpx.Client(timeout=25, transport=transport, follow_redirects=True)

    def appel(self, fonction: str, **params: Any) -> Any:
        data: Dict[str, Any] = {"wstoken": self.jeton, "wsfunction": fonction, "moodlewsrestformat": "json"}
        for k, v in params.items():
            if isinstance(v, (list, tuple)):
                for i, x in enumerate(v):
                    data[f"{k}[{i}]"] = x
            else:
                data[k] = v
        r = self._c.post(f"{self.url}/webservice/rest/server.php", data=data)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict) and j.get("exception"):
            raise ValueError(f"Moodle : {j.get('message') or j.get('errorcode')}")
        return j


def jeton_depuis_identifiants(url: str, identifiant: str, mot_de_passe: str,
                              transport: Optional[httpx.BaseTransport] = None) -> str:
    """Échange identifiant + mot de passe contre un jeton (le mot de passe n'est pas conservé)."""
    with httpx.Client(timeout=25, transport=transport, follow_redirects=True) as c:
        r = c.post(f"{url.rstrip('/')}/login/token.php",
                   data={"username": identifiant, "password": mot_de_passe, "service": "moodle_mobile_app"})
    r.raise_for_status()
    j = r.json()
    if not j.get("token"):
        raise ValueError(j.get("error") or "Moodle a refusé la connexion")
    return j["token"]


def donnees_moodle(url: str, jeton: str, fuseau: str = "Europe/Paris", jours: int = 21,
                   transport: Optional[httpx.BaseTransport] = None) -> Dict[str, Any]:
    m = Moodle(url, jeton, transport)
    tz = ZoneInfo(fuseau)
    site = m.appel("core_webservice_get_site_info")
    maintenant = int(time.time())
    devoirs: List[Dict[str, Any]] = []
    try:
        ev = m.appel("core_calendar_get_action_events_by_timesort", timesortfrom=maintenant - 7 * 86400,
                     timesortto=maintenant + jours * 86400, limitnum=40)
        for e in ev.get("events", []):
            quand = datetime.fromtimestamp(e.get("timesort") or e.get("timestart") or maintenant, tz)
            devoirs.append({
                "titre": (e.get("activityname") or e.get("name") or "").strip(),
                "cours": ((e.get("course") or {}).get("fullname") or "").strip(),
                "type": e.get("modulename") or "",
                "echeance": quand.isoformat(timespec="minutes"),
                "en_retard": bool(e.get("overdue")) or quand.timestamp() < maintenant,
                "url": e.get("url") or "",
                "action": ((e.get("action") or {}).get("name") or ""),
            })
    except Exception:  # noqa: BLE001 — certains Moodle bloquent cette fonction
        up = m.appel("core_calendar_get_calendar_upcoming_view")
        for e in up.get("events", []):
            quand = datetime.fromtimestamp(e.get("timesort") or e.get("timestart") or maintenant, tz)
            devoirs.append({"titre": e.get("name", ""), "cours": ((e.get("course") or {}).get("fullname") or ""),
                            "type": e.get("modulename") or "", "echeance": quand.isoformat(timespec="minutes"),
                            "en_retard": False, "url": e.get("url") or "", "action": ""})
    devoirs.sort(key=lambda d: d["echeance"])
    cours = []
    try:
        c = m.appel("core_course_get_enrolled_courses_by_timeline_classification", classification="inprogress")
        cours = [{"nom": x.get("fullname", ""), "progression": x.get("progress")} for x in c.get("courses", [])]
    except Exception:  # noqa: BLE001
        pass
    return {"site": site.get("sitename", "Moodle"), "devoirs": devoirs[:25], "cours": cours[:20]}


def moodle(cfg) -> Optional[Dict[str, Any]]:
    if cfg.demo:
        from datetime import timedelta

        tz = ZoneInfo(cfg["moi"]["fuseau"])
        n = datetime.now(tz).replace(second=0, microsecond=0)
        d = lambda j, h: (n + timedelta(days=j)).replace(hour=h, minute=0).isoformat(timespec="minutes")  # noqa: E731
        return {"site": "Moodle de l'école", "cours": [{"nom": "Marketing digital", "progression": 62}, {"nom": "Finance d'entreprise", "progression": 48}],
                "devoirs": [{"titre": "Étude de cas Fyxigo", "cours": "Marketing digital", "type": "assign", "echeance": d(1, 23), "en_retard": False, "url": "", "action": "Remettre"},
                            {"titre": "Quiz chapitre 4", "cours": "Finance d'entreprise", "type": "quiz", "echeance": d(3, 18), "en_retard": False, "url": "", "action": "Tenter"},
                            {"titre": "Dossier business plan", "cours": "Entrepreneuriat", "type": "assign", "echeance": d(8, 12), "en_retard": False, "url": "", "action": "Remettre"}]}
    mc = cfg["moodle"]
    if not mc.get("actif"):
        return None
    return donnees_moodle(mc.get("url", ""), cfg.secret("moodle_token"), cfg["moi"]["fuseau"])
