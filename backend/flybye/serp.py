"""SerpApi calls. Every call is logged in the store so the monthly cap holds."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from .windows import window


class Fatal(Exception):
    """Out of searches or a bad key: stop searching for today."""


def http_get(params, key):
    q = urllib.parse.urlencode({**params, "api_key": key})
    try:
        with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # SerpApi puts the reason in a JSON body (401 bad key, 429 out of searches)
        return json.load(e)


def _call(params, window_id, st, get):
    st.log_search(window_id)
    d = get(params)
    err = d.get("error")
    if not err:
        return d
    if "hasn't returned any results" in err or err.startswith("Empty results"):
        return {}
    if re.search(r"run out|api key|account", err, re.I):
        raise Fatal(err)
    raise RuntimeError(f"SerpApi: {err}")


def _base(engine, w, cfg, **extra):
    dates = {"outbound_date": str(w.out), "return_date": str(w.ret)} if w else {}
    return {"engine": engine, "departure_id": cfg.get("home", "ORD"), **dates, "type": 1, "adults": cfg["search"]["adults"], "stops": cfg["search"]["stops"],
            "currency": "USD", "hl": "en", "gl": "us", **extra}


def _row(w, code, name, price, hotel, minutes, airline, stops, source, airline_code=None, gps=None, country=None):
    return {"window_id": w.id, "kind": w.kind, "out": str(w.out), "ret": str(w.ret), "code": code, "name": name,
            "price": price, "hotel": hotel, "minutes": minutes, "airline": airline, "airline_code": airline_code,
            "lat": (gps or {}).get("latitude"), "lon": (gps or {}).get("longitude"), "stops": stops, "source": source,
            "country": country}


def explore(w, area, cfg, st, get):
    p = _base("google_travel_explore", w, cfg, travel_mode=1)
    if area:
        p["arrival_area_id"] = area
    d = _call(p, w.id, st, get)
    return [_explore_row(w, x, "explore") for x in d.get("destinations", []) if x.get("flight_price") and x.get("destination_airport")]


def _explore_row(w, x, source):
    return _row(w, x["destination_airport"]["code"], x["name"], x["flight_price"], x.get("hotel_price"),
                x.get("flight_duration", 0), x.get("airline"), x.get("number_of_stops", 0), source,
                x.get("airline_code"), x.get("gps_coordinates"), x.get("country"))


def explore_flex(area, cfg, st, get):
    """No dates: Google picks each city's cheapest ~1-week round trip over the next ~6 months (one date pair per city)."""
    p = _base("google_travel_explore", None, cfg, travel_mode=1, travel_duration=2)
    if area:
        p["arrival_area_id"] = area
    d = _call(p, flex_key(area), st, get)
    return [_explore_row(window("long", date.fromisoformat(x["start_date"]), date.fromisoformat(x["end_date"])), x, "flex")
            for x in d.get("destinations", [])
            if x.get("flight_price") and x.get("destination_airport") and x.get("start_date") and x.get("end_date")]


def typical(w, city, cfg, st, get):
    """Google's typical price range (total for every traveler) for a wish city on a trip like w, from its own fare history.
    One lookup stands for every trip of that type to that city leaving in the same month."""
    from .pick import typical_id
    d = _call({**_base("google_flights", w, cfg), "arrival_id": ",".join(city["airports"]),
               "stops": city.get("stops", cfg["search"]["stops"])}, "typical:" + typical_id(city, w.kind, f"{w.out:%Y-%m}"), st, get)
    rng = d.get("price_insights", {}).get("typical_price_range")
    return {"low": rng[0], "high": rng[-1]} if rng else None


def flex_key(area):
    return f"flex:{area or 'home'}"


def _itins(d):
    return d.get("best_flights", []) + d.get("other_flights", [])


def flights(w, airports, stops, name, cfg, st, get):
    d = _call({**_base("google_flights", w, cfg), "arrival_id": ",".join(airports), "stops": stops}, w.id, st, get)
    best = min(_itins(d), key=lambda x: x["price"], default=None)
    if not best:
        return None
    arrive = (d.get("airports") or [{}])[0].get("arrival") or [{}]
    return _row(w, airports[0], name, best["price"], None, best["total_duration"],
                best["flights"][0]["airline"], len(best.get("layovers", [])), "flights",
                (best["flights"][0].get("flight_number") or "").split(" ")[0] or None, country=arrive[0].get("country"))


def confirm(row, cfg, st, get):
    from .pick import city_for
    from .windows import Window
    w = Window(row["kind"], datetime.fromisoformat(row["out"]).date(), datetime.fromisoformat(row["ret"]).date(), None)
    stops = (city_for(row["code"], cfg) or {}).get("stops", cfg["search"]["stops"])
    # logged as "<window>|<code>" so it doesn't count as an Explore refresh of the window
    d = _call({**_base("google_flights", w, cfg), "arrival_id": row["code"], "stops": stops}, f"{w.id}|{row['code']}", st, get)
    pi = d.get("price_insights", {})
    rng = pi.get("typical_price_range") or [None, None]
    first = min(_itins(d), key=lambda x: x["price"], default=None)
    return {"lowest": pi.get("lowest_price"), "typical_low": rng[0], "typical_high": rng[-1], "level": pi.get("price_level"),
            "depart": first["flights"][0]["departure_airport"]["time"] if first else None}
