"""SerpApi calls. Every call is logged to `searches` so the monthly cap holds."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime


def http_get(params):
    q = urllib.parse.urlencode({**params, "api_key": os.environ["SERPAPI_KEY"]})
    with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=120) as r:
        return json.load(r)


def _call(params, window_id, db, get):
    db.execute("INSERT INTO searches VALUES(?,?,?)", (datetime.now().isoformat(timespec="seconds"), params["engine"], window_id))
    db.commit()
    d = get(params)
    if "error" in d:
        raise RuntimeError(f"SerpApi: {d['error']}")
    return d


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
    from .windows import Window
    w = Window(row["kind"], datetime.fromisoformat(row["out"]).date(), datetime.fromisoformat(row["ret"]).date(), None)
    d = _call({**_base("google_flights", w, cfg), "arrival_id": row["code"]}, w.id, db, get)
    pi = d.get("price_insights", {})
    rng = pi.get("typical_price_range") or [None, None]
    first = min(_itins(d), key=lambda x: x["price"], default=None)
    return {"lowest": pi.get("lowest_price"), "typical_low": rng[0], "typical_high": rng[-1], "level": pi.get("price_level"),
            "depart": first["flights"][0]["departure_airport"]["time"] if first else None}
