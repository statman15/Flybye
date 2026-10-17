import json
import re
import pathlib
from datetime import date

import yaml

from flybye import __main__ as main
from fakefs import new_store

FIX = pathlib.Path(__file__).parent / "fixtures"
CFG = yaml.safe_load((pathlib.Path(__file__).parents[2] / "config.yaml").read_text())
ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:w@x
SUMMARY:Work offsite
DTSTART;VALUE=DATE:20261113
DTEND;VALUE=DATE:20261116
END:VEVENT
END:VCALENDAR
"""


class Fakes:
    def __init__(self, lowest=858):
        self.sent, self.params = [], []
        self.explore = json.loads((FIX / "explore.json").read_text())
        self.flights = json.loads((FIX / "flights.json").read_text())
        self.flights["price_insights"]["lowest_price"] = lowest

    def get(self, p):
        self.params.append(p)
        return self.explore if p["engine"] == "google_travel_explore" else self.flights

    def chat(self, provider, messages):
        n = len(re.findall(r"^\d+\. ", messages[0]["content"], re.M))
        return json.dumps([{"i": i, "block": True, "why": "work"} for i in range(n)])

    def send(self, title, message, click=None):
        self.sent.append((title, message, click))


def run(today, f, db):
    main.daily(CFG, db, today, fetch=lambda url: ICS, chat=f.chat, get=f.get, send=f.send)


def test_daily_skips_blocked_window_stores_prices_and_spends_allowance():
    db, f = new_store(), Fakes()
    run(date(2026, 10, 17), f, db)  # Saturday: no summary
    searched = {(p["outbound_date"], p["return_date"]) for p in f.params if p["engine"] == "google_travel_explore"}
    assert ("2026-11-13", "2026-11-15") not in searched          # the offsite blocks that weekend
    used = db.execute("SELECT count(*) FROM searches").fetchone()[0]
    assert 0 < used <= main.pick.allowance(CFG["search"]["cap"], 0, date(2026, 10, 17)) + CFG["search"]["confirm_per_run"]
    assert db.execute("SELECT count(*) FROM prices").fetchone()[0] > 0
    assert f.sent == []                                         # 858 is above the typical low of 390


def test_cheap_confirmed_wish_city_sends_one_alert_with_link():
    db, f = new_store(), Fakes(lowest=350)
    run(date(2026, 10, 17), f, db)
    assert 1 <= len(f.sent) <= 2
    title, msg, click = f.sent[0]
    assert "Flybye" in title and "google.com/travel/flights" in click
    assert db.execute("SELECT count(*) FROM alerts").fetchone()[0] == len(f.sent)


def test_sunday_sends_summary_and_new_labels():
    db, f = new_store(), Fakes()
    run(date(2026, 10, 18), f, db)
    title, msg, _ = f.sent[-1]
    assert title.startswith("Flybye: this week") and "1 new calendar event" in msg
    run(date(2026, 10, 25), f, db)
    assert "new calendar event" not in f.sent[-1][1]            # labels only counted once


def test_monthly_cap_stops_searches():
    db, f = new_store(), Fakes()
    for _ in range(CFG["search"]["cap"]):
        db.execute("INSERT INTO searches VALUES('2026-10-02T00:00:00','x','y')")
    run(date(2026, 10, 17), f, db)
    assert f.params == []


# --- review fixes ------------------------------------------------------------------------------------------------
def test_confirm_failure_does_not_skip_sunday_summary():
    db, f = new_store(), Fakes(lowest=350)

    def get(p):
        if p["engine"] == "google_flights" and "arrival_id" in p and p["arrival_id"] != "OPO":
            raise RuntimeError("SerpApi: timeout")
        return f.get(p)
    main.daily(CFG, db, date(2026, 10, 18), fetch=lambda url: ICS, chat=f.chat, get=get, send=f.send)
    assert f.sent and f.sent[-1][0].startswith("Flybye: this week")


def test_quota_error_stops_the_sweep_and_tells_us():
    db, f = new_store(), Fakes()

    def get(p):
        f.params.append(p)
        return {"error": "Your account has run out of searches."}
    main.daily(CFG, db, date(2026, 10, 17), fetch=lambda url: ICS, chat=f.chat, get=get, send=f.send)
    assert len(f.params) == 1
    assert any("out of searches" in m for _, m, _ in f.sent)


def test_weekly_cap_checked_before_spending_a_confirm():
    db, f = new_store(), Fakes(lowest=350)
    for d in ("2026-10-12", "2026-10-13"):
        db.execute("INSERT INTO alerts VALUES(?, 'X', 'a', 'b', 1, 'weekend')", (d,))
    run(date(2026, 10, 17), f, db)
    assert not [p for p in f.params if p["engine"] == "google_flights" and p.get("arrival_id") != "OPO"]


def test_summary_sends_label_counts_not_titles():
    db, f = new_store(), Fakes()
    run(date(2026, 10, 18), f, db)
    msg = f.sent[-1][1]
    assert "Work offsite" not in msg and "1 new calendar event" in msg


def test_summary_ignores_prices_older_than_three_weeks():
    db, f = new_store(), Fakes()
    run(date(2026, 10, 18), f, db)
    db.execute("UPDATE prices SET seen='2026-09-01'")
    f.sent.clear()
    f.explore = {"destinations": []}
    f.flights = {"best_flights": [], "other_flights": [], "price_insights": {}}
    run(date(2026, 10, 25), f, db)
    assert "No priced trips" in f.sent[-1][1]
