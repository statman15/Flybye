"""SerpApi calls. Every call is logged to `searches` so the monthly cap holds."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime


class Fatal(Exception):
    """Out of searches or a bad key: stop searching for today."""


def http_get(params):
    q = urllib.parse.urlencode({**params, "api_key": os.environ["SERPAPI_KEY"]})
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # SerpApi puts the reason in a JSON body (401 bad key, 429 out of searches)
        return json.load(e)


def _call(params, window_id, db, get):
    db.execute("INSERT INTO searches VALUES(?,?,?)", (datetime.now().isoformat(timespec="seconds"), params["engine"], window_id))
    db.commit()
    d = get(params)
    err = d.get("error")
    if not err:
        return d
    if "hasn't returned any results" in err:
        return {}
    if re.search(r"run out|api key|account", err, re.I):
        raise Fatal(err)
    raise RuntimeError(f"SerpApi: {err}")


def _base(engine, w, cfg, **extra):
    return {"engine": engine, "departure_id": cfg.get("home", "ORD"), "outbound_date": str(w.out),
            "return_date": str(w.ret), "type": 1, "adults": cfg["search"]["adults"], "stops": cfg["search"]["stops"],
            "currency": "USD", "hl": "en", "gl": "us", **extra}


def _row(w, code, name, price, hotel, minutes, airline, stops, source):
    return {"window_id": w.id, "kind": w.kind, "out": str(w.out), "ret": str(w.ret), "code": code, "name": name,
            "price": price, "hotel": hotel, "minutes": minutes, "airline": airline, "stops": stops, "source": source}


def explore(w, area, cfg, db, get=http_get):
    p = _base("google_travel_explore", w, cfg, travel_mode=1)
    if area:
        p["arrival_area_id"] = area
    d = _call(p, w.id, db, get)
    return [_row(w, x["destination_airport"]["code"], x["name"], x["flight_price"], x.get("hotel_price"),
                 x.get("flight_duration", 0), x.get("airline"), x.get("number_of_stops", 0), "explore")
            for x in d.get("destinations", []) if x.get("flight_price") and x.get("destination_airport")]


def _itins(d):
    return d.get("best_flights", []) + d.get("other_flights", [])


def flights(w, airports, stops, name, cfg, db, get=http_get):
    d = _call({**_base("google_flights", w, cfg), "arrival_id": ",".join(airports), "stops": stops}, w.id, db, get)
    best = min(_itins(d), key=lambda x: x["price"], default=None)
    if not best:
        return None
    return _row(w, airports[0], name, best["price"], None, best["total_duration"],
                best["flights"][0]["airline"], len(best.get("layovers", [])), "flights")


def confirm(row, cfg, db, get=http_get):
    from .pick import city_for
    from .windows import Window
    w = Window(row["kind"], datetime.fromisoformat(row["out"]).date(), datetime.fromisoformat(row["ret"]).date(), None)
    stops = (city_for(row["code"], cfg) or {}).get("stops", cfg["search"]["stops"])
    # logged as "<window>|<code>" so it doesn't count as an Explore refresh of the window
    d = _call({**_base("google_flights", w, cfg), "arrival_id": row["code"], "stops": stops}, f"{w.id}|{row['code']}", db, get)
    pi = d.get("price_insights", {})
    rng = pi.get("typical_price_range") or [None, None]
    first = min(_itins(d), key=lambda x: x["price"], default=None)
    return {"lowest": pi.get("lowest_price"), "typical_low": rng[0], "typical_high": rng[-1], "level": pi.get("price_level"),
            "depart": first["flights"][0]["departure_airport"]["time"] if first else None}
