"""python -m flybye daily | windows | summary | test-notify   (run from the repo root; reads config.yaml, needs FIREBASE_SA)"""
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import yaml

from . import ai, cal, pick, push, serp, weather
from . import store as storem
from .windows import TZ, candidates, is_free


def app_link(sid, window_id=None, code=None):
    url = os.environ.get("APP_URL") or None
    if not url:
        return None
    return url + (f"#trip={urllib.parse.quote(f'{window_id}|{code}', safe=':')}&space={sid}" if window_id else f"#space={sid}")


def load_cfg(st):
    """Settings live in Firestore (the app edits them); config.yaml seeds them once and fills in what older spaces lack."""
    y = yaml.safe_load(open(os.environ.get("FLYBYE_CONFIG", "config.yaml"), encoding="utf-8"))
    cfg = st.settings({k: v for k, v in y.items() if k != "ai"})
    return {**cfg, "ai": y["ai"], **{k: {**y[k], **cfg.get(k, {})} for k in ("score", "airlines", "weather")}}


def free_windows(cfg, st, today, fetch, chat):
    """(windows free in every one of the space's calendars, {event key: blocks})."""
    calendars = st.keys().get("calendars", [])
    if not calendars:  # nothing to check against: don't call every date free
        return [], {}
    now = datetime.combine(today, datetime.min.time(), TZ)
    last_week = max(c["weeks"][1] for c in cfg["trips"].values())
    events = [e for c in calendars for e in cal.parse(fetch(c["url"]), now - timedelta(days=1), now + timedelta(weeks=last_week + 2))]
    labels = ai.label_events(events, st, cfg, chat)
    blockers = [e for e in events if labels[f"{e.uid}|{e.title}"]]
    return [w for w in candidates(today, cfg["trips"]) if is_free(w, blockers)], labels


def month(today):
    return f"{today:%Y-%m}"


def baselines(st, codes_kinds, before):
    return {(code, kind): pick.baseline([r for r in st.route_prices(code, kind) if r["seen"] < before])
            for code, kind in codes_kinds}


def sweep(cfg, st, today, windows, get, send, errors):
    b = st.budget(month(today))
    budget = pick.allowance(cfg["search"]["cap"], b["used"], today)
    rows = []
    calls = []
    # a window is re-searched once a week at most
    stale = (today - timedelta(days=cfg["search"].get("refresh_days", 7) - 1)).isoformat()
    for w in pick.choose(windows, b["last"], budget, cfg, stale):
        calls += [lambda w=w, a=a: serp.explore(w, a, cfg, st, get)
                  for a in (cfg["search"]["long_areas"] if w.kind == "long" else [None])]
        calls += [lambda w=w, c=c: [r for r in [serp.flights(w, c["airports"], c["stops"], c["name"], cfg, st, get)] if r]
                  for c in pick.own_stops_cities(w.kind, cfg)]
    failed = 0
    for call in calls:
        try:
            rows += call()
        except serp.Fatal as e:
            send("Flybye stopped searching", f"SerpApi says: {e}")
            errors.append(f"SerpApi stopped the search: {e}")
            break
        except Exception as e:  # one bad search (timeout, odd answer) shouldn't lose the rest
            print(f"search failed: {e}", file=sys.stderr)
            failed += 1
    if failed:
        errors.append(f"{failed} search{'es' if failed != 1 else ''} failed")
    cheapest = {}
    for r in rows:  # Explore can list one airport twice (Miami and Fort Lauderdale are both FLL)
        k = (r["window_id"], r["code"])
        if k not in cheapest or r["price"] < cheapest[k]["price"]:
            cheapest[k] = r
    rows = pick.keep(list(cheapest.values()), cfg)
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
                 {"window_id": r["window_id"], "code": r["code"], "space": st.sid}, app_link(st.sid, r["window_id"], r["code"]))
            a = {"at": str(today), "code": r["code"], "out": r["out"], "ret": r["ret"], "price": r["price"], "kind": r["kind"]}
            st.add_alert(a)
            sent.append(a)


def latest(cfg, st, today, windows, wx):
    """The newest prices (21 days at most) of the windows that are still free, minus avoided airlines, with their
    weather, and their usual prices."""
    ids = {w.id: w for w in windows}
    rows = pick.keep(st.latest_rows(list(ids), (today - timedelta(days=21)).isoformat()), cfg)
    if wx:
        rows = [{**r, "weather": wx.of(r)} for r in rows]
    return rows, ids, baselines(st, {(r["code"], r["kind"]) for r in rows}, "9999")


def publish(cfg, st, today, windows, wx):
    rows, ids, base = latest(cfg, st, today, windows, wx)
    doc = pick.suggestions(rows, base, ids, cfg, datetime.now(TZ).isoformat(timespec="seconds"))
    st.write_suggestions(doc)
    return doc


def summary(cfg, st, today, windows, send, wx):
    rows, ids, base = latest(cfg, st, today, windows, wx)
    labels = [{**l, "block": storem.blocks(l)} for l in st.labels_since(st.summary_last())]
    send(*pick.summary(rows, base, ids, cfg, labels), None, app_link(st.sid))
    st.set_summary_last(datetime.now(TZ).isoformat(timespec="seconds"))


def windows_report(windows, labels, cfg, ci):
    """The repo is public, so in Actions logs only counts: no event titles, no away dates."""
    blocking = sum(storem.blocks(l) for l in labels)
    if ci:
        return [f"{len(windows)} free window{'s' if len(windows) != 1 else ''}, "
                f"{len(labels)} calendar event{'s' if len(labels) != 1 else ''} labelled ({blocking} block trips)"]
    return ([f"{w.id} {w.holiday or ''} cost {pick.cost(w, cfg)}" for w in windows]
            + [("BLOCK " if storem.blocks(l) else "ok    ") + f"{l['title']} - {l['why']}" for l in labels])


def next_run(now):
    """When the main cron (12:17 UTC every day, daily.yml) fires next."""
    n = now.astimezone(timezone.utc)
    t = n.replace(hour=12, minute=17, second=0, microsecond=0)
    return (t if t > n else t + timedelta(days=1)).isoformat(timespec="seconds")


def write_activity(cfg, st, today, windows, labels, doc, errors):
    """meta/activity: what the Activity screen shows. Errors are kept 20 deep, newest first."""
    now, b = datetime.now(TZ), st.budget(month(today))
    picks = {w["id"]: len(w["picks"]) for w in (doc or {}).get("windows", [])}
    st.set_activity({"last_run": now.isoformat(timespec="seconds"), "next_run": next_run(now), "month": month(today),
                     "used": b["used"], "cap": cfg["search"]["cap"],
                     "windows": [{"id": w.id, "searched_at": b["last"].get(w.id), "picks": picks.get(w.id, 0)} for w in windows],
                     "labelled": len(labels), "blocking": sum(labels.values()),
                     "errors": ([f"{today}: {e}" for e in errors] + st.activity().get("errors", []))[:20]})


def daily(cfg, st, today, fetch=cal.fetch, chat=ai.http_chat, get=serp.http_get, send=None, wget=weather.http_get):
    """One space's morning: its calendars -> free windows -> its SerpApi searches -> suggestions, alerts, activity."""
    keys, errors, windows, labels, doc = st.keys(), [], [], {}, None
    send = send or (lambda *a: push.send(st, *a))
    ask = lambda p, m: chat(p, m, keys.get("gemini"))
    search = lambda p: get(p, keys.get("serpapi"))
    try:
        if not keys.get("calendars"):
            errors.append("Add a calendar in Settings")
        else:
            if not keys.get("gemini"):
                errors.append("Add a Gemini key in Settings")
            windows, labels = free_windows(cfg, st, today, fetch, ask)
            if keys.get("serpapi"):
                rows = sweep(cfg, st, today, windows, search, send, errors)
                try:
                    instant_alerts(cfg, st, today, rows, search, send)
                except Exception as e:  # never let an alert problem cost us the Sunday summary
                    print(f"alerts failed: {e}", file=sys.stderr)
                    errors.append("Deal alerts failed")
            else:
                errors.append("Add a SerpApi key in Settings")
            wx = weather.Weather(st, today, wget)
            doc = publish(cfg, st, today, windows, wx)
            if today.weekday() == 6:
                summary(cfg, st, today, windows, send, wx)
    except Exception as e:  # only the kind of error is kept: messages can carry calendar links
        print(f"space {st.sid}: run failed ({type(e).__name__})", file=sys.stderr)
        errors.append(f"Run failed ({type(e).__name__})")
    write_activity(cfg, st, today, windows, labels, doc, errors)


def command(st, cmd, today, fetch=cal.fetch, chat=ai.http_chat, wget=weather.http_get, **kw):
    cfg = load_cfg(st)
    ask = lambda p, m: chat(p, m, st.keys().get("gemini"))
    if cmd == "daily":
        if os.environ.get("FLYBYE_BACKUP") and st.activity().get("last_run", "").startswith(str(today)):
            return  # the backup cron: this space already ran today
        daily(cfg, st, today, fetch=fetch, chat=chat, wget=wget, **kw)
    elif cmd == "windows":
        ws, _ = free_windows(cfg, st, today, fetch, ask)
        report = windows_report(ws, list(reversed(st.labels_since(""))), cfg, bool(os.environ.get("GITHUB_ACTIONS")))
        print("\n".join(f"space {st.sid}: {line}" for line in report))
    elif cmd == "summary":
        ws, _ = free_windows(cfg, st, today, fetch, ask)
        summary(cfg, st, today, ws, lambda *a: push.send(st, *a), weather.Weather(st, today, wget))
    elif cmd == "test-notify":
        push.send(st, "Flybye test", "If you see this, Flybye can reach your phone.", None, app_link(st.sid))


def run_all(fs, cmd, today, **kw):
    """Every space on its own: one that breaks never stops the others."""
    for sid in storem.Store.spaces(fs):
        try:
            command(storem.Store(fs, sid), cmd, today, **kw)
        except Exception as e:
            print(f"space {sid}: {cmd} failed ({type(e).__name__})", file=sys.stderr)


def main(argv):
    cmd = argv[0] if argv else "daily"
    if cmd not in ("daily", "windows", "summary", "test-notify"):
        sys.exit(__doc__)
    run_all(storem.connect(), cmd, datetime.now(TZ).date())


if __name__ == "__main__":
    main(sys.argv[1:])
