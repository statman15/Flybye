"""python -m flybye daily | windows | summary | test-notify   (run from the repo root; reads config.yaml)"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import yaml

from . import ai, cal, pick, serp
from . import db as dbm
from .windows import TZ, Window, candidates, is_free


def ntfy(title, message, click=None):
    body = {"topic": os.environ["NTFY_TOPIC"], "title": title, "message": message, **({"click": click} if click else {})}
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).close()


def flights_link(row, cfg):
    q = f"Flights to {row['code']} from {cfg.get('home', 'ORD')} on {row['out']} through {row['ret']} nonstop"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def free_windows(cfg, db, today, fetch, chat):
    now = datetime.combine(today, datetime.min.time(), TZ)
    last_week = max(c["weeks"][1] for c in cfg["trips"].values())
    events = cal.parse(fetch(os.environ.get("ICAL_URL", "")), now - timedelta(days=1), now + timedelta(weeks=last_week + 2))
    labels = ai.label_events(events, db, cfg, chat)
    blockers = [e for e in events if labels[f"{e.uid}|{e.title}"]]
    return [w for w in candidates(today, cfg["trips"]) if is_free(w, blockers)]


def used_this_month(db, today):
    return db.execute("SELECT count(*) FROM searches WHERE at >= ?", (f"{today:%Y-%m}-01",)).fetchone()[0]


def baselines(db, codes_kinds, before):
    out = {}
    for code, kind in codes_kinds:
        rows = db.execute("SELECT price, window_id FROM prices WHERE code=? AND kind=? AND seen < ?", (code, kind, before))
        out[(code, kind)] = pick.baseline([dict(r) for r in rows])
    return out


def sweep(cfg, db, today, windows, get, send):
    last = {r[0]: r[1] for r in db.execute("SELECT window_id, max(at) FROM searches GROUP BY window_id")}
    budget = pick.allowance(cfg["search"]["cap"], used_this_month(db, today), today)
    rows = []
    calls = []
    for w in pick.choose(windows, last, budget, cfg):
        calls += [lambda w=w, a=a: serp.explore(w, a, cfg, db, get)
                  for a in (cfg["search"]["long_areas"] if w.kind == "long" else [None])]
        calls += [lambda w=w, c=c: [r for r in [serp.flights(w, c["airports"], c["stops"], c["name"], cfg, db, get)] if r]
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
    db.executemany("INSERT INTO prices VALUES(:seen,:window_id,:kind,:out,:ret,:code,:name,:price,:hotel,:minutes,"
                   ":airline,:stops,:source)", [{**r, "seen": str(today)} for r in rows])
    db.commit()
    return rows


def instant_alerts(cfg, db, today, rows, get, send):
    base = baselines(db, {(r["code"], r["kind"]) for r in rows}, str(today))
    sent = [dict(r) for r in db.execute("SELECT * FROM alerts")]
    week_ago = (today - timedelta(days=7)).isoformat()
    recent = {r[0] for r in db.execute("SELECT window_id FROM searches WHERE engine='google_flights' AND at >= ?", (week_ago,))}
    for r in pick.deal_candidates(rows, base, cfg, recent):
        if used_this_month(db, today) >= cfg["search"]["cap"] or pick.week_full(sent, today, cfg):
            return
        try:
            c = serp.confirm(r, cfg, db, get)
        except Exception as e:
            print(f"confirm failed for {r['code']} {r['window_id']}: {e}", file=sys.stderr)
            continue
        if pick.should_alert(r, c, sent, today, cfg):
            r = {**r, "price": c["lowest"] or r["price"]}
            msg = (pick.fmt_row(r, base.get((r["code"], r["kind"])), cfg)
                   + f"\nGoogle's usual: ${c['typical_low']}–${c['typical_high']} for this trip. You're both free.")
            send("Flybye deal: " + pick.city_for(r["code"], cfg)["name"], msg, flights_link(r, cfg))
            a = {"at": str(today), "code": r["code"], "out": r["out"], "ret": r["ret"], "price": r["price"], "kind": r["kind"]}
            db.execute("INSERT INTO alerts VALUES(:at,:code,:out,:ret,:price,:kind)", a)
            db.commit()
            sent.append(a)


def summary(cfg, db, today, windows, send):
    ids = {w.id: w for w in windows}
    rows = [dict(r) for r in db.execute(
        "SELECT p.* FROM prices p JOIN (SELECT window_id, code, max(seen) s FROM prices GROUP BY window_id, code) m "
        "ON p.window_id = m.window_id AND p.code = m.code AND p.seen = m.s WHERE p.seen >= ?",
        ((today - timedelta(days=21)).isoformat(),)) if r["window_id"] in ids]
    base = baselines(db, {(r["code"], r["kind"]) for r in rows}, "9999")
    since = dbm.get(db, "last_summary", "")
    labels = [dict(r) for r in db.execute("SELECT title, block, why FROM labels WHERE at > ? ORDER BY at", (since,))]
    send(*pick.summary(rows, base, ids, cfg, labels))
    dbm.put(db, "last_summary", datetime.now().isoformat(timespec="seconds"))


def daily(cfg, db, today, fetch=cal.fetch, chat=ai.http_chat, get=serp.http_get, send=ntfy):
    windows = free_windows(cfg, db, today, fetch, chat)
    rows = sweep(cfg, db, today, windows, get, send)
    try:
        instant_alerts(cfg, db, today, rows, get, send)
    except Exception as e:  # never let an alert problem cost us the Sunday summary
        print(f"alerts failed: {e}", file=sys.stderr)
    if today.weekday() == 6:
        summary(cfg, db, today, windows, send)


def main(argv):
    cfg = yaml.safe_load(open(os.environ.get("FLYBYE_CONFIG", "config.yaml"), encoding="utf-8"))
    os.makedirs(os.path.dirname(cfg["db"]) or ".", exist_ok=True)
    db, today = dbm.connect(cfg["db"]), datetime.now(TZ).date()
    cmd = argv[0] if argv else "daily"
    if cmd == "daily":
        daily(cfg, db, today)
    elif cmd == "windows":
        for w in free_windows(cfg, db, today, cal.fetch, ai.http_chat):
            print(w.id, w.holiday or "", f"cost {pick.cost(w, cfg)}")
        for r in db.execute("SELECT title, block, why FROM labels ORDER BY at DESC"):
            print(("BLOCK " if r["block"] else "ok    ") + r["title"], "-", r["why"])
    elif cmd == "summary":
        summary(cfg, db, today, free_windows(cfg, db, today, cal.fetch, ai.http_chat), ntfy)
    elif cmd == "test-notify":
        ntfy("Flybye test", "If you see this, Flybye can reach your phone.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
