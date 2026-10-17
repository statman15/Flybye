from datetime import datetime

from fakefs import FakeFS
from flybye.store import Store, blocks


def make(now=datetime(2026, 10, 17, 8)):
    fs = FakeFS()
    return Store(fs, now=lambda: now), fs


def test_settings_seeded_once_then_read_back():
    st, fs = make()
    assert st.settings({"home": "ORD"}) == {"home": "ORD"}
    fs.data["settings"]["main"]["home"] = "MDW"          # the app edited it
    assert st.settings({"home": "ORD"}) == {"home": "MDW"}


def test_override_beats_the_ai():
    st, _ = make()
    st.labels_put("u|A", {"block": True, "override": None})
    st.labels_put("u|B", {"block": True, "override": False})
    st.labels_put("u|C", {"block": False, "override": True})
    got = st.labels_get(["u|A", "u|B", "u|C", "u|none"])
    assert {k: blocks(v) for k, v in got.items()} == {"u|A": True, "u|B": False, "u|C": True}


def test_labels_put_merges_and_keeps_the_override():
    st, _ = make()
    st.labels_put("u|A", {"block": True, "start": "x", "override": False})
    st.labels_put("u|A", {"start": "y"})
    assert st.labels_get(["u|A"])["u|A"] == {"key": "u|A", "block": True, "start": "y", "override": False}


def test_budget_counts_then_resets_on_a_new_month():
    st, fs = make(datetime(2026, 9, 30))
    st.log_search("w1")
    st.log_search("w2")
    assert st.budget("2026-09")["used"] == 2
    st.now = lambda: datetime(2026, 10, 1)
    assert st.budget("2026-10")["used"] == 0             # reading doesn't need a write
    st.log_search("w1")
    b = st.budget("2026-10")
    assert b["used"] == 1 and set(b["last"]) == {"w1", "w2"}   # last-searched survives the month


def test_prices_keep_newest_60_and_latest_per_window():
    st, _ = make()
    row = lambda w, p: {"window_id": w, "kind": "weekend", "code": "DEN", "price": p}
    for i in range(70):
        st.add_prices([row(f"w{i}", 100 + i)], f"2026-09-{i % 28 + 1:02d}")
    got = st.route_prices("DEN", "weekend")
    assert len(got) == 60 and got[-1]["price"] == 169 and got[0]["price"] == 110
    assert st.latest_rows(["w69", "w0"], "2026-01-01")[0]["price"] == 169
    assert [r["price"] for r in st.latest_rows(["w69"], "2026-12-01")] == []   # too old


def test_alerts_keep_newest_100_and_summary_marker():
    st, _ = make()
    for i in range(105):
        st.add_alert({"at": "2026-10-01", "code": "DEN", "price": i})
    assert len(st.alerts()) == 100 and st.alerts()[0]["price"] == 5
    assert st.summary_last() == ""
    st.set_summary_last("2026-10-18T08:00:00")
    assert st.summary_last() == "2026-10-18T08:00:00"


def test_devices_listed_and_dropped():
    st, fs = make()
    fs.collection("devices").document("tok1").set({"platform": "web"})
    fs.collection("devices").document("tok2").set({"platform": "android"})
    assert sorted(st.device_tokens()) == ["tok1", "tok2"]
    st.drop_token("tok1")
    assert st.device_tokens() == ["tok2"]
