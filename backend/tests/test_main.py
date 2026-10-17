import json
import re
import pathlib
from datetime import date, datetime

import pytest
import yaml

from fakefs import new_store
from flybye import __main__ as main

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


@pytest.fixture(autouse=True)
def app_url(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://app.test/Flybye/")


def fresh():
    st = new_store()
    st.now = lambda: datetime(2026, 10, 17, 8)
    return st


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

    def send(self, title, message, data=None, link=None):
        self.sent.append((title, message, data, link))


def run(today, f, st):
    main.daily(CFG, st, today, fetch=lambda url: ICS, chat=f.chat, get=f.get, send=f.send)


def test_daily_skips_blocked_window_stores_prices_and_spends_allowance():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)  # Saturday: no summary
    searched = {(p["outbound_date"], p["return_date"]) for p in f.params if p["engine"] == "google_travel_explore"}
    assert ("2026-11-13", "2026-11-15") not in searched          # the offsite blocks that weekend
    used = st.budget("2026-10")["used"]
    assert 0 < used <= main.pick.allowance(CFG["search"]["cap"], 0, date(2026, 10, 17)) + CFG["search"]["confirm_per_run"]
    assert st.fs.data["latest"] and st.route_prices("DEN", "weekend")
    assert f.sent == []                                         # 858 is above the typical low of 390


def test_cheap_confirmed_wish_city_sends_one_alert_with_app_link():
    st, f = fresh(), Fakes(lowest=350)
    run(date(2026, 10, 17), f, st)
    assert 1 <= len(f.sent) <= 2
    title, msg, data, link = f.sent[0]
    assert "Flybye" in title and set(data) == {"window_id", "code"}
    assert link == f"https://app.test/Flybye/#trip={data['window_id']}%7C{data['code']}"
    assert len(st.alerts()) == len(f.sent)


def test_sunday_sends_summary_and_new_labels():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    title, msg, _, link = f.sent[-1]
    assert title.startswith("Flybye: this week") and "1 new calendar event" in msg and link == "https://app.test/Flybye/"
    run(date(2026, 10, 25), f, st)
    assert "new calendar event" not in f.sent[-1][1]            # labels only counted once


def test_every_daily_run_writes_the_suggestions_doc():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)                              # a Saturday: no summary, still published
    doc = st.fs.data["suggestions"]["current"]
    assert set(doc) == {"updated", "windows", "top"} and doc["windows"] and 1 <= len(doc["top"]) <= 4
    ids = {w["id"] for w in doc["windows"]}
    assert "weekend:2026-11-13:2026-11-15" not in ids           # the offsite blocks it
    assert all(t["window_id"] in ids for t in doc["top"])
    assert all(len(w["picks"]) <= 8 for w in doc["windows"])


def test_monthly_cap_stops_searches():
    st, f = fresh(), Fakes()
    st.fs.collection("meta").document("budget").set({"month": "2026-10", "used": CFG["search"]["cap"], "last": {}})
    run(date(2026, 10, 17), f, st)
    assert f.params == []


def test_budget_used_starts_over_in_a_new_month():
    st, f = fresh(), Fakes()
    st.fs.collection("meta").document("budget").set({"month": "2026-09", "used": CFG["search"]["cap"], "last": {}})
    run(date(2026, 10, 17), f, st)
    assert f.params and st.budget("2026-10")["used"] == len(f.params)


def test_settings_are_seeded_from_config_then_the_app_wins(monkeypatch):
    monkeypatch.setenv("FLYBYE_CONFIG", str(pathlib.Path(__file__).parents[2] / "config.yaml"))
    st = fresh()
    cfg = main.load_cfg(st)
    assert cfg["cities"] == CFG["cities"] and "ai" in cfg
    saved = st.fs.data["settings"]["main"]
    assert "ai" not in saved and "db" not in saved and saved["home"] == "ORD"
    saved["home"] = "MDW"
    assert main.load_cfg(st)["home"] == "MDW"


# --- review fixes ------------------------------------------------------------------------------------------------
def test_confirm_failure_does_not_skip_sunday_summary():
    st, f = fresh(), Fakes(lowest=350)

    def get(p):
        if p["engine"] == "google_flights" and "arrival_id" in p and p["arrival_id"] != "OPO":
            raise RuntimeError("SerpApi: timeout")
        return f.get(p)
    main.daily(CFG, st, date(2026, 10, 18), fetch=lambda url: ICS, chat=f.chat, get=get, send=f.send)
    assert f.sent and f.sent[-1][0].startswith("Flybye: this week")


def test_quota_error_stops_the_sweep_and_tells_us():
    st, f = fresh(), Fakes()

    def get(p):
        f.params.append(p)
        return {"error": "Your account has run out of searches."}
    main.daily(CFG, st, date(2026, 10, 17), fetch=lambda url: ICS, chat=f.chat, get=get, send=f.send)
    assert len(f.params) == 1
    assert any("out of searches" in m for _, m, _, _ in f.sent)


def test_weekly_cap_checked_before_spending_a_confirm():
    st, f = fresh(), Fakes(lowest=350)
    for d in ("2026-10-12", "2026-10-13"):
        st.add_alert({"at": d, "code": "X", "out": "a", "ret": "b", "price": 1, "kind": "weekend"})
    run(date(2026, 10, 17), f, st)
    assert not [p for p in f.params if p["engine"] == "google_flights" and p.get("arrival_id") != "OPO"]


def test_summary_sends_label_counts_not_titles():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    msg = f.sent[-1][1]
    assert "Work offsite" not in msg and "1 new calendar event" in msg


def test_summary_ignores_prices_older_than_three_weeks():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    for d in st.fs.data["latest"].values():
        d["seen"] = "2026-09-01"
    f.sent.clear()
    f.explore = {"destinations": []}
    f.flights = {"best_flights": [], "other_flights": [], "price_insights": {}}
    run(date(2026, 10, 25), f, st)
    assert "No priced trips" in f.sent[-1][1]


# --- M2 review fixes ---------------------------------------------------------------------------------------------
def test_app_link_encodes_the_trip_for_fcm(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://x.test/Flybye/")
    assert main.app_link("weekend:2026-11-13:2026-11-15", "DEN") == "https://x.test/Flybye/#trip=weekend:2026-11-13:2026-11-15%7CDEN"
    assert main.app_link() == "https://x.test/Flybye/"


def test_windows_report_hides_titles_and_dates_in_ci():
    from flybye.windows import Window
    w = [Window("weekend", date(2026, 11, 6), date(2026, 11, 8), None)]
    labels = [{"title": "Dentist", "why": "appt", "block": True, "override": None}]
    local = "\n".join(main.windows_report(w, labels, CFG, ci=False))
    ci = "\n".join(main.windows_report(w, labels, CFG, ci=True))
    assert "Dentist" in local and "2026-11-06" in local
    assert "Dentist" not in ci and "2026-11" not in ci and "1 free window" in ci and "1 calendar event" in ci


def test_suggestions_updated_has_a_timezone():
    from datetime import datetime as dt
    st, f = new_store(), Fakes()
    run(date(2026, 10, 17), f, st)
    doc = st.fs.collection("suggestions").document("current").get().to_dict()
    assert dt.fromisoformat(doc["updated"]).tzinfo is not None
