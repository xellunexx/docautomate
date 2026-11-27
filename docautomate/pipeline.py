"""Pipeline of a worker: „Следваща стъпка“ (next step).

The задание (03) says the status changes only by hand. The pipeline keeps that rule: nothing moves
by itself. When staff press „Следваща стъпка“, the app checks what the next status needs, shows
what is missing, generates the documents when the step calls for it, and only then sets the
status (as a manual change, with history).

Everything below marked DEFAULT is a choice the задание leaves open (see docs/pipeline.md). The
tables are plain data, so a default is changed in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import schedule as sched

# DEFAULT: the path of each visa type through the 11 statuses of the задание.
PATHS = {
    "3 години": sched.STATUSES,
    "1 година": sched.STATUSES,
    # Seasonal work up to 90 days goes through the Employment Agency, not a Migration permit.
    "3 месеца": tuple(s for s in sched.STATUSES if s != "Подаден Миграция"),
    # The worker is already in Bulgaria: no legalisation, visa or arrival.
    "Удължаване": ("Нов", "Готови документи", "Подаден Миграция", "Подаден АЗ", "Получено разрешение", "Работещ"),
}
FILING_STATUSES = ("Подаден Миграция", "Подаден АЗ")

# DEFAULT: upcoming dates shown as deadlines, and how far ahead.
UPCOMING_DAYS = 14
UPCOMING = (("visa_interview_date", "Интервю за виза"), ("ticket_date", "Самолетен билет"),
            ("arrival_date", "Пристигане"), ("lk_submit_date", "Подаване на ЛК"),
            ("lk_pickup_date", "Взимане на ЛК"))
PASSPORT_WARN_DAYS = 180  # DEFAULT: warn when the passport expires within six months
STALL_DAYS = 3            # Xel, 26.11.2026: warn after 3 days without movement (in the app only)


def stalled_days(w: dict, today: date | None = None) -> int | None:
    """Days without a status change when that is STALL_DAYS or more and the worker still has a next step."""
    if not next_status(w.get("status") or "", w.get("visa_type") or ""):
        return None
    d = sched.days_in_status(w.get("status"), w.get("status_changed_at"), w.get("created_at"), today)
    return d if d is not None and d >= STALL_DAYS else None


def stalled(rows, today: date | None = None) -> list[dict]:
    """Workers without movement for STALL_DAYS or more, longest first (dashboard list)."""
    out = [{"r": r, "days": n, "next": next_status(r["status"], r["visa_type"])}
           for r in rows if (n := stalled_days(dict(r), today)) is not None]
    return sorted(out, key=lambda x: -x["days"])


@dataclass
class Check:
    ok: bool
    text: str
    hard: bool = True          # a failed hard check blocks the step; a soft one only warns
    link: str = ""             # where to fix it (anchor or URL), filled in by the view
    blank: bool = False        # a template field that will print as „……“ (shown folded)
    miss: str = ""             # wording when the check fails, if different from `text`
    auto: bool = False         # required by „Пусни процеса“ (the one-click run) even when soft for the button

    @property
    def stops_run(self) -> bool:
        return not self.ok and (self.hard or self.auto)

    @property
    def label(self) -> str:
        return self.text if self.ok or not self.miss else self.miss


@dataclass
class Step:
    current: str
    path: tuple
    next: str | None
    checks: list = field(default_factory=list)
    generate: bool = False     # the step generates the documents of the visa type
    note: str = ""
    manual: str = ""           # why the one-click run stops here: no data shows the step happened

    @property
    def run_blockers(self) -> list:
        """Checks that stop „Пусни процеса“ at this step."""
        return [c for c in self.checks if c.stops_run]

    @property
    def blocked(self) -> bool:
        return any(not c.ok and c.hard for c in self.checks)

    @property
    def warnings(self) -> list:
        return [c for c in self.checks if not c.ok and not c.hard]


def path_for(visa_type: str) -> tuple:
    return PATHS.get(visa_type or "", sched.STATUSES)


def next_status(status: str, visa_type: str) -> str | None:
    path = path_for(visa_type)
    if status not in path:
        return None
    i = path.index(status)
    return path[i + 1] if i + 1 < len(path) else None


def _filled(w, key) -> bool:
    return bool((w.get(key) or "").strip()) if isinstance(w.get(key), str) else w.get(key) is not None


def plan_step(w: dict, *, attachments: set, doc_plan: dict | None, position: dict | None,
              iso3: str = "", today: date | None = None) -> Step:
    """What „Следваща стъпка“ would do for worker `w` now. Pure: reads only what it is given."""
    today = today or date.today()
    visa = w.get("visa_type") or ""
    status = w.get("status") or "Нов"
    path = path_for(visa)
    step = Step(status, path, next_status(status, visa))
    if status not in path:
        step.note = (f"Статус „{status}“ е извън процеса за тип виза „{visa or '—'}“."
                     " Сменете статуса ръчно от графика.")
        return step
    if step.next is None:
        step.note = "Работникът е на последния етап. Следете срока на пребиваване."
        return step
    nxt, c = step.next, step.checks

    def need(key, label, hard=True, link=None, auto=False):
        link = link or (f"#s-{key}" if key in sched.EDITABLE else "#schedule")
        c.append(Check(_filled(w, key), f"Попълнено: {label}", hard, link, miss=f"Не е попълнено: {label}",
                       auto=auto))

    def attach(cat, label, hard=False, auto=False):
        c.append(Check(cat in attachments, f"Прикачен файл: {label}", hard, "#attachments",
                       miss=f"Няма прикачен файл: {label}", auto=auto))

    if nxt == "Изпратен легализация":
        need("visa_type", "Тип виза", link="#cand-form")
        need("employer_id", "Работодател", link="#cand-form")
        need("position_id", "Длъжност", link="#cand-form")
        attach("passport", "Паспорт и свидетелство за съдимост", auto=True)
    elif nxt == "Готови документи":
        need("visa_type", "Тип виза", link="#cand-form")
        need("employer_id", "Работодател", link="#cand-form")
        need("position_id", "Длъжност", link="#cand-form")
        pos = position or {}
        if visa != "3 месеца":
            text = ((pos.get("obosnovka_ext") or pos.get("obosnovka")) if visa == "Удължаване"
                    else pos.get("obosnovka"))
            c.append(Check(bool((text or "").strip()), "Обосновката на длъжността е написана", True, "position-ai",
                           miss="Обосновката на длъжността е празна (напишете я с AI)"))
        c.append(Check(bool((pos.get("dh_duties") or "").strip()), "Длъжностната характеристика е написана",
                       True, "position-ai", miss="Длъжностната характеристика е празна (напишете я с AI)"))
        if doc_plan is not None:
            if doc_plan.get("error"):
                c.append(Check(False, doc_plan["error"], True, "#documents"))
            for t in doc_plan.get("templates", []):
                miss = [label for _, label in t["missing"]]
                c.append(Check(not miss, f"„{t['t']['name']}“: " + ("всички данни са попълнени" if not miss else
                               "липсва " + ", ".join(miss[:6]) + (" …" if len(miss) > 6 else "")
                               ), False, "#documents", blank=True))
        step.generate = True
    elif nxt in FILING_STATUSES and not any(s in FILING_STATUSES for s in path[:path.index(nxt)]):
        # the first filing of this path: the incoming number and date are known now
        need("in_no", "Входящ номер")
        need("filed_date", "Дата на входиране")
        step.generate = True   # the control sheet carries the incoming number
    elif nxt in FILING_STATUSES:
        # DEFAULT: no field records the filing at the Employment Agency, so the run asks a person
        step.manual = (f"Няма поле, от което да се види, че е „{nxt}“. Натиснете „Следваща стъпка: {nxt}“,"
                       " когато е направено, и пуснете процеса пак.")
    elif nxt == "Получено разрешение":
        need("permit_date", "Получено разрешение Миграция")
        attach("permit", "Разрешение Миграция")
    elif nxt == "Интервю за виза":
        need("visa_interview_date", "Интервю за виза")
        attach("insurance", "Медицинска застраховка")
        if visa == "3 години" and iso3 in ("IND", "NPL"):
            attach("invitation", "Invitation Letter")
        attach("visa_interview", "Документи интервю виза")
    elif nxt == "Преминал интервю":
        d = sched._day(w.get("visa_interview_date"))
        c.append(Check(bool(d and d <= today), "Датата на интервюто за виза е минала", False, "#s-visa_interview_date",
                       miss="Датата на интервюто за виза още не е минала или липсва", auto=True))
    elif nxt == "Получена виза":
        need("visa_date", "Получена виза")
    elif nxt == "Пристигане България":
        need("arrival_date", "Дата на пристигане")
        need("ticket_date", "Самолетен билет", hard=False)
    elif nxt == "Работещ":
        if visa == "Удължаване":
            need("residence_until", "Срок на пребиваване", hard=False, auto=True)
        else:
            need("migration_reg_date", "Регистрация Миграция", hard=False, auto=True)
            attach("nap", "НАП")
    return step


def deadlines(w: dict, today: date | None = None) -> list[tuple[str, str, str]]:
    """(level, text, anchor) for the deadlines panel: level is 'red', 'orange', 'yellow' or ''."""
    today = today or date.today()
    out = []
    info = sched.addition_info(w, today)
    status = w.get("status") or ""
    if status in sched.THRESHOLDS and info["days_in_status"] is not None:
        orange, red = sched.THRESHOLDS[status]
        d = info["days_in_status"]
        if info["delay"] == "red":
            out.append(("red", f"{d} дни в „{status}“: над червения праг ({red} дни).", "#schedule"))
        elif info["delay"] == "orange":
            out.append(("orange", f"{d} дни в „{status}“: над оранжевия праг ({orange}); червено след {red}.",
                        "#schedule"))
        else:
            out.append(("", f"{d} дни в „{status}“; оранжево след {orange}.", "#schedule"))
    stall = stalled_days(w, today)
    if stall is not None:
        out.insert(0, ("orange", f"Без движение {stall} дни (предупреждение след {STALL_DAYS}). Следващата стъпка е"
                                 f" „{next_status(status, w.get('visa_type') or '')}“.", "#pipeline"))
    for key, label in UPCOMING:
        day = sched._day(w.get(key))
        if day and today <= day <= today + timedelta(days=UPCOMING_DAYS):
            left = (day - today).days
            when = "днес" if left == 0 else ("утре" if left == 1 else f"след {left} дни")
            out.append(("orange" if left <= 2 else "", f"{label}: {day:%d.%m.%Y} ({when}).", "#schedule"))
    exp = sched._day(w.get("passport_expiry"))
    if exp:
        left = (exp - today).days
        if left < 0:
            out.append(("red", f"Паспортът е изтекъл на {exp:%d.%m.%Y}.", "#cand-form"))
        elif left <= PASSPORT_WARN_DAYS:
            out.append(("orange", f"Паспортът изтича на {exp:%d.%m.%Y} (след {left} дни).", "#cand-form"))
    rd, band = info["residence_days"], info["residence_band"]
    if rd is not None:
        if rd < 0:
            out.append(("red", "Срокът на пребиваване е изтекъл.", "#schedule"))
        elif band in ("red", "orange", "yellow"):
            out.append((band, f"Пребиваването изтича след {rd} дни. Помислете за удължаване.", "#schedule"))
    return out
