"""python -m flybye daily | windows | summary | test-notify   (run from the repo root; reads config.yaml, needs FIREBASE_SA)"""
import os
import sys
import urllib.parse
from datetime import datetime, timedelta

import yaml

from . import ai, cal, pick, push, serp
from . import store as storem
from .windows import TZ, candidates, is_free


def app_link(window_id=None, code=None):
    url = os.environ.get("APP_URL") or None
    return url and (url + "#trip=" + urllib.parse.quote(f"{window_id}|{code}", safe=":") if window_id else url)


def load_cfg(st):
    """Settings live in Firestore (the app edits them); config.yaml seeds them once. The AI list stays in the file."""
    y = yaml.safe_load(open(os.environ.get("FLYBYE_CONFIG", "config.yaml"), encoding="utf-8"))
    return {**st.settings({k: v for k, v in y.items() if k != "ai"}), "ai": y["ai"]}


def free_windows(cfg, st, today, fetch, chat):
    now = datetime.combine(today, datetime.min.time(), TZ)
    last_week = max(c["weeks"][1] for c in cfg["trips"].values())
    events = cal.parse(fetch(os.environ.get("ICAL_URL", "")), now - timedelta(days=1), now + timedelta(weeks=last_week + 2))
    labels = ai.label_events(events, st, cfg, chat)
    blockers = [e for e in events if labels[f"{e.uid}|{e.title}"]]
    return [w for w in candidates(today, cfg["trips"]) if is_free(w, blockers)]


def month(today):
    return f"{today:%Y-%m}"


def baselines(st, codes_kinds, before):
    return {(code, kind): pick.baseline([r for r in st.route_prices(code, kind) if r["seen"] < before])
            for code, kind in codes_kinds}


def sweep(cfg, st, today, windows, get, send):
    b = st.budget(month(today))
    budget = pick.allowance(cfg["search"]["cap"], b["used"], today)
    rows = []
    calls = []
    for w in pick.choose(windows, b["last"], budget, cfg):
        calls += [lambda w=w, a=a: serp.explore(w, a, cfg, st, get)
                  for a in (cfg["search"]["long_areas"] if w.kind == "long" else [None])]
        calls += [lambda w=w, c=c: [r for r in [serp.flights(w, c["airports"], c["stops"], c["name"], cfg, st, get)] if r]
                  for c in pick.own_stops_cities(w.kind, cfg)]
    for call in calls:
        try:
            rows += call()
        except serp.Fatal as e:
            send("Flybye stopped searching", f"SerpApi says: {e}")
            break
        except Exception as e:  # one bad search (timeout, odd answer) shouldn't lose the rest
            print(f"search failed: {e}", file=sys.stderr)
    cheapest = {}
    for r in rows:  # Explore can list one airport twice (Miami and Fort Lauderdale are both FLL)
        k = (r["window_id"], r["code"])
        if k not in cheapest or r["price"] < cheapest[k]["price"]:
            cheapest[k] = r
    rows = list(cheapest.values())
    st.add_prices(rows, str(today))
    return rows


def instant_alerts(cfg, st, today, rows, get, send):
    base = baselines(st, {(r["code"], r["kind"]) for r in rows}, str(today))
    sent = st.alerts()
    week_ago = (today - timedelta(days=7)).isoformat()
    # confirms are logged as "<window>|<code>"
    recent = {k for k, at in st.budget(month(today))["last"].items() if "|" in k and at >= week_ago}
    for r in pick.deal_candidates(rows, base, cfg, recent):
        if st.budget(month(today))["used"] >= cfg["search"]["cap"] or pick.week_full(sent, today, cfg):
            return
        try:
            c = serp.confirm(r, cfg, st, get)
        except Exception as e:
            print(f"confirm failed for {r['code']} {r['window_id']}: {e}", file=sys.stderr)
            continue
        if pick.should_alert(r, c, sent, today, cfg):
            r = {**r, "price": c["lowest"] or r["price"]}
            msg = (pick.fmt_row(r, base.get((r["code"], r["kind"])), cfg)
                   + f"\nGoogle's usual: ${c['typical_low']}–${c['typical_high']} for this trip. You're both free.")
            send("Flybye deal: " + pick.city_for(r["code"], cfg)["name"], msg,
                 {"window_id": r["window_id"], "code": r["code"]}, app_link(r["window_id"], r["code"]))
            a = {"at": str(today), "code": r["code"], "out": r["out"], "ret": r["ret"], "price": r["price"], "kind": r["kind"]}
            st.add_alert(a)
            sent.append(a)


def latest(cfg, st, today, windows):
    """The newest prices (21 days at most) of the windows that are still free, and their usual prices."""
    ids = {w.id: w for w in windows}
    rows = st.latest_rows(list(ids), (today - timedelta(days=21)).isoformat())
    return rows, ids, baselines(st, {(r["code"], r["kind"]) for r in rows}, "9999")


def publish(cfg, st, today, windows):
    rows, ids, base = latest(cfg, st, today, windows)
    st.write_suggestions(pick.suggestions(rows, base, ids, cfg, datetime.now(TZ).isoformat(timespec="seconds")))


def summary(cfg, st, today, windows, send):
    rows, ids, base = latest(cfg, st, today, windows)
    labels = [{**l, "block": storem.blocks(l)} for l in st.labels_since(st.summary_last())]
    send(*pick.summary(rows, base, ids, cfg, labels), None, app_link())
    st.set_summary_last(datetime.now(TZ).isoformat(timespec="seconds"))


def windows_report(windows, labels, cfg, ci):
    """The repo is public, so in Actions logs only counts: no event titles, no away dates."""
    blocking = sum(storem.blocks(l) for l in labels)
    if ci:
        return [f"{len(windows)} free window{'s' if len(windows) != 1 else ''}, "
                f"{len(labels)} calendar event{'s' if len(labels) != 1 else ''} labelled ({blocking} block trips)"]
    return ([f"{w.id} {w.holiday or ''} cost {pick.cost(w, cfg)}" for w in windows]
            + [("BLOCK " if storem.blocks(l) else "ok    ") + f"{l['title']} - {l['why']}" for l in labels])


def daily(cfg, st, today, fetch=cal.fetch, chat=ai.http_chat, get=serp.http_get, send=None):
    send = send or (lambda *a: push.send(st, *a))
    windows = free_windows(cfg, st, today, fetch, chat)
    rows = sweep(cfg, st, today, windows, get, send)
    try:
        instant_alerts(cfg, st, today, rows, get, send)
    except Exception as e:  # never let an alert problem cost us the Sunday summary
        print(f"alerts failed: {e}", file=sys.stderr)
    publish(cfg, st, today, windows)
    if today.weekday() == 6:
        summary(cfg, st, today, windows, send)


def main(argv):
    st = storem.connect()
    cfg, today = load_cfg(st), datetime.now(TZ).date()
    cmd = argv[0] if argv else "daily"
    if cmd == "daily":
        daily(cfg, st, today)
    elif cmd == "windows":
        ws = free_windows(cfg, st, today, cal.fetch, ai.http_chat)
        print("\n".join(windows_report(ws, list(reversed(st.labels_since(""))), cfg, bool(os.environ.get("GITHUB_ACTIONS")))))
    elif cmd == "summary":
        summary(cfg, st, today, free_windows(cfg, st, today, cal.fetch, ai.http_chat), lambda *a: push.send(st, *a))
    elif cmd == "test-notify":
        push.send(st, "Flybye test", "If you see this, Flybye can reach your phone.", None, app_link())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
