"""Open-Meteo weather for a trip: the forecast within 16 days, otherwise a 10-year typical for that city and month.
Any failure gives None (no weather), never an error."""
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
YEARS, FRESH_DAYS, WET_MM = 10, 180, 1.0


def http_get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _url(base, lat, lon, start, end, daily):
    return base + "?" + urllib.parse.urlencode({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                                                "daily": daily, "temperature_unit": "fahrenheit", "timezone": "auto"})


class Weather:
    """One per space and run: remembers what it already asked for."""

    def __init__(self, st, today, get=http_get):
        self.st, self.today, self.get, self.memo = st, today, get, {}

    def of(self, row):
        """{kind: forecast|typical, hi_f, lo_f, rain_pct} for a priced row, or None."""
        if row.get("lat") is None or row.get("lon") is None:
            return None
        out = date.fromisoformat(row["out"])
        try:
            if (out - self.today).days < 16:
                return self._forecast(row["lat"], row["lon"], out, date.fromisoformat(row["ret"]))
            return self._typical(row["code"], row["lat"], row["lon"], f"{out:%m}")
        except Exception as e:  # weather is a bonus: a failure never blocks a run
            print(f"weather failed: {type(e).__name__}", file=sys.stderr)
            return None

    def _memo(self, key, make):
        if key not in self.memo:
            try:
                self.memo[key] = make()
            except Exception:
                self.memo[key] = None
                raise
        return self.memo[key]

    def _forecast(self, lat, lon, out, ret):
        end = min(ret, self.today + timedelta(days=15))
        return self._memo(("f", lat, lon, out, end), lambda: self._fetch_forecast(lat, lon, out, end))

    def _fetch_forecast(self, lat, lon, out, end):
        d = self.get(_url(FORECAST, lat, lon, out, end,
                          "temperature_2m_max,temperature_2m_min,precipitation_probability_max"))["daily"]
        hi, lo, rain = (_avg(d[k]) for k in ("temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"))
        if hi is None or lo is None:
            return None
        return {"kind": "forecast", "hi_f": round(hi), "lo_f": round(lo), "rain_pct": round(rain or 0)}

    def _typical(self, code, lat, lon, mm):
        key = ("c", code, mm)
        if key not in self.memo:
            c = self.st.climate(code, mm)
            if c and c["at"] >= (self.today - timedelta(days=FRESH_DAYS)).isoformat():
                self.memo[key] = {"kind": "typical", **{k: c[k] for k in ("hi_f", "lo_f", "rain_pct")}}
            else:
                self.memo[key] = None  # so a failed request isn't repeated for every row of this city
                self._archive(code, lat, lon)
        return self.memo.get(key)

    def _archive(self, code, lat, lon):
        """One request fills all 12 months of a city: cached for everyone, and remembered for this run."""
        y = self.today.year
        d = self.get(_url(ARCHIVE, lat, lon, f"{y - YEARS}-01-01", f"{y - 1}-12-31",
                          "temperature_2m_max,temperature_2m_min,precipitation_sum"))["daily"]
        by_month = {}
        for t, hi, lo, mm in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["precipitation_sum"]):
            if hi is not None and lo is not None:
                by_month.setdefault(t[5:7], []).append((hi, lo, (mm or 0) >= WET_MM))
        for m, days in by_month.items():
            w = {"hi_f": round(_avg([x[0] for x in days])), "lo_f": round(_avg([x[1] for x in days])),
                 "rain_pct": round(100 * sum(x[2] for x in days) / len(days))}
            self.st.set_climate(code, m, {**w, "years": YEARS, "at": self.today.isoformat()})
            self.memo[("c", code, m)] = {"kind": "typical", **w}
