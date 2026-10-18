from types import SimpleNamespace

from firebase_admin import exceptions, messaging

from fakefs import new_store
from flybye import push


def ok():
    return SimpleNamespace(success=True, exception=None)


def bad(exc):
    return SimpleNamespace(success=False, exception=exc)


def test_send_fans_out_to_every_device_with_data_and_link():
    st = new_store()
    for t in ("a", "b"):
        st._set("devices", t, {"platform": "web"})
    seen = []

    def fan(msgs):
        seen.extend(msgs)
        return SimpleNamespace(responses=[ok() for _ in msgs])
    push.send(st, "Title", "Body", {"window_id": "w", "code": "DEN"}, "https://x.test/#trip=w|DEN", fan)
    assert sorted(m.token for m in seen) == ["a", "b"]
    m = seen[0]
    assert m.notification.title == "Title" and m.notification.body == "Body" and m.data == {"window_id": "w", "code": "DEN"}
    assert m.webpush.fcm_options.link == "https://x.test/#trip=w|DEN"


def test_dead_tokens_are_pruned_but_other_failures_keep_the_device():
    st = new_store()
    for t in ("live", "gone", "junk", "flaky"):
        st._set("devices", t, {"platform": "web"})
    answers = {"live": ok(), "gone": bad(messaging.UnregisteredError("x")),
               "junk": bad(exceptions.InvalidArgumentError("x")), "flaky": bad(exceptions.UnavailableError("x"))}
    push.send(st, "T", "B", fan=lambda msgs: SimpleNamespace(responses=[answers[m.token] for m in msgs]))
    assert sorted(st.device_tokens()) == ["flaky", "junk", "live"]  # InvalidArgument can mean a bad message, not a bad token


def test_no_devices_sends_nothing():
    called = []
    push.send(new_store(), "T", "B", fan=lambda msgs: called.append(msgs))
    assert called == []
