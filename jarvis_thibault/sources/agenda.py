"""Agenda : lit l'app Calendrier du Mac (iCloud, Outlook/Exchange, Google... tout
ce qui est ajouté dans Calendrier).

Lecture en lecture seule de la base SQLite de Calendrier, comme le connecteur
``apple_calendar`` d'OpenJarvis (Apache-2.0) dont les requêtes sont reprises.
Nécessite l'« Accès complet au disque » pour l'app qui lance Jarvis
(Réglages Système → Confidentialité et sécurité → Accès complet au disque).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

CAL_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.calendar"
    / "Calendar.sqlitedb"
)
_EPOQUE_APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)

_COLONNES = """
SELECT ci.summary, ci.start_date, ci.end_date, ci.all_day, ci.start_tz,
       ci.location_id, c.title AS calendrier
"""

_REQ_SIMPLE = (
    _COLONNES
    + """
FROM CalendarItem ci JOIN Calendar c ON ci.calendar_id = c.ROWID
WHERE ci.start_date < ? AND COALESCE(ci.end_date, ci.start_date) >= ?
  AND ci.summary IS NOT NULL AND ci.hidden = 0
"""
)

_REQ_OCCURRENCES = (
    _REQ_SIMPLE
    + """
  AND NOT EXISTS (SELECT 1 FROM OccurrenceCache m
                  WHERE m.event_id = ci.ROWID AND m.occurrence_start_date = ci.start_date)
UNION
SELECT ci.summary, oc.occurrence_start_date, oc.occurrence_end_date, ci.all_day,
       ci.start_tz, ci.location_id, c.title
FROM OccurrenceCache oc
JOIN CalendarItem ci ON oc.event_id = ci.ROWID
JOIN Calendar c ON oc.calendar_id = c.ROWID
WHERE oc.occurrence_start_date < ? AND oc.occurrence_end_date >= ?
  AND ci.summary IS NOT NULL AND ci.hidden = 0
"""
)


def _vers_apple(dt: datetime) -> float:
    return (dt - _EPOQUE_APPLE).total_seconds()


def _depuis_apple(sec: float) -> datetime:
    return _EPOQUE_APPLE + timedelta(seconds=sec)


def _heure_locale(sec: float, tz_evt: str | None, journee: bool, tz: ZoneInfo) -> datetime:
    dt = _depuis_apple(sec)
    if journee or not tz_evt or tz_evt == "_float":
        # Heure « flottante » : les composantes UTC sont l'heure murale.
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def lire_evenements(
    jour: date, nb_jours: int, fuseau: str, ignores: List[str] | None = None,
    db: Path = CAL_DB,
) -> List[Dict[str, Any]]:
    tz = ZoneInfo(fuseau)
    debut = datetime.combine(jour, time.min, tzinfo=tz)
    fin = debut + timedelta(days=nb_jours)
    if not db.exists():
        raise FileNotFoundError(
            "Base Calendrier introuvable ou inaccessible : donnez l'« Accès complet "
            "au disque » à l'app Jarvis (Réglages Système → Confidentialité)."
        )
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(OccurrenceCache)")}
        bornes = (_vers_apple(fin), _vers_apple(debut))
        if {"event_id", "calendar_id", "occurrence_start_date", "occurrence_end_date"} <= cols:
            lignes = conn.execute(_REQ_OCCURRENCES, bornes + bornes).fetchall()
        else:
            lignes = conn.execute(_REQ_SIMPLE, bornes).fetchall()
        lieux: Dict[int, str] = {}
        evts: List[Dict[str, Any]] = []
        vus = set()
        for titre, d, f, journee, tz_evt, loc_id, cal in lignes:
            if ignores and cal in ignores:
                continue
            journee = bool(journee)
            dt_debut = _heure_locale(d, tz_evt, journee, tz)
            dt_fin = _heure_locale(f, tz_evt, journee, tz) if f else None
            if dt_debut >= fin:
                continue
            if (dt_fin is not None and dt_fin <= debut and dt_fin != dt_debut) or (
                dt_debut < debut and (dt_fin is None or dt_fin == dt_debut)
            ):
                continue
            cle = (titre, dt_debut.isoformat())
            if cle in vus:
                continue
            vus.add(cle)
            if loc_id and loc_id not in lieux:
                row = conn.execute(
                    "SELECT title, address FROM Location WHERE ROWID = ?", (loc_id,)
                ).fetchone()
                lieux[loc_id] = ", ".join(p for p in (row or ()) if p)
            evts.append(
                {
                    "titre": titre,
                    "jour": max(dt_debut, debut).date().isoformat(),
                    "debut": None if journee else dt_debut.strftime("%H:%M"),
                    "fin": None if journee or not dt_fin else dt_fin.strftime("%H:%M"),
                    "journee": journee,
                    "lieu": lieux.get(loc_id, "") if loc_id else "",
                    "calendrier": cal,
                    "_tri": dt_debut.isoformat(),
                }
            )
        evts.sort(key=lambda e: (e["jour"], not e["journee"], e["_tri"]))
        for e in evts:
            e.pop("_tri")
        return evts
    finally:
        conn.close()


def agenda(cfg) -> Dict[str, Any]:
    fuseau = cfg["moi"]["fuseau"]
    aujourd_hui = datetime.now(ZoneInfo(fuseau)).date()
    if cfg.demo:
        from .demo import agenda_demo

        evts = agenda_demo(aujourd_hui)
    else:
        evts = lire_evenements(
            aujourd_hui, 2, fuseau, cfg["agenda"].get("calendriers_ignores") or []
        )
    demain = (aujourd_hui + timedelta(days=1)).isoformat()
    return {
        "aujourdhui": [e for e in evts if e["jour"] == aujourd_hui.isoformat()],
        "demain": [e for e in evts if e["jour"] == demain],
    }
