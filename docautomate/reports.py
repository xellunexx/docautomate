"""Управленско табло, календар и рапорти (задание раздели 07, 08, 09). Pure queries over the workers table."""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from . import schedule as sched

# задание 08: the five calendar events and the График date each one comes from
EVENTS = (
    ("visa_interview_date", "Интервю за виза"),
    ("arrival_date", "Пристигане"),
    ("migration_reg_date", "Регистрация"),
    ("lk_submit_date", "Подаване на ЛК"),
    ("lk_pickup_date", "Взимане на ЛК"),
)
EVENT_LABEL = dict(EVENTS)

BASE_SQL = ("SELECT ca.*, e.name AS employer, co.name AS citizenship,"
            " coalesce(nullif(u.full_name, ''), u.username, 'Без отговорник') AS assigned"
            " FROM candidate ca LEFT JOIN employer e ON e.id=ca.employer_id"
            " LEFT JOIN country co ON co.id=ca.citizenship_id LEFT JOIN app_user u ON u.id=ca.assigned_user_id")


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def parse_day(text, default: date) -> date:
    try:
        return date.fromisoformat(str(text)[:10]) if text else default
    except ValueError:
        try:
            return datetime.strptime(str(text).strip(), "%d.%m.%Y").date()
        except ValueError:
            return default


def workers(conn, filters: dict | None = None):
    """Workers with the dashboard filters (employer list, visa type, status, assigned)."""
    f = filters or {}
    where, args = [], []
    if f.get("employers"):
        where.append(f"ca.employer_id IN ({','.join('?' * len(f['employers']))})")
        args += list(f["employers"])
    if f.get("visa"):
        where.append("ca.visa_type=?")
        args.append(f["visa"])
    if f.get("status"):
        where.append("ca.status=?")
        args.append(f["status"])
    if f.get("assigned") == "-":
        where.append("ca.assigned_user_id IS NULL")
    elif str(f.get("assigned") or "").isdigit():
        where.append("ca.assigned_user_id=?")
        args.append(int(f["assigned"]))
    sql = BASE_SQL + (" WHERE " + " AND ".join(where) if where else "")
    return conn.execute(sql + " ORDER BY ca.ref_no", args).fetchall()


def delayed(rows, today: date | None = None) -> list[dict]:
    """Red first, then orange; inside each colour by days over that colour's threshold (задание 07)."""
    out = []
    for r in rows:
        info = sched.addition_info(r, today)
        if info["delay"]:
            out.append({"r": r, **info})
    out.sort(key=lambda x: (0 if x["delay"] == "red" else 1, -x["days_over"], x["r"]["ref_no"] or 0))
    return out


def by_status(rows) -> list[tuple[str, int]]:
    counts = {s: 0 for s in sched.ALL_STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return [(s, n) for s, n in counts.items() if n or s in sched.STATUSES]


def residence(rows, today: date | None = None) -> dict:
    """Each worker in exactly one group: red / orange / yellow, expired, no date (задание 08)."""
    groups = {"red": [], "orange": [], "yellow": [], "expired": [], "none": []}
    for r in rows:
        d = sched.residence_days(r["residence_until"], today)
        band = sched.residence_band(d)
        if band in groups:
            groups[band].append({"r": r, "days": d})
    for k in ("red", "orange", "yellow", "expired"):
        groups[k].sort(key=lambda x: x["days"])
    return groups


def events(rows, start: date, end: date, kinds=None) -> list[dict]:
    """Calendar events with a date inside [start, end] (both included)."""
    out = []
    for r in rows:
        for field, label in EVENTS:
            if kinds and field not in kinds:
                continue
            d = sched._day(r[field])
            if d and start <= d <= end:
                out.append({"date": d, "field": field, "label": label, "r": r})
    out.sort(key=lambda x: (x["date"], x["label"], x["r"]["name_cyr"] or ""))
    return out


def calendar_weeks(start: date, end: date, evs) -> list[list[dict]]:
    """Weeks Mon..Sun covering [start, end], each day with its events."""
    by_day = {}
    for e in evs:
        by_day.setdefault(e["date"], []).append(e)
    first, _ = week_bounds(start)
    weeks, day = [], first
    while day <= end:
        weeks.append([{"date": day + timedelta(days=i), "events": by_day.get(day + timedelta(days=i), []),
                       "in_range": start <= day + timedelta(days=i) <= end} for i in range(7)])
        day += timedelta(days=7)
    return weeks


def movement(rows, today: date | None = None) -> dict:
    """Monday report (задание 09): last week's counts and events, and the events of the week that starts."""
    today = today or date.today()
    this_start, this_end = week_bounds(today)
    last_start, last_end = this_start - timedelta(days=7), this_start - timedelta(days=1)

    def count(field):
        return sum(1 for r in rows if (d := sched._day(r[field])) and last_start <= d <= last_end)
    return {
        "last": (last_start, last_end), "next": (this_start, this_end),
        "filed": count("filed_date"), "permits": count("permit_date"), "visas": count("visa_date"),
        "last_events": events(rows, last_start, last_end),
        "next_events": events(rows, this_start, this_end),
    }


def stage_times(rows) -> dict:
    """Median calendar days filing → permit and interview → visa, over records with both dates in order."""
    def med(a, b):
        days = []
        for r in rows:
            x, y = sched._day(r[a]), sched._day(r[b])
            if x and y and y >= x:
                days.append((y - x).days)
        return {"median": statistics.median(days) if days else None, "count": len(days)}
    return {"permit": med("filed_date", "permit_date"), "visa": med("visa_interview_date", "visa_date")}
