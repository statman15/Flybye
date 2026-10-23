"""M3: spaces, calendars, keys, airlines, weather, activity. Fakes and helpers come from test_main."""
from datetime import date, datetime, timezone

from fakefs import FakeFS, new_store
from flybye import __main__ as main
from test_main import CFG, ICS, ICS_B, KEYS, Fakes, env, fresh, run, seed  # noqa: F401  (env is an autouse fixture)


def test_old_spaces_get_the_new_settings_defaults():
    st = fresh()
    st._set("settings", "main", {**{k: v for k, v in CFG.items() if k not in ("ai", "airlines", "weather")},
                                 "score": {"hour_penalty": 3}})
    cfg = main.load_cfg(st)
    assert cfg["airlines"] == {"prefer": [], "avoid": []} and cfg["weather"] == {"min_f": 65, "max_f": 85}
    assert cfg["score"]["hour_penalty"] == 3 and cfg["score"]["weather_bonus"] == 10 and cfg["score"]["airline_bonus"] == 8


def test_the_space_keys_are_used_not_environment_variables(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "env-serp")
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)
    assert set(f.serp_keys) == {"sk"} and set(f.chat_keys) == {"gk"}


def test_a_trip_needs_every_calendar_free():
    st, f = fresh(calendars=[{"name": "A", "url": "https://cal.test/a"}, {"name": "B", "url": "https://cal.test/b"}]), Fakes()
    f.cals = {"https://cal.test/a": ICS, "https://cal.test/b": ICS_B}
    run(date(2026, 10, 17), f, st)
    assert f.fetched.count("https://cal.test/a") == 1 and f.fetched.count("https://cal.test/b") == 1
    searched = {p["outbound_date"] for p in f.params if "outbound_date" in p}
    assert "2026-11-13" not in searched and "2026-11-20" not in searched      # one blocked by A, one by B
    assert "2026-11-06" in searched or "2026-11-27" in searched
    assert st.activity()["labelled"] == 2 and st.activity()["blocking"] == 2


def test_two_spaces_are_isolated_and_a_broken_one_does_not_stop_the_other():
    fs, f = FakeFS(), Fakes()
    for sid in ("a", "b"):
        fs.collection("spaces").document(sid).set({"name": sid})
        seed(new_store(sid, fs), calendars=[{"name": "x", "url": f"https://cal.test/{sid}"}], serpapi=f"key-{sid}")

    def fetch(url):
        if url.endswith("/a"):
            raise OSError("calendar down")
        return f.fetch(url)
    main.run_all(fs, "daily", date(2026, 10, 17), fetch=fetch, chat=f.chat, get=f.get, send=f.send, wget=f.wget)
    a, b = new_store("a", fs), new_store("b", fs)
    assert any("Run failed" in e for e in a.activity()["errors"]) and a.budget("2026-10")["used"] == 0
    assert b.activity()["errors"] == [] and b.budget("2026-10")["used"] > 0 and b.labels_get(["w@x|Work offsite"])
    assert a.labels_get(["w@x|Work offsite"]) == {} and set(f.serp_keys) == {"key-b"}
    assert not any(p.startswith("spaces/a/latest") for p in fs.data)


def test_avoided_airlines_are_never_shown_and_preferred_ones_get_the_bonus():
    st, f = fresh(), Fakes()
    cfg = {**CFG, "airlines": {"prefer": ["AA"], "avoid": ["F9"]}}
    run(date(2026, 10, 17), f, st, cfg)
    stored = [r for d in st.fs.docs("spaces/s1/latest").values() for r in d["rows"]]
    assert any(r["airline_code"] == "F9" for r in stored)   # stored, so keep() can learn the name "Frontier"
    picks = [p for w in st.fs.data["spaces/s1/suggestions/current"]["windows"] for p in w["picks"]]
    assert picks and all(p["code"] != "DEN" for p in picks)
    assert all((p["score"]["airline"] == 8) == (p["airline_code"] == "AA") for p in picks)


def test_an_avoid_list_edited_later_hides_already_stored_rows():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)
    assert any(p["code"] == "DEN" for w in st.fs.data["spaces/s1/suggestions/current"]["windows"] for p in w["picks"])
    cfg = {**CFG, "airlines": {"prefer": [], "avoid": ["F9"]}}
    windows, *_ = main.free_windows(cfg, st, date(2026, 10, 17), f.fetch, lambda p, m: f.chat(p, m, "k"))
    doc = main.publish(cfg, st, date(2026, 10, 17), windows, None)
    assert doc["windows"] and not any(p["code"] == "DEN" for w in doc["windows"] for p in w["picks"])


def test_weather_is_on_every_pick_and_moves_its_score():
    st, f = fresh(), Fakes()
    for x in f.explore["destinations"]:
        x["gps_coordinates"] = {"latitude": 30.0, "longitude": -90.0}
    run(date(2026, 10, 17), f, st, {**CFG, "trips": {"weekend": {"enabled": True, "weeks": [0, 10]}}})
    wins = st.fs.data["spaces/s1/suggestions/current"]["windows"]
    near = next(p for w in wins if w["out"] <= "2026-11-01" for p in w["picks"])
    far = next(p for w in wins if w["out"] > "2026-12-01" for p in w["picks"])
    assert near["weather"] == {"kind": "forecast", "hi_f": 75, "lo_f": 55, "rain_pct": 20}
    assert near["score"]["weather"] == 8.0                     # 75F is inside 65-85: +10, minus 20% rain / 10
    assert far["weather"] == {"kind": "typical", "hi_f": 95, "lo_f": 75, "rain_pct": 0}
    assert far["score"]["weather"] == -10.0                    # 10F too hot
    assert st.climate("FLL", "12")["hi_f"] == 95               # cached for next time


def test_weather_failing_leaves_the_run_intact_with_no_weather():
    st, f = fresh(), Fakes()
    for x in f.explore["destinations"]:
        x["gps_coordinates"] = {"latitude": 30.0, "longitude": -90.0}

    def down(url):
        raise OSError("down")
    main.daily(CFG, st, date(2026, 10, 17), fetch=f.fetch, chat=f.chat, get=f.get, send=f.send, wget=down)
    picks = [p for w in st.fs.data["spaces/s1/suggestions/current"]["windows"] for p in w["picks"]]
    assert picks and all(p["weather"] is None and p["score"]["weather"] == 0 for p in picks)
    assert st.activity()["errors"] == []


def test_the_activity_doc_shape():
    st, f = fresh(), Fakes()
    run(date(2026, 10, 17), f, st)
    a = st.activity()
    assert set(a) == {"last_run", "next_run", "month", "used", "cap", "windows", "labelled", "blocking", "errors"}
    assert a["month"] == "2026-10" and a["cap"] == 230 and a["used"] == st.budget("2026-10")["used"] > 0
    assert a["labelled"] == 1 and a["blocking"] == 1 and a["errors"] == []
    assert datetime.fromisoformat(a["last_run"]).tzinfo and datetime.fromisoformat(a["next_run"]) > datetime.fromisoformat(a["last_run"])
    assert set(a["windows"][0]) == {"id", "searched_at", "picks"}
    searched = [w for w in a["windows"] if w["searched_at"]]
    assert searched and all(w["picks"] > 0 for w in searched) and "weekend:2026-11-13:2026-11-15" not in {w["id"] for w in a["windows"]}


def test_next_run_is_the_next_0650_chicago():
    assert main.next_run(datetime(2026, 10, 17, 6, tzinfo=main.TZ)) == "2026-10-17T06:50:00-05:00"
    assert main.next_run(datetime(2026, 10, 17, 9, tzinfo=main.TZ)) == "2026-10-18T06:50:00-05:00"
    assert main.next_run(datetime(2026, 11, 2, 7, tzinfo=main.TZ)) == "2026-11-03T06:50:00-06:00"   # winter time


def test_activity_keeps_the_newest_twenty_errors():
    st, f = fresh(serpapi=""), Fakes()
    st.set_activity({"errors": [f"old {i}" for i in range(25)]})
    run(date(2026, 10, 17), f, st)
    e = st.activity()["errors"]
    assert len(e) == 20 and "Add a SerpApi key in Settings" in e[0] and e[1] == "old 0"


def test_a_space_without_a_serpapi_key_gets_windows_and_labels_but_no_search():
    st, f = fresh(serpapi=None), Fakes()
    run(date(2026, 10, 17), f, st)
    assert f.params == [] and st.budget("2026-10")["used"] == 0
    assert st.labels_get(["w@x|Work offsite"]) and st.activity()["windows"]
    assert any("Add a SerpApi key in Settings" in e for e in st.activity()["errors"])
    assert st._get("suggestions", "current", None) is not None


def test_a_space_without_calendars_searches_nothing():
    st, f = fresh(calendars=[]), Fakes()
    run(date(2026, 10, 17), f, st)
    assert f.params == [] and f.fetched == []
    assert any("Add a calendar in Settings" in e for e in st.activity()["errors"])


def test_ci_log_is_per_space_counts_only(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    fs, f = FakeFS(), Fakes()
    fs.collection("spaces").document("abc123").set({"name": "Secret Name", "owner": "someone@example.com"})
    seed(new_store("abc123", fs))
    main.run_all(fs, "windows", date(2026, 10, 17), fetch=f.fetch, chat=f.chat)
    out = capsys.readouterr().out
    assert out.startswith("space abc123: ") and "free window" in out and "event" in out
    assert "Secret Name" not in out and "someone@example.com" not in out and "Work offsite" not in out and "2026-11" not in out


def test_explore_rows_carry_real_gps_coordinates():
    from flybye import serp
    from flybye.windows import Window
    import json, pathlib
    data = json.loads((pathlib.Path(__file__).parent / "fixtures" / "explore.json").read_text())
    w = Window("weekend", date(2026, 11, 13), date(2026, 11, 15), None)
    rows = serp.explore(w, None, CFG, fresh(), lambda p: data)
    den = next(r for r in rows if r["code"] == "DEN")
    assert abs(den["lat"] - 39.7) < 0.5 and abs(den["lon"] + 105.0) < 0.5


def test_a_new_space_without_calendars_still_gets_default_settings():
    fs = FakeFS()
    fs.collection("spaces").document("new").set({"name": "new", "owner": "o@x.test", "members": ["o@x.test"]})
    main.run_all(fs, "daily", date(2026, 10, 17))
    st = new_store("new", fs)
    s = st._get("settings", "main", None)
    assert s and s["weather"] == {"min_f": 65, "max_f": 85} and s["airlines"] == {"prefer": [], "avoid": []}
    assert "Add a calendar in Settings" in " ".join(st.activity()["errors"])
