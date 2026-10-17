"""The shared Google Calendar's private iCal link -> a flat list of events (recurring ones expanded)."""
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time

import icalendar
import recurring_ical_events

from .windows import TZ


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    free: bool  # TRANSP:TRANSPARENT ("show as available"); a hint for the AI, not a rule


def _local(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=TZ)
    return datetime.combine(v, time(), TZ)  # all-day: a date


def parse(ics_text, start, end):
    out = []
    for c in recurring_ical_events.of(icalendar.Calendar.from_ical(ics_text)).between(start, end):
        s = c["DTSTART"].dt
        e = c["DTEND"].dt if "DTEND" in c else s
        out.append(Event(str(c.get("UID", "")), str(c.get("SUMMARY", "")), _local(s), _local(e),
                         not isinstance(s, datetime), str(c.get("TRANSP", "")).upper() == "TRANSPARENT"))
    return out


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()
