"""Pure decisions: how many searches today, which windows, what's a deal, what to alert, how picks read."""
import calendar
import statistics
from datetime import date


def allowance(cap, used, today):
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    return max(0, (cap - used) // days_left)


def city_for(code, cfg):
    return next((c for c in cfg["cities"] if code in c["airports"]), None)


def own_stops_cities(kind, cfg):
    """Wish cities with their own stops rule (Porto) get a separate google_flights search."""
    return [c for c in cfg["cities"] if "stops" in c and kind in c["trips"]]


def cost(w, cfg):
    areas = len(cfg["search"]["long_areas"]) if w.kind == "long" else 1
    return areas + len(own_stops_cities(w.kind, cfg))


def choose(windows, last_searched, budget, cfg):
    order = sorted(windows, key=lambda w: (w.id in last_searched, last_searched.get(w.id, ""), w.out))
    picked = []
    for w in order:
        if cost(w, cfg) <= budget:
            picked.append(w)
            budget -= cost(w, cfg)
    return picked


def baseline(rows):
    """A route's usual price for a trip type: the median, once we've seen it 4+ times across 2+ windows."""
    if len(rows) < 4 or len({r["window_id"] for r in rows}) < 2:
        return None
    return statistics.median(r["price"] for r in rows)


def deal_candidates(rows, baselines, cfg, recent=()):
    """recent: "<window_id>|<code>" pairs already confirmed lately, not worth another search yet."""
    out = []
    for r in rows:
        if not city_for(r["code"], cfg) or f"{r['window_id']}|{r['code']}" in recent:
            continue
        b = baselines.get((r["code"], r["kind"]))
        ratio = r["price"] / b if b else 1.0  # unknown baseline: worth a check, after the real deals
        if b is None or ratio <= cfg["alerts"]["deal_ratio"]:
            out.append((ratio, r))
    out.sort(key=lambda x: (x[0], x[1]["price"]))
    return [r for _, r in out[:cfg["search"]["confirm_per_run"]]]


def week_full(sent, today, cfg):
    week = today.isocalendar()[:2]
    return sum(date.fromisoformat(a["at"][:10]).isocalendar()[:2] == week for a in sent) >= cfg["alerts"]["max_instant_per_week"]


def should_alert(row, confirm, sent, today, cfg):
    price = confirm.get("lowest") or row["price"]
    if not confirm.get("typical_low") or price > confirm["typical_low"] or week_full(sent, today, cfg):
        return False
    before = [a["price"] for a in sent if (a["code"], a["out"], a["ret"]) == (row["code"], row["out"], row["ret"])]
    return not before or price <= cfg["alerts"]["repeat_drop"] * min(before)


def score(row, base, w, cfg):
    s = cfg["score"]
    pct = (base - row["price"]) / base * 100 if base else 0
    return (pct - s["hour_penalty"] * row["minutes"] / 60 + (s["wish_bonus"] if city_for(row["code"], cfg) else 0)
            + (s["holiday_bonus"] if w.holiday else 0))


def _d(iso):
    d = date.fromisoformat(iso)
    return f"{d:%a %b} {d.day}"


def fmt_row(row, base, cfg):
    city = city_for(row["code"], cfg)
    name = city["name"] if city else row["name"]
    vs = f" ({round((base - row['price']) / base * 100)}% under usual)" if base and row["price"] < base else ""
    stops = "nonstop" if not row["stops"] else f"{row['stops']} stop"
    hotel = f" · hotel ~${round(row['hotel'])}" if row.get("hotel") else ""
    return (f"{name} · {_d(row['out'])}–{_d(row['ret'])} · ${round(row['price'])} for {cfg['search']['adults']}{vs}"
            f" · {row['minutes'] // 60}h{row['minutes'] % 60:02d} {stops}{hotel}")


def summary(rows, baselines, windows, cfg, new_labels):
    """rows: latest price per (window, city) for windows that are still free. windows: id -> Window."""
    scored = sorted(((score(r, baselines.get((r["code"], r["kind"])), windows[r["window_id"]], cfg), r)
                     for r in rows if r["window_id"] in windows), key=lambda x: -x[0])
    wish = [r for _, r in scored if city_for(r["code"], cfg)][:3]
    other = next((r for _, r in scored if not city_for(r["code"], cfg)), None)
    lines = [fmt_row(r, baselines.get((r["code"], r["kind"])), cfg) for r in wish]
    if other:
        lines.append("Surprise: " + fmt_row(other, baselines.get((other["code"], other["kind"])), cfg))
    if not lines:
        lines.append("No priced trips fit your free dates yet.")
    if new_labels:  # counts only: event titles never go through ntfy
        n, b = len(new_labels), sum(bool(l["block"]) for l in new_labels)
        lines.append(f"{n} new calendar event{'s' if n != 1 else ''} checked, {b} block trips (details: run 'windows').")
    return "Flybye: this week's best getaways", "\n".join(lines)
