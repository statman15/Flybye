"""Candidate trip windows, US holidays, and whether a window is free. Pure: no I/O."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
BUFFER = timedelta(hours=3)
RETURN_AT = time(21)


@dataclass(frozen=True)
class Window:
    kind: str  # weekend | 3day | long
    out: date
    ret: date
    holiday: str | None

    @property
    def id(self):
        return f"{self.kind}:{self.out}:{self.ret}"


def _nth(year, month, weekday, n):
    """n-th weekday of a month; n=-1 is the last."""
    if n > 0:
        d = date(year, month, 1)
        return d + timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def holidays(year):
    tg = _nth(year, 11, 3, 4)
    return {date(year, 1, 1): "New Year's Day", _nth(year, 1, 0, 3): "MLK Day", _nth(year, 2, 0, 3): "Presidents' Day",
            _nth(year, 5, 0, -1): "Memorial Day", date(year, 6, 19): "Juneteenth", date(year, 7, 4): "July 4th",
            _nth(year, 9, 0, 1): "Labor Day", tg: "Thanksgiving", tg + timedelta(days=1): "Day after Thanksgiving",
            date(year, 12, 25): "Christmas"}


def window(kind, out, ret, hol=None):
    """A Window, named after the first US holiday inside it (if any)."""
    hol = hol or {**holidays(out.year), **holidays(out.year + 1)}
    return Window(kind, out, ret, next((hol[x] for x in sorted(hol) if out <= x <= ret), None))


def parse(window_id):
    kind, out, ret = window_id.split(":")
    return window(kind, date.fromisoformat(out), date.fromisoformat(ret))


# kind -> list of (departure weekday, nights)
SHAPES = {"weekend": [(5, 1)], "3day": [(4, 2), (5, 2)]}


def candidates(today, trips):
    hol = {**holidays(today.year), **holidays(today.year + 1)}
    out = []
    for kind, c in trips.items():
        if not c.get("enabled"):
            continue
        shapes = SHAPES.get(kind) or [(5, n) for n in c.get("nights", [7])]
        first, last = today + timedelta(weeks=c["weeks"][0]), today + timedelta(weeks=c["weeks"][1])
        d = first
        while d <= last:
            for wd, nights in shapes:
                if d.weekday() == wd:
                    out.append(window(kind, d, d + timedelta(days=nights), hol))
            d += timedelta(days=1)
    return sorted(out, key=lambda w: (w.out, w.kind))


def span(w):
    """What the trip occupies: from 3h before departure (after work Thu/Fri, morning otherwise) to 3h after return."""
    dep = time(17) if w.out.weekday() in (3, 4) else time(7)
    return (datetime.combine(w.out, dep, TZ) - BUFFER, datetime.combine(w.ret, RETURN_AT, TZ) + BUFFER)


def days_off(w, evening=False):
    """PTO days: weekdays (not US holidays) the trip uses, both ends included; evening=True when the flight out leaves
    at 5pm or later, so the departure day is a work day."""
    hol = {**holidays(w.out.year), **holidays(w.ret.year)}
    days = (w.out + timedelta(n) for n in range(evening, (w.ret - w.out).days + 1))
    return sum(d.weekday() < 5 and d not in hol for d in days)


def is_free(w, blockers):
    a, b = span(w)
    return not any(e.start < b and e.end > a for e in blockers)
