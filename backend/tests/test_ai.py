from datetime import datetime
from zoneinfo import ZoneInfo

from flybye import db as dbm
from flybye.ai import label_events
from flybye.cal import Event

TZ = ZoneInfo("America/Chicago")
CFG = {"ai": [{"name": "omni", "url": "u1", "key": "k", "model": "m"},
              {"name": "gem", "url": "u2", "key": "k", "model": "m"}],
       "overrides": {"Trash day": "ignore", "uid-force": "block"}}


def ev(uid, title):
    return Event(uid, title, datetime(2026, 11, 13, 9, tzinfo=TZ), datetime(2026, 11, 13, 10, tzinfo=TZ), False, False)


class FakeChat:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, provider, messages):
        self.calls.append(provider["name"])
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def test_labels_are_cached():
    db = dbm.connect(":memory:")
    chat = FakeChat(['[{"i":0,"block":true,"why":"work trip"}]'])
    assert label_events([ev("a", "Conference")], db, CFG, chat) == {"a|Conference": True}
    assert label_events([ev("a", "Conference")], db, CFG, chat) == {"a|Conference": True}
    assert chat.calls == ["omni"]


def test_overrides_skip_the_ai():
    db = dbm.connect(":memory:")
    chat = FakeChat([])
    got = label_events([ev("t", "trash DAY"), ev("uid-force", "Lunch")], db, CFG, chat)
    assert got == {"t|trash DAY": False, "uid-force|Lunch": True} and chat.calls == []


def test_falls_back_to_second_provider():
    db = dbm.connect(":memory:")
    chat = FakeChat([OSError("down"), '[{"i":0,"block":false,"why":"reminder"}]'])
    assert label_events([ev("b", "Pay rent")], db, CFG, chat) == {"b|Pay rent": False}
    assert chat.calls == ["omni", "gem"]


def test_all_failed_blocks_and_does_not_cache():
    db = dbm.connect(":memory:")
    chat = FakeChat([OSError(), OSError(), '[{"i":0,"block":false,"why":"x"}]'])
    assert label_events([ev("c", "Mystery")], db, CFG, chat) == {"c|Mystery": True}
    assert label_events([ev("c", "Mystery")], db, CFG, chat) == {"c|Mystery": False}  # retried next run


def test_json_inside_prose_and_fences():
    db = dbm.connect(":memory:")
    chat = FakeChat(['Sure!\n```json\n[{"i":0,"block":true,"why":"x"},{"i":1,"block":false,"why":"y"}]\n```'])
    got = label_events([ev("d", "Flight to Boston"), ev("e", "Mom bday")], db, CFG, chat)
    assert got == {"d|Flight to Boston": True, "e|Mom bday": False}


def test_missing_answer_blocks():
    db = dbm.connect(":memory:")
    chat = FakeChat(['[{"i":0,"block":false,"why":"x"}]'])
    got = label_events([ev("f", "One"), ev("g", "Two")], db, CFG, chat)
    assert got == {"f|One": False, "g|Two": True}


def test_same_title_recurring_labelled_once():
    db = dbm.connect(":memory:")
    chat = FakeChat(['[{"i":0,"block":true,"why":"x"}]'])
    got = label_events([ev("r", "Volleyball"), ev("r", "Volleyball")], db, CFG, chat)
    assert got == {"r|Volleyball": True} and len(chat.calls) == 1
