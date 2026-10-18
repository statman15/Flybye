import json

import pytest
import pathlib
from datetime import date, datetime

from fakefs import new_store
from flybye import pick, serp
from flybye.windows import Window

FIX = pathlib.Path(__file__).parent / "fixtures"
CFG = {
    "search": {"cap": 230, "adults": 2, "stops": 1, "long_areas": [None, "/m/02j9z", "/m/0j0k"], "confirm_per_run": 2},
    "alerts": {"deal_ratio": 0.8, "max_instant_per_week": 2, "repeat_drop": 0.9},
    "score": {"hour_penalty": 2, "wish_bonus": 10, "holiday_bonus": 5, "weather_bonus": 10, "airline_bonus": 8},
    "airlines": {"prefer": ["UA"], "avoid": ["F9"]},
    "weather": {"min_f": 65, "max_f": 85},
    "cities": [{"name": "Denver", "airports": ["DEN"], "trips": ["weekend", "3day", "long"]},
               {"name": "Miami", "airports": ["MIA", "FLL"], "trips": ["weekend", "3day", "long"]},
               {"name": "Porto", "airports": ["OPO"], "trips": ["long"], "stops": 2}],
}
WE = Window("weekend", date(2026, 11, 13), date(2026, 11, 15), None)
LONG = Window("long", date(2027, 1, 16), date(2027, 1, 23), None)


def row(code="DEN", price=400, window=WE, name="Denver", minutes=176, **extra):
    return {"window_id": window.id, "kind": window.kind, "out": str(window.out), "ret": str(window.ret), "code": code,
            "name": name, "price": price, "hotel": 150, "minutes": minutes, "airline": "United", "airline_code": "UA",
            "lat": 39.8, "lon": -104.7, "stops": 0, "source": "explore", **extra}


# --- budget ---------------------------------------------------------------------------------------------------
def test_allowance_spreads_what_is_left_over_the_days_left():
    assert pick.allowance(230, 0, date(2026, 10, 17)) == 15     # 230 // 15 days (17th..31st)
    assert pick.allowance(230, 230, date(2026, 10, 17)) == 0
    assert pick.allowance(230, 250, date(2026, 10, 31)) == 0


def test_cost_long_window_counts_areas_and_own_stops_cities():
    assert pick.cost(WE, CFG) == 1
    assert pick.cost(LONG, CFG) == 4  # 3 areas + Porto


def test_choose_never_searched_first_then_oldest_then_nearest():
    a = Window("weekend", date(2026, 11, 6), date(2026, 11, 8), None)
    b = Window("weekend", date(2026, 11, 13), date(2026, 11, 15), None)
    c = Window("weekend", date(2026, 11, 20), date(2026, 11, 22), None)
    last = {a.id: "2026-10-10", b.id: "2026-10-03"}
    assert pick.choose([a, b, c], last, 2, CFG) == [c, b]


def test_choose_skips_what_does_not_fit_and_takes_cheaper_ones():
    assert pick.choose([LONG, WE], {}, 2, CFG) == [WE]


# --- baseline, deals, alerts -------------------------------------------------------------------------------------
def test_baseline_needs_four_prices_from_two_windows():
    w2 = Window("weekend", date(2026, 11, 20), date(2026, 11, 22), None)
    assert pick.baseline([row(price=p) for p in (300, 400, 500, 600)]) is None
    assert pick.baseline([row(price=300), row(price=400), row(price=500, window=w2), row(price=900, window=w2)]) == 450


def test_deal_candidates_only_wish_cities_cheap_or_unknown_sorted_capped():
    rows = [row("DEN", 300), row("FLL", 200, name="Miami"), row("BNA", 100, name="Nashville"), row("OPO", 900)]
    base = {("DEN", "weekend"): 500, ("FLL", "weekend"): 210}
    got = pick.deal_candidates(rows, base, CFG)
    assert [r["code"] for r in got] == ["DEN", "OPO"]  # FLL 0.95 not a deal; BNA not on the list; unknown last


def test_should_alert_needs_price_at_or_below_typical_low():
    c = {"lowest": 380, "typical_low": 390}
    assert pick.should_alert(row(price=400), c, [], date(2026, 10, 17), CFG)
    assert not pick.should_alert(row(price=400), {"lowest": 395, "typical_low": 390}, [], date(2026, 10, 17), CFG)


def test_should_alert_weekly_cap():
    c = {"lowest": 300, "typical_low": 390}
    sent = [{"at": "2026-10-12", "code": "X", "out": "a", "ret": "b", "price": 1},
            {"at": "2026-10-14", "code": "Y", "out": "a", "ret": "b", "price": 1}]
    assert not pick.should_alert(row(), c, sent, date(2026, 10, 17), CFG)   # same ISO week (Mon 12th..)
    assert pick.should_alert(row(), c, sent, date(2026, 10, 19), CFG)       # next week


def test_should_alert_repeat_needs_ten_percent_drop():
    sent = [{"at": "2026-10-01", "code": "DEN", "out": "2026-11-13", "ret": "2026-11-15", "price": 340}]
    assert not pick.should_alert(row(), {"lowest": 320, "typical_low": 390}, sent, date(2026, 10, 17), CFG)
    assert pick.should_alert(row(), {"lowest": 300, "typical_low": 390}, sent, date(2026, 10, 17), CFG)


# --- score and text ----------------------------------------------------------------------------------------------
def test_score_prefers_cheaper_shorter_wish_and_holiday():
    hol = Window("3day", date(2026, 11, 26), date(2026, 11, 29), "Thanksgiving")
    s = pick.score(row(price=400), 500, WE, CFG) - 8                 # minus the preferred-airline bonus
    assert s == pytest.approx(20 - 2 * 176 / 60 + 10)
    assert pick.score(row(code="BNA", price=400), 500, WE, CFG) - 8 == pytest.approx(s - 10)
    assert pick.score(row(price=400), 500, hol, CFG) == s + 5 + 8
    assert pick.score(row(price=400), None, WE, CFG) == pytest.approx(s - 20 + 8)


def wx(hi, rain=0):
    return {"kind": "forecast", "hi_f": hi, "lo_f": hi - 15, "rain_pct": rain}


def test_score_parts_sum_to_the_total():
    p = pick.parts(row(price=400, weather=wx(75, 20)), 500, WE, CFG)
    assert p["total"] == pytest.approx(p["under_pct"] + p["hours"] + p["wish"] + p["holiday"] + p["weather"] + p["airline"])
    assert p["hours"] == pytest.approx(-2 * 176 / 60) and p["airline"] == 8


def test_weather_inside_range_is_a_bonus_and_rain_costs():
    assert pick.parts(row(weather=wx(70)), None, WE, CFG)["weather"] == 10
    assert pick.parts(row(weather=wx(70, 30)), None, WE, CFG)["weather"] == 7
    assert pick.parts(row(weather=wx(85)), None, WE, CFG)["weather"] == 10      # edges count as inside


def test_weather_outside_range_loses_a_point_per_degree_capped_at_twenty():
    assert pick.parts(row(weather=wx(60)), None, WE, CFG)["weather"] == -5
    assert pick.parts(row(weather=wx(90, 50)), None, WE, CFG)["weather"] == -10
    assert pick.parts(row(weather=wx(20)), None, WE, CFG)["weather"] == -20


def test_no_weather_means_no_weather_points():
    assert pick.parts(row(), None, WE, CFG)["weather"] == 0


def test_avoided_airlines_are_dropped_and_preferred_ranked_higher():
    rows = [row("DEN", 400, name="Denver"), {**row("BNA", 400, name="Nashville"), "airline_code": "F9"},
            {**row("ATL", 400, name="Atlanta"), "airline_code": "DL"}]
    assert [r["code"] for r in pick.keep(rows, CFG)] == ["DEN", "ATL"]
    assert pick.score(rows[0], None, WE, CFG) - pick.score(rows[2], None, WE, CFG) == 8 + 10   # prefer + wish


def test_fmt_row():
    t = pick.fmt_row(row(price=410), 533, CFG)
    assert t == "Denver · Fri Nov 13–Sun Nov 15 · $410 for 2 (23% under usual) · 2h56 nonstop · hotel ~$150"


def test_summary_top_three_wish_plus_one_surprise():
    w2 = Window("weekend", date(2026, 11, 20), date(2026, 11, 22), None)
    rows = [row("DEN", 300), row("DEN", 350, window=w2), row("FLL", 250, name="Miami"),
            row("BNA", 100, name="Nashville"), row("ATL", 120, name="Atlanta")]
    title, text = pick.summary(rows, {}, {WE.id: WE, w2.id: w2}, CFG, [{"title": "Dentist", "block": 1, "why": "appt"}])
    lines = text.splitlines()
    assert title.startswith("Flybye")
    assert sum(l.startswith(("Denver", "Miami")) for l in lines) == 3
    assert any(l.startswith("Surprise: Nashville") for l in lines)
    assert "1 new calendar event checked, 1 block trips" in text and "Dentist" not in text


def test_suggestions_doc_shape():
    w2 = Window("weekend", date(2026, 11, 20), date(2026, 11, 22), "Veterans Day")
    rows = [row("DEN", 300), row("DEN", 350, window=w2), row("FLL", 250, name="Miami"),
            row("BNA", 100, name="Nashville"), row("ATL", 120, name="Atlanta")]
    doc = pick.suggestions(rows, {("DEN", "weekend"): 500}, {WE.id: WE, w2.id: w2}, CFG, "2026-10-17T08:00:00")
    assert doc["updated"] == "2026-10-17T08:00:00"
    assert [w["id"] for w in doc["windows"]] == [WE.id, w2.id]            # soonest first
    first = doc["windows"][0]
    assert set(first) == {"id", "kind", "out", "ret", "holiday", "picks"} and doc["windows"][1]["holiday"] == "Veterans Day"
    assert [p["code"] for p in first["picks"]][:2] == ["DEN", "FLL"]      # best first: wish cities lead
    p = next(p for p in first["picks"] if p["code"] == "DEN")
    assert set(p) == {"code", "name", "price", "usual", "minutes", "stops", "hotel", "airline", "airline_code", "wish",
                      "link", "weather", "score"}
    assert p["weather"] is None and p["airline_code"] == "UA"
    assert set(p["score"]) == {"total", "under_pct", "hours", "wish", "holiday", "weather", "airline"}
    assert p["score"]["airline"] == 8 and p["score"]["wish"] == 10 and p["score"]["under_pct"] == 40.0
    assert p["usual"] == 500 and p["wish"] is True and p["name"] == "Denver"
    assert p["link"].startswith("https://www.google.com/travel/flights?q=") and "DEN" in p["link"]
    assert next(p for p in first["picks"] if p["code"] == "BNA")["usual"] is None
    assert [(t["code"], t["window_id"]) for t in doc["top"]][-1] == ("BNA", WE.id)   # 3 wish picks + the surprise
    assert len(doc["top"]) == 4 and sum(t["wish"] for t in doc["top"]) == 3


def test_suggestions_keep_at_most_eight_picks_per_window():
    rows = [row(f"X{i:02d}", 100 + i, name=f"City{i}") for i in range(12)]
    doc = pick.suggestions(rows, {}, {WE.id: WE}, CFG, "t")
    assert len(doc["windows"][0]["picks"]) == 8 and doc["top"][0]["price"] == 100 and len(doc["top"]) == 1


# --- serp parsing (real response shapes from the 2026-10-17 spike) -------------------------------------------------
def fake_get(name):
    data = json.loads((FIX / name).read_text())
    calls = []

    def get(params):
        calls.append(params)
        return data
    return get, calls


def test_explore_rows_and_search_logged():
    st = new_store()
    get, calls = fake_get("explore.json")
    rows = serp.explore(WE, None, CFG, st, get)
    assert {r["code"] for r in rows} == {"FLL", "DEN", "BNA"} and len(rows) == 4  # unpriced Victoria dropped
    den = next(r for r in rows if r["code"] == "DEN")
    assert den["price"] == 410 and den["window_id"] == WE.id and den["stops"] == 0
    p = calls[0]
    assert den["airline_code"] == "F9"
    assert p["engine"] == "google_travel_explore" and p["outbound_date"] == "2026-11-13" and p["stops"] == 1
    assert "arrival_area_id" not in p
    assert st.budget(f"{datetime.now():%Y-%m}")["used"] == 1


def test_flights_cheapest_itinerary_and_confirm():
    st = new_store()
    get, calls = fake_get("flights.json")
    r = serp.flights(LONG, ["OPO"], 2, "Porto", CFG, st, get)
    assert r["price"] == 858 and r["code"] == "OPO" and r["source"] == "flights" and calls[0]["stops"] == 2
    c = serp.confirm(row("BNA", 858), CFG, st, get)
    assert c["lowest"] == 858 and c["typical_low"] == 390 and c["typical_high"] == 740
    assert calls[1]["arrival_id"] == "BNA" and calls[1]["stops"] == 1


def test_confirm_uses_the_city_stops_rule():
    st = new_store()
    get, calls = fake_get("flights.json")
    serp.confirm(row("OPO", 900, window=LONG), CFG, st, get)
    assert calls[0]["stops"] == 2


def test_no_results_error_means_empty_not_failure():
    st = new_store()
    rows = serp.explore(LONG, "/m/02j9z", CFG, st, lambda p: {"error": "Google Travel Explore hasn't returned any results for this query."})
    assert rows == []


def test_quota_error_is_fatal():
    st = new_store()
    with pytest.raises(serp.Fatal):
        serp.explore(WE, None, CFG, st, lambda p: {"error": "Invalid API key. Your API key should be here"})


def test_unknown_baselines_cheapest_first_and_recently_confirmed_skipped():
    rows = [row("DEN", 500), row("FLL", 300, name="Miami"), row("DEN", 200, window=LONG)]
    got = pick.deal_candidates(rows, {}, CFG, recent={f"{LONG.id}|DEN"})
    assert [(r["code"], r["price"]) for r in got] == [("FLL", 300), ("DEN", 500)]


def test_empty_results_wording_also_means_empty():
    db = new_store()
    assert serp.explore(LONG, None, CFG, db, lambda p: {"error": 'Empty results for departure_id: "ORD".'}) == []


def test_explore_rows_carry_coordinates_when_google_gives_them():
    st = new_store()
    data = json.loads((FIX / "explore.json").read_text())
    data["destinations"][1]["gps_coordinates"] = {"latitude": 39.74, "longitude": -104.99}
    rows = serp.explore(WE, None, CFG, st, lambda p: data)
    den = next(r for r in rows if r["code"] == "DEN")
    assert (den["lat"], den["lon"]) == (39.74, -104.99)
    assert next(r for r in rows if r["code"] == "BNA")["lat"] is None


def test_flights_row_gets_the_airline_code_from_the_flight_number():
    st = new_store()
    get, _ = fake_get("flights.json")
    assert serp.flights(LONG, ["OPO"], 2, "Porto", CFG, st, get)["airline_code"] == "UA"
