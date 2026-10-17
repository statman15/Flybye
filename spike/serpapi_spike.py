"""Milestone 1 spike: 3 SerpApi searches to settle how the sweep works (see PLAN.md).

1. Explore from ORD on exact weekend dates: does one call price many destinations on OUR dates?
2. Explore from ORD with flexible dates (weekend, any month): which dates does it pick?
3. Flights ORD->BNA on the same dates: what price_insights really holds, and is price for 2 adults?

Run: python spike/serpapi_spike.py   (asks for the key once, keeps it in serpapi.key, git-ignored)
Raw JSON goes to spike/out/.
"""
import getpass, json, os, pathlib, urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "serpapi.key"
OUT = ROOT / "spike" / "out"
OUT_DATE, RET_DATE = "2026-11-13", "2026-11-15"  # a Fri-Sun weekend ~4 weeks out
COMMON = {"departure_id": "ORD", "adults": 2, "stops": 1, "currency": "USD", "hl": "en", "gl": "us"}


def key():
    if os.environ.get("SERPAPI_KEY"):
        return os.environ["SERPAPI_KEY"]
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    k = getpass.getpass("SerpApi key (input hidden): ").strip()
    KEY_FILE.write_text(k)
    return k


def search(name, params):
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode({**COMMON, **params, "api_key": key()})
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        data = {"http_error": e.code, "body": e.read().decode(errors="replace")[:2000]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2))
    print(f"\n=== {name} ===")
    if "error" in data or "http_error" in data:
        print("ERROR:", data.get("error") or data)
    return data


def show_explore(d):
    dests = d.get("destinations", [])
    print(f"{len(dests)} destinations; keys: {sorted(dests[0]) if dests else '-'}")
    for x in dests[:15]:
        print(f"  {x.get('name')!s:22} {x.get('destination_airport', {}).get('code')}  ${x.get('flight_price')}"
              f"  {x.get('start_date')}..{x.get('end_date')}  stops={x.get('number_of_stops')}  {x.get('flight_duration')}min")


e1 = search("1_explore_exact_dates", {"engine": "google_travel_explore", "outbound_date": OUT_DATE,
                                      "return_date": RET_DATE, "travel_mode": 1})
show_explore(e1)
print(f"All on our dates? {all(x.get('start_date') == OUT_DATE for x in e1.get('destinations', []))}")

e2 = search("2_explore_flexible_weekend", {"engine": "google_travel_explore", "month": 0, "travel_duration": 1,
                                           "travel_mode": 1})
show_explore(e2)

f = search("3_flights_ORD_BNA", {"engine": "google_flights", "arrival_id": "BNA", "outbound_date": OUT_DATE,
                                 "return_date": RET_DATE, "type": 1})
print("price_insights:", json.dumps({k: v for k, v in f.get("price_insights", {}).items() if k != "price_history"}))
print("price_history points:", len(f.get("price_insights", {}).get("price_history", [])))
for x in (f.get("best_flights", []) + f.get("other_flights", []))[:5]:
    legs = x.get("flights", [])
    print(f"  ${x.get('price')}  {x.get('total_duration')}min  {legs[0].get('airline') if legs else '?'}"
          f"  dep {legs[0].get('departure_airport', {}).get('time') if legs else '?'}")
if "search_metadata" in f:
    print("\nCompare a price above with google.com/travel/flights for 2 adults, ORD-BNA, Nov 13-15, nonstop.")
