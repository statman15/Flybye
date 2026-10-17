"""The shared Google Calendar's private iCal link -> a flat list of events (recurring ones expanded)."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    free: bool  # TRANSP:TRANSPARENT ("show as available"); a hint for the AI, not a rule
