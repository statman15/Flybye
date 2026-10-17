from datetime import date, datetime
from zoneinfo import ZoneInfo

from flybye.cal import Event
from flybye.windows import Window, candidates, holidays, is_free

TZ = ZoneInfo("America/Chicago")
TRIPS = {"weekend": {"on": True, "weeks": [2, 10]},
         "3day": {"on": True, "weeks": [2, 12]},
         "long": {"on": True, "weeks": [3, 17], "nights": [7]}}
TODAY = date(2026, 10, 17)  # a Saturday


def ev(start, end, all_day=False):
    return Event("u", "x", start, end, all_day, False)


def test_holidays_2026():
    h = holidays(2026)
    assert h[date(2026, 9, 7)] == "Labor Day"
    assert h[date(2026, 11, 26)] == "Thanksgiving"
    assert date(2026, 11, 27) in h
    assert h[date(2026, 1, 19)] == "MLK Day"
    assert h[date(2026, 5, 25)] == "Memorial Day"


def test_weekend_lead_time_edges():
    w = [x for x in candidates(TODAY, TRIPS) if x.kind == "weekend"]
    assert all(x.out.weekday() == 4 and (x.ret - x.out).days == 2 for x in w)
    assert min(x.out for x in w) == date(2026, 11, 6)    # first Fri >= today + 14d
    assert max(x.out for x in w) == date(2026, 12, 25)   # last Fri <= today + 70d


def test_3day_has_thu_sun_and_fri_mon():
    w = [x for x in candidates(TODAY, TRIPS) if x.kind == "3day"]
    assert Window("3day", date(2026, 11, 5), date(2026, 11, 8), None) in w
    assert Window("3day", date(2026, 11, 6), date(2026, 11, 9), None) in w


def test_long_is_saturday_seven_nights():
    w = [x for x in candidates(TODAY, TRIPS) if x.kind == "long"]
    assert w and all(x.out.weekday() == 5 and (x.ret - x.out).days == 7 for x in w)
    assert min(x.out for x in w) == date(2026, 11, 7)


def test_holiday_tag_on_thanksgiving_3day():
    w = candidates(TODAY, TRIPS)
    tg = Window("3day", date(2026, 11, 26), date(2026, 11, 29), "Thanksgiving")
    assert tg in w


def test_turned_off_type_gives_nothing():
    trips = {**TRIPS, "long": {**TRIPS["long"], "on": False}}
    assert not [x for x in candidates(TODAY, trips) if x.kind == "long"]


def test_window_id():
    assert Window("weekend", date(2026, 11, 13), date(2026, 11, 15), None).id == "weekend:2026-11-13:2026-11-15"


FRI = Window("weekend", date(2026, 11, 13), date(2026, 11, 15), None)


def test_blocker_inside_buffer_blocks_friday_departure():
    assert not is_free(FRI, [ev(datetime(2026, 11, 13, 14, tzinfo=TZ), datetime(2026, 11, 13, 15, tzinfo=TZ))])


def test_blocker_before_buffer_is_fine():
    assert is_free(FRI, [ev(datetime(2026, 11, 13, 12, tzinfo=TZ), datetime(2026, 11, 13, 13, tzinfo=TZ))])


def test_all_day_saturday_blocks():
    assert not is_free(FRI, [ev(datetime(2026, 11, 14, tzinfo=TZ), datetime(2026, 11, 15, tzinfo=TZ), True)])


def test_monday_morning_after_return_is_fine():
    assert is_free(FRI, [ev(datetime(2026, 11, 16, 8, tzinfo=TZ), datetime(2026, 11, 16, 9, tzinfo=TZ))])
