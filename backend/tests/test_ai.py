from datetime import datetime
from zoneinfo import ZoneInfo

from fakefs import new_store
from flybye.ai import label_events
from flybye.cal import Event

TZ = ZoneInfo("America/Chicago")
CFG = {"ai": [{"name": "omni", "url": "u1", "key": "k", "model": "m"},
              {"name": "gem", "url": "u2", "key": "k", "model": "m"}]}


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
    st = new_store()
    chat = FakeChat(['[{"i":0,"block":true,"why":"work trip"}]'])
    assert label_events([ev("a", "Conference")], st, CFG, chat) == {"a|Conference": True}
    assert label_events([ev("a", "Conference")], st, CFG, chat) == {"a|Conference": True}
    assert chat.calls == ["omni"]


def test_override_on_the_label_beats_the_ai_and_skips_it():
    st = new_store()
    st.labels_put("t|Trash day", {"block": True, "override": False})
    st.labels_put("u|Lunch", {"block": False, "override": True})
    chat = FakeChat([])
    got = label_events([ev("t", "Trash day"), ev("u", "Lunch")], st, CFG, chat)
    assert got == {"t|Trash day": False, "u|Lunch": True} and chat.calls == []


def test_new_label_stores_start_and_all_day_and_never_sets_an_override():
    st = new_store()
    label_events([ev("a", "Conference")], st, CFG, FakeChat(['[{"i":0,"block":true,"why":"work trip"}]']))
    d = st.labels_get(["a|Conference"])["a|Conference"]
    assert d["start"] == "2026-11-13T09:00:00-06:00" and d["all_day"] is False
    assert d["block"] is True and d["override"] is None and d["title"] == "Conference" and d["src"] == "omni"


def test_recurring_event_label_start_follows_the_next_occurrence():
    st = new_store()
    chat = FakeChat(['[{"i":0,"block":true,"why":"x"}]'])
    label_events([ev("r", "Volleyball")], st, CFG, chat)
    later = Event("r", "Volleyball", datetime(2026, 11, 20, 9, tzinfo=TZ), datetime(2026, 11, 20, 10, tzinfo=TZ), False, False)
    label_events([later], st, CFG, chat)
    assert st.labels_get(["r|Volleyball"])["r|Volleyball"]["start"].startswith("2026-11-20") and len(chat.calls) == 1


def test_falls_back_to_second_provider():
    st = new_store()
    chat = FakeChat([OSError("down"), '[{"i":0,"block":false,"why":"reminder"}]'])
    assert label_events([ev("b", "Pay rent")], st, CFG, chat) == {"b|Pay rent": False}
    assert chat.calls == ["omni", "gem"]


def test_all_failed_blocks_and_does_not_cache():
    st = new_store()
    chat = FakeChat([OSError(), OSError(), '[{"i":0,"block":false,"why":"x"}]'])
    assert label_events([ev("c", "Mystery")], st, CFG, chat) == {"c|Mystery": True}
    assert label_events([ev("c", "Mystery")], st, CFG, chat) == {"c|Mystery": False}  # retried next run


def test_json_inside_prose_and_fences():
    st = new_store()
    chat = FakeChat(['Sure!\n```json\n[{"i":0,"block":true,"why":"x"},{"i":1,"block":false,"why":"y"}]\n```'])
    got = label_events([ev("d", "Flight to Boston"), ev("e", "Mom bday")], st, CFG, chat)
    assert got == {"d|Flight to Boston": True, "e|Mom bday": False}


def test_missing_answer_blocks():
    st = new_store()
    chat = FakeChat(['[{"i":0,"block":false,"why":"x"}]'])
    got = label_events([ev("f", "One"), ev("g", "Two")], st, CFG, chat)
    assert got == {"f|One": False, "g|Two": True}


def test_same_title_recurring_labelled_once():
    st = new_store()
    chat = FakeChat(['[{"i":0,"block":true,"why":"x"}]'])
    got = label_events([ev("r", "Volleyball"), ev("r", "Volleyball")], st, CFG, chat)
    assert got == {"r|Volleyball": True} and len(chat.calls) == 1


def test_all_providers_failing_is_logged(capsys):
    st = new_store()
    label_events([ev("z", "Thing")], st, CFG, FakeChat([OSError("no key"), OSError("down")]))
    assert "no key" in capsys.readouterr().err
