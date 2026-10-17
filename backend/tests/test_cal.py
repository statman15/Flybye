from datetime import datetime
from zoneinfo import ZoneInfo

from flybye.cal import parse

TZ = ZoneInfo("America/Chicago")
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly@x
SUMMARY:Laura volleyball
DTSTART;TZID=America/Chicago:20261104T190000
DTEND;TZID=America/Chicago:20261104T210000
RRULE:FREQ=WEEKLY;COUNT=3
END:VEVENT
BEGIN:VEVENT
UID:allday@x
SUMMARY:Wedding
DTSTART;VALUE=DATE:20261114
DTEND;VALUE=DATE:20261115
TRANSP:TRANSPARENT
END:VEVENT
BEGIN:VEVENT
UID:utc@x
SUMMARY:Dentist
DTSTART:20261120T150000Z
DTEND:20261120T160000Z
END:VEVENT
END:VCALENDAR
"""
START, END = datetime(2026, 11, 1, tzinfo=TZ), datetime(2026, 12, 31, tzinfo=TZ)


def test_weekly_rule_expands():
    v = [e for e in parse(ICS, START, END) if e.uid == "weekly@x"]
    assert [e.start.day for e in v] == [4, 11, 18]


def test_all_day_runs_midnight_to_midnight_local():
    e = next(e for e in parse(ICS, START, END) if e.uid == "allday@x")
    assert e.all_day and e.free
    assert e.start == datetime(2026, 11, 14, tzinfo=TZ) and e.end == datetime(2026, 11, 15, tzinfo=TZ)


def test_utc_converted_to_chicago():
    e = next(e for e in parse(ICS, START, END) if e.uid == "utc@x")
    assert e.start.tzinfo is not None and e.start.astimezone(TZ).hour == 9 and not e.free
