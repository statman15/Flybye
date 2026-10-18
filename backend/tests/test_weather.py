from datetime import date

from fakefs import new_store
from flybye.weather import Weather

TODAY = date(2026, 10, 17)


def forecast_json(days=3):
    return {"daily": {"time": [f"2026-10-{20 + i}" for i in range(days)],
                      "temperature_2m_max": [80, 70, None][:days], "temperature_2m_min": [60, 50, None][:days],
                      "precipitation_probability_max": [10, 30, None][:days]}}


def archive_json():
    """Ten Januaries (every day 40/20 degrees, wet on the 1st only) and ten Julys (90/70, always dry)."""
    t, hi, lo, rain = [], [], [], []
    for y in range(2016, 2026):
        for m, h, l in ((1, 40, 20), (7, 90, 70)):
            for d in range(1, 29):
                t.append(f"{y}-{m:02d}-{d:02d}")
                hi.append(h)
                lo.append(l)
                rain.append(5.0 if d == 1 and m == 1 else 0.0)
    return {"daily": {"time": t, "temperature_2m_max": hi, "temperature_2m_min": lo, "precipitation_sum": rain}}


class Net:
    def __init__(self, fc=None, ar=None):
        self.urls, self.fc, self.ar = [], fc or forecast_json(), ar or archive_json()

    def __call__(self, url):
        self.urls.append(url)
        if "archive-api" in url:
            return self.ar
        return self.fc


def trip(out, ret, code="DEN", lat=39.8, lon=-104.7):
    return {"code": code, "out": out, "ret": ret, "lat": lat, "lon": lon}


def test_a_trip_within_16_days_uses_the_forecast_averaged_over_its_days():
    net, st = Net(), new_store()
    w = Weather(st, TODAY, net).of(trip("2026-10-20", "2026-10-22"))
    assert w == {"kind": "forecast", "hi_f": 75, "lo_f": 55, "rain_pct": 20}      # the empty third day is skipped
    u = net.urls[0]
    assert u.startswith("https://api.open-meteo.com/v1/forecast?") and "temperature_unit=fahrenheit" in u
    assert "start_date=2026-10-20" in u and "end_date=2026-10-22" in u and "latitude=39.8" in u


def test_a_forecast_is_asked_once_per_place_and_dates():
    net = Net()
    wx = Weather(new_store(), TODAY, net)
    wx.of(trip("2026-10-20", "2026-10-21"))
    wx.of(trip("2026-10-20", "2026-10-21"))
    assert len(net.urls) == 1


def test_a_trip_that_ends_after_the_forecast_horizon_asks_only_for_what_exists():
    net = Net()
    Weather(new_store(), TODAY, net).of(trip("2026-10-31", "2026-11-04"))
    assert "end_date=2026-11-01" in net.urls[0]


def test_a_later_trip_uses_ten_year_typical_weather_and_caches_every_month():
    net, st = Net(), new_store()
    w = Weather(st, TODAY, net).of(trip("2027-01-15", "2027-01-17"))
    assert w == {"kind": "typical", "hi_f": 40, "lo_f": 20, "rain_pct": 4}      # 1 wet day in 28
    assert len(net.urls) == 1 and net.urls[0].startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "start_date=2016-01-01" in net.urls[0] and "end_date=2025-12-31" in net.urls[0]
    assert st.climate("DEN", "07")["hi_f"] == 90 and st.climate("DEN", "01")["years"] == 10


def test_climate_cache_hit_makes_no_request_and_a_stale_one_is_refreshed():
    net, st = Net(), new_store()
    st.set_climate("DEN", "01", {"hi_f": 33, "lo_f": 11, "rain_pct": 9, "years": 10, "at": "2026-08-01"})   # 77 days old
    assert Weather(st, TODAY, net).of(trip("2027-01-15", "2027-01-17"))["hi_f"] == 33 and net.urls == []
    st.set_climate("DEN", "01", {"hi_f": 33, "lo_f": 11, "rain_pct": 9, "years": 10, "at": "2026-03-01"})   # 230 days old
    assert Weather(st, TODAY, net).of(trip("2027-01-15", "2027-01-17"))["hi_f"] == 40 and len(net.urls) == 1


def test_failures_and_missing_coordinates_mean_no_weather_and_dont_raise():
    def boom(url):
        raise OSError("down")
    wx = Weather(new_store(), TODAY, boom)
    assert wx.of(trip("2026-10-20", "2026-10-21")) is None
    assert wx.of(trip("2027-01-15", "2027-01-17")) is None
    assert Weather(new_store(), TODAY, Net()).of(trip("2026-10-20", "2026-10-21", lat=None, lon=None)) is None
    assert Weather(new_store(), TODAY, lambda u: {"daily": {"time": []}}).of(trip("2026-10-20", "2026-10-21")) is None


def test_a_failed_archive_request_is_not_repeated_for_every_row_of_the_city():
    calls = []

    def boom(url):
        calls.append(url)
        raise OSError("down")
    wx = Weather(new_store(), TODAY, boom)
    for _ in range(5):
        wx.of(trip("2027-01-15", "2027-01-17"))
    assert len(calls) == 1


def test_only_a_few_new_cities_are_looked_up_per_run_so_the_first_run_stays_quick():
    from flybye import weather
    net, st = Net(), new_store()
    wx = Weather(st, TODAY, net)
    got = [wx.of(trip("2027-01-15", "2027-01-17", code=f"C{i:02d}")) for i in range(weather.NEW_CITIES_PER_RUN + 5)]
    assert len(net.urls) == weather.NEW_CITIES_PER_RUN                       # the rest wait for the next run
    assert all(got[:weather.NEW_CITIES_PER_RUN]) and not any(got[weather.NEW_CITIES_PER_RUN:])
