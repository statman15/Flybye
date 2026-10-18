"""The shared Google Calendar's private iCal link -> a flat list of events (recurring ones expanded)."""
import ipaddress
import socket
import urllib.parse
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


def _resolve(host):
    return [a[4][0] for a in socket.getaddrinfo(host, 443)]


def safe_url(url, resolve=_resolve):
    """Calendar links come from users: https only (webcal:// is Apple's name for it), and only public addresses,
    so a link can't read files on the runner or reach its metadata or private networks."""
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("calendar link must be https")
    if not all(ipaddress.ip_address(ip).is_global for ip in resolve(u.hostname)):
        raise ValueError("calendar link must point to a public host")
    return url


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, safe_url(newurl))  # every hop gets the same check


_opener = urllib.request.build_opener(_CheckedRedirect)


def fetch(url):
    # ponytail: checks DNS before connecting, so a host that re-resolves between check and fetch could slip by; fine for
    # read-only calendar fetches on a throwaway runner. Pin the connection to the checked IP if that ever matters.
    with _opener.open(safe_url(url), timeout=60) as r:
        return r.read(5_000_000)
