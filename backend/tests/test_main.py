import json
import re
import pathlib
from datetime import date, datetime

import pytest
import yaml

from fakefs import FakeFS, new_store
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


ICS_B = ICS.replace(b"w@x", b"b@x").replace(b"Work offsite", b"Laura trip").replace(b"20261113", b"20261120").replace(b"20261116", b"20261123")
KEYS = {"serpapi": "sk", "gemini": "gk", "calendars": [{"name": "Home", "url": "https://cal.test/a"}]}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://app.test/Flybye/")
    monkeypatch.setenv("FLYBYE_CONFIG", str(pathlib.Path(__file__).parents[2] / "config.yaml"))


def seed(st, **over):
    st._set("private", "keys", {**KEYS, **over})
    return st


def fresh(**over):
    st = new_store()
    st.now = lambda: datetime(2026, 10, 17, 8)
    return seed(st, **over)


class Fakes:
    def __init__(self, lowest=858):
        self.sent, self.params, self.serp_keys, self.chat_keys, self.fetched = [], [], [], [], []
        self.cals, self.weather_urls = {}, []
        self.explore = json.loads((FIX / "explore.json").read_text())
        self.flights = json.loads((FIX / "flights.json").read_text())
        self.flights["price_insights"]["lowest_price"] = lowest
        self.flex = {"destinations": []}  # Explore without dates (Google's flexible longer trips)

    def fetch(self, url):
        self.fetched.append(url)
        return self.cals.get(url, ICS)

    def get(self, p, key):
        self.params.append(p)
        self.serp_keys.append(key)
        if p["engine"] == "google_travel_explore":
            return self.explore if "outbound_date" in p else self.flex
        return self.flights

    def wget(self, url):
        self.weather_urls.append(url)
        if "archive-api" in url:  # every day of ten years, hot and dry
            t = [f"{y}-{m:02d}-01" for y in range(2016, 2026) for m in range(1, 13)]
            return {"daily": {"time": t, "temperature_2m_max": [95] * len(t), "temperature_2m_min": [75] * len(t),
                              "precipitation_sum": [0.0] * len(t)}}
        return {"daily": {"time": ["x"], "temperature_2m_max": [75], "temperature_2m_min": [55], "precipitation_probability_max": [20]}}

    def chat(self, provider, messages, key):
        self.chat_keys.append(key)
        n = len(re.findall(r"^\d+\. ", messages[0]["content"], re.M))
        return json.dumps([{"i": i, "block": True, "why": "work"} for i in range(n)])

    def send(self, title, message, data=None, link=None):
        self.sent.append((title, message, data, link))


def run(today, f, st, cfg=CFG):
    main.daily(cfg, st, today, fetch=f.fetch, chat=f.chat, get=f.get, send=f.send, wget=f.wget)


def test_daily_skips_blocked_window_stores_prices_and_spends_allowance():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)  # Saturday: no summary
    searched = {(p["outbound_date"], p["return_date"]) for p in f.params if "outbound_date" in p}
    assert ("2026-11-13", "2026-11-15") not in searched          # the offsite blocks that weekend
    used = st.budget("2026-10")["used"]
    assert 0 < used <= main.pick.allowance(CFG["search"]["cap"], 0, date(2026, 10, 17)) + CFG["search"]["confirm_per_run"]
    assert st.fs.docs("spaces/s1/latest") and st.route_prices("DEN", "weekend")
    assert f.sent == []                                         # 858 is above the typical low of 390


def test_cheap_confirmed_wish_city_sends_one_alert_with_app_link():
    st, f = fresh(), Fakes(lowest=350)
    run(date(2026, 10, 17), f, st)
    assert 1 <= len(f.sent) <= 2
    title, msg, data, link = f.sent[0]
    assert "Flybye" in title and data == {"window_id": data["window_id"], "code": data["code"], "space": "s1"}
    assert link == f"https://app.test/Flybye/#trip={data['window_id']}%7C{data['code']}&space=s1"
    assert len(st.alerts()) == len(f.sent)


def test_sunday_sends_summary_and_new_labels():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    title, msg, _, link = f.sent[-1]
    assert title.startswith("Flybye: this week") and "1 new calendar event" in msg and link == "https://app.test/Flybye/#space=s1"
    run(date(2026, 10, 25), f, st)
    assert "new calendar event" not in f.sent[-1][1]            # labels only counted once


def test_backup_cron_skips_a_space_that_already_ran_today(monkeypatch):
    st, f = fresh(), Fakes()
    monkeypatch.setenv("FLYBYE_BACKUP", "1")
    st.set_activity({"last_run": "2026-10-18T07:20:00-05:00"})
    main.command(st, "daily", date(2026, 10, 18), fetch=f.fetch, chat=f.chat, wget=f.wget, get=f.get, send=f.send)
    assert f.params == [] and f.sent == []
    main.command(st, "daily", date(2026, 10, 19), fetch=f.fetch, chat=f.chat, wget=f.wget, get=f.get, send=f.send)
    assert f.params  # the next day it runs


def test_flexible_longer_trips_kept_when_free_searched_weekly_and_still_shown_next_day():
    import copy
    st, f = fresh(), Fakes()
    d = f.explore["destinations"][0]
    f.flex = {"destinations": [{**copy.deepcopy(d), "start_date": s, "end_date": e, "destination_airport": {"code": c}}
                               for c, s, e in [("MIA", "2026-12-04", "2026-12-14"),   # Fri -> Mon, free: kept
                                               ("DEN", "2026-11-14", "2026-11-21"),   # the offsite blocks Nov 13-16
                                               ("LAX", "2026-10-20", "2026-10-27")]]}  # sooner than 3 weeks out
    run(date(2026, 10, 17), f, st)
    flex = [p for p in f.params if p["engine"] == "google_travel_explore" and "outbound_date" not in p]
    assert len(flex) == 3 and all(p["travel_duration"] == 2 for p in flex)   # one per area
    ids = {w["id"]: w for w in st.fs.data["spaces/s1/suggestions/current"]["windows"]}
    assert "long:2026-11-14:2026-11-21" not in ids and "long:2026-10-20:2026-10-27" not in ids
    mia = ids["long:2026-12-04:2026-12-14"]["picks"]
    assert [p["code"] for p in mia] == ["MIA"] and mia[0]["flex"] is True
    f.params.clear()
    run(date(2026, 10, 18), f, st)
    assert not [p for p in f.params if "outbound_date" not in p and p["engine"] == "google_travel_explore"]  # weekly
    assert "long:2026-12-04:2026-12-14" in {w["id"] for w in st.fs.data["spaces/s1/suggestions/current"]["windows"]}


def test_google_typical_range_becomes_the_usual_price_for_that_city_type_and_month():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)
    t = st.fs.docs("spaces/s1/typical")
    assert 0 < len(t) <= CFG["search"]["typical_per_run"]
    tid, doc = sorted(t.items())[0]
    assert doc == {"low": 390, "high": 740, "at": "2026-10-17"}               # flights.json's typical_price_range
    code, kind, month = tid.split("_")
    base = main.baselines(st, [{"code": code, "kind": kind, "out": month + "-15"}], "9999", CFG)
    assert base[(code, kind, month)] == 565                                   # the middle of the range
    f.params.clear()
    run(date(2026, 10, 18), f, st)
    assert len(st.fs.docs("spaces/s1/typical")) > len(t)                      # the next ones, not the same again


def test_watch_pushes_when_the_price_moves_and_drops_past_trips():
    st, f = fresh(), Fakes()                                    # every search answers $858 total = $429 each
    W = "weekend:2026-11-06:2026-11-08"
    st._set("watches", f"{W}|DEN", {"window_id": W, "code": "DEN", "name": "Denver", "by": "a@b.c", "at": "1", "price": 500})
    st._set("watches", "weekend:2026-10-02:2026-10-04|DEN", {"window_id": "weekend:2026-10-02:2026-10-04", "code": "DEN", "name": "Denver", "by": "a@b.c", "at": "0", "price": 500})
    main.watches(CFG, st, date(2026, 10, 17), lambda p: f.get(p, "k"), f.send)
    assert list(st.fs.docs("spaces/s1/watches")) == [f"{W}|DEN"] and len(f.params) == 1
    assert f.sent[0][:3] == ("Flybye watch: Denver", "Down to $429 per person (was $500).", {"window_id": W, "code": "DEN", "space": "s1"})
    assert st.watches()[0][1]["last"] == 429 and st.watches()[0][1]["low"] == 429
    main.watches(CFG, st, date(2026, 10, 18), lambda p: f.get(p, "k"), f.send)
    assert len(f.sent) == 1                                     # unchanged price: quiet


def test_every_daily_run_writes_the_suggestions_doc():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)                              # a Saturday: no summary, still published
    doc = st.fs.data["spaces/s1/suggestions/current"]
    assert set(doc) == {"updated", "windows", "top"} and doc["windows"] and 1 <= len(doc["top"]) <= 4
    ids = {w["id"] for w in doc["windows"]}
    assert "weekend:2026-11-13:2026-11-15" not in ids           # the offsite blocks it
    assert all(t["window_id"] in ids for t in doc["top"])
    assert all(len(w["picks"]) <= 8 for w in doc["windows"])


def test_monthly_cap_stops_searches():
    st, f = fresh(), Fakes()
    st._set("meta", "budget", {"month": "2026-10", "used": CFG["search"]["cap"], "last": {}})
    run(date(2026, 10, 17), f, st)
    assert f.params == []


def test_budget_used_starts_over_in_a_new_month():
    st, f = fresh(), Fakes()
    st._set("meta", "budget", {"month": "2026-09", "used": CFG["search"]["cap"], "last": {}})
    run(date(2026, 10, 17), f, st)
    assert f.params and st.budget("2026-10")["used"] == len(f.params)


def test_settings_are_seeded_from_config_then_the_app_wins():
    st = fresh()
    cfg = main.load_cfg(st)
    assert cfg["cities"] == CFG["cities"] and "ai" in cfg
    saved = st.fs.data["spaces/s1/settings/main"]
    assert "ai" not in saved and "db" not in saved and saved["home"] == "ORD"
    saved["home"] = "MDW"
    assert main.load_cfg(st)["home"] == "MDW"


# --- review fixes ------------------------------------------------------------------------------------------------
def test_confirm_failure_does_not_skip_sunday_summary():
    st, f = fresh(), Fakes(lowest=350)

    def get(p, key):
        if p["engine"] == "google_flights" and "arrival_id" in p and p["arrival_id"] != "OPO":
            raise RuntimeError("SerpApi: timeout")
        return f.get(p, key)
    main.daily(CFG, st, date(2026, 10, 18), fetch=f.fetch, chat=f.chat, get=get, send=f.send, wget=f.wget)
    assert f.sent and f.sent[-1][0].startswith("Flybye: this week")


def test_quota_error_stops_the_sweep_and_tells_us():
    st, f = fresh(), Fakes()

    def get(p, key):
        f.params.append(p)
        return {"error": "Your account has run out of searches."}
    main.daily(CFG, st, date(2026, 10, 17), fetch=f.fetch, chat=f.chat, get=get, send=f.send, wget=f.wget)
    assert len(f.params) == 1
    assert any("out of searches" in m for _, m, _, _ in f.sent)


def test_weekly_cap_checked_before_spending_a_confirm():
    st, f = fresh(), Fakes(lowest=350)
    for d in ("2026-10-12", "2026-10-13"):
        st.add_alert({"at": d, "code": "X", "out": "a", "ret": "b", "price": 1, "kind": "weekend"})
    run(date(2026, 10, 17), f, st, {**CFG, "search": {**CFG["search"], "typical_per_run": 0}})  # typical lookups are google_flights too
    assert not [p for p in f.params if p["engine"] == "google_flights" and p.get("arrival_id") != "OPO"]


def test_summary_sends_label_counts_not_titles():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    msg = f.sent[-1][1]
    assert "Work offsite" not in msg and "1 new calendar event" in msg


def test_summary_ignores_prices_older_than_three_weeks():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 18), f, st)
    for d in st.fs.docs("spaces/s1/latest"):
        st._set("latest", d, {"seen": "2026-09-01", "rows": st._get("latest", d, None)["rows"]})
    f.sent.clear()
    f.explore = {"destinations": []}
    f.flights = {"best_flights": [], "other_flights": [], "price_insights": {}}
    run(date(2026, 10, 25), f, st)
    assert "No priced trips" in f.sent[-1][1]


# --- M2 review fixes ---------------------------------------------------------------------------------------------
def test_app_link_encodes_the_trip_for_fcm(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://x.test/Flybye/")
    assert main.app_link("s1", "weekend:2026-11-13:2026-11-15", "DEN") == "https://x.test/Flybye/#trip=weekend:2026-11-13:2026-11-15%7CDEN&space=s1"
    assert main.app_link("s1") == "https://x.test/Flybye/#space=s1"


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
    st, f = seed(new_store()), Fakes()
    run(date(2026, 10, 17), f, st)
    doc = st._get("suggestions", "current", None)
    assert dt.fromisoformat(doc["updated"]).tzinfo is not None
