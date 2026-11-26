"""Справки (График): statuses, delay thresholds and the computed "Addition info" values (задание 03, 06, 07)."""
from __future__ import annotations

from datetime import date, datetime

# The 11 statuses of the задание, in order.
STATUSES = (
    "Нов", "Изпратен легализация", "Готови документи", "Подаден Миграция", "Подаден АЗ",
    "Получено разрешение", "Интервю за виза", "Преминал интервю", "Получена виза",
    "Пристигане България", "Работещ",
)
# Statuses that existed in Airtable but are not in the задание. Kept so old records stay readable;
# no delay colour for them.
EXTRA_STATUSES = ("Отказ", "Уволнен", "Избягал")
ALL_STATUSES = STATUSES + EXTRA_STATUSES

# задание раздел 07: (orange after more than N days, red after more than M days)
THRESHOLDS = {
    "Нов": (14, 21),
    "Изпратен легализация": (7, 14),
    "Готови документи": (7, 14),
    "Подаден Миграция": (40, 60),
    "Подаден АЗ": (14, 20),
    "Получено разрешение": (14, 21),
    "Преминал интервю": (60, 90),
}

# Columns of the График that the team edits (задание раздел 03), in display order.
TEXT_FIELDS = (("in_no", "Входящ номер"),)
DATE_FIELDS = (
    ("filed_date", "Дата на входиране"),
    ("permit_date", "Получено разрешение Миграция"),
    ("visa_interview_date", "Интервю за виза"),
    ("visa_date", "Получена виза"),
    ("ticket_date", "Самолетен билет"),
    ("arrival_date", "Дата на пристигане"),
    ("migration_reg_date", "Регистрация Миграция"),
    ("lk_submit_date", "Подаване на ЛК"),
    ("lk_pickup_date", "Взимане на ЛК"),
    ("residence_until", "Срок на пребиваване"),
)
EDITABLE = dict(TEXT_FIELDS + DATE_FIELDS)

# задание раздел 08: days left until „Срок на пребиваване“
RESIDENCE_BANDS = (("red", 0, 60), ("orange", 61, 90), ("yellow", 91, 120))


def _day(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def status_start(status: str, status_changed_at, created_at) -> date | None:
    """Day the current status clock starts: creation for „Нов“, else the manual change."""
    if status == "Нов":
        return _day(created_at) or _day(status_changed_at)
    return _day(status_changed_at) or _day(created_at)


def days_in_status(status, status_changed_at, created_at, today: date | None = None) -> int | None:
    start = status_start(status, status_changed_at, created_at)
    if start is None:
        return None
    return ((today or date.today()) - start).days


def delay(status: str, days: int | None) -> str:
    """'red', 'orange' or '' (задание 07: strictly more than the threshold; red wins)."""
    if days is None or status not in THRESHOLDS:
        return ""
    orange, red = THRESHOLDS[status]
    if days > red:
        return "red"
    if days > orange:
        return "orange"
    return ""


def days_over(status: str, days: int | None, colour: str) -> int:
    """Days past the threshold of the given colour, for sorting the daily report."""
    if not colour or days is None:
        return 0
    orange, red = THRESHOLDS[status]
    return days - (red if colour == "red" else orange)


def residence_days(residence_until, today: date | None = None) -> int | None:
    end = _day(residence_until)
    return None if end is None else (end - (today or date.today())).days


def residence_band(days: int | None) -> str:
    """'red' / 'orange' / 'yellow', 'expired' for past dates, 'none' without a date, '' when far away."""
    if days is None:
        return "none"
    if days < 0:
        return "expired"
    for name, lo, hi in RESIDENCE_BANDS:
        if lo <= days <= hi:
            return name
    return ""


def addition_info(row, today: date | None = None) -> dict:
    """The automatic "Addition info" values for one worker row."""
    d = days_in_status(row["status"], row["status_changed_at"], row["created_at"], today)
    colour = delay(row["status"], d)
    rd = residence_days(row["residence_until"], today)
    return {
        "created": _day(row["created_at"]),
        "status_changed": _day(row["status_changed_at"]),
        "status_start": status_start(row["status"], row["status_changed_at"], row["created_at"]),
        "days_in_status": d,
        "delay": colour,
        "days_over": days_over(row["status"], d, colour),
        "residence_days": rd,
        "residence_band": residence_band(rd),
    }
