import sqlite3
from datetime import date, datetime, timezone

from jarvis_thibault.sources.agenda import _vers_apple, lire_evenements


def _db(tmp_path):
    p = tmp_path / "Calendar.sqlitedb"
    c = sqlite3.connect(p)
    c.executescript("""
    CREATE TABLE Calendar(ROWID INTEGER PRIMARY KEY, title TEXT, color TEXT);
    CREATE TABLE Location(ROWID INTEGER PRIMARY KEY, title TEXT, address TEXT);
    CREATE TABLE CalendarItem(ROWID INTEGER PRIMARY KEY, summary TEXT, description TEXT, start_date REAL,
      end_date REAL, all_day INTEGER, start_tz TEXT, location_id INTEGER, has_attendees INTEGER,
      last_modified REAL, UUID TEXT, calendar_id INTEGER, hidden INTEGER DEFAULT 0);
    CREATE TABLE OccurrenceCache(event_id INTEGER, calendar_id INTEGER, occurrence_start_date REAL, occurrence_end_date REAL);
    INSERT INTO Calendar VALUES (1,'Outlook',''),(2,'Anniversaires','');
    INSERT INTO Location VALUES (1,'Bureau','Lyon');
    """)
    u = lambda *a: _vers_apple(datetime(*a, tzinfo=timezone.utc))  # noqa: E731
    rows = [
        # 9h30 Paris = 8h30 UTC le 20/11
        (1, "Réunion", u(2026, 11, 20, 8, 30), u(2026, 11, 20, 9), 0, "Europe/Paris", 1, 1),
        # journée entière (heure flottante) le 21/11
        (2, "Salon", u(2026, 11, 21), u(2026, 11, 22), 1, "_float", None, 1),
        # journée entière d'hier : ne doit pas apparaître aujourd'hui
        (3, "Hier", u(2026, 11, 19), u(2026, 11, 20), 1, "_float", None, 1),
        (4, "Anniv Paul", u(2026, 11, 20, 10), u(2026, 11, 20, 11), 0, "Europe/Paris", None, 2),
    ]
    for rid, s, d, f, j, tz, loc, cal in rows:
        c.execute("INSERT INTO CalendarItem VALUES (?,?,?,?,?,?,?,?,0,0,?,?,0)",
                  (rid, s, "", d, f, j, tz, loc, f"u{rid}", cal))
    # occurrence d'un événement récurrent (Sport 18h Paris = 17h UTC)
    c.execute("INSERT INTO CalendarItem VALUES (5,'Sport','',?,?,0,'Europe/Paris',NULL,0,0,'u5',1,0)",
              (u(2026, 11, 13, 17), u(2026, 11, 13, 18)))
    c.execute("INSERT INTO OccurrenceCache VALUES (5,1,?,?)", (u(2026, 11, 20, 17), u(2026, 11, 20, 18)))
    c.commit()
    c.close()
    return p


def test_agenda(tmp_path):
    evts = lire_evenements(date(2026, 11, 20), 2, "Europe/Paris", ["Anniversaires"], db=_db(tmp_path))
    resume = [(e["jour"], e["debut"], e["titre"], e["lieu"]) for e in evts]
    assert resume == [
        ("2026-11-20", "09:30", "Réunion", "Bureau, Lyon"),
        ("2026-11-20", "18:00", "Sport", ""),
        ("2026-11-21", None, "Salon", ""),
    ]
