import importlib.util
import pathlib

import pytest

import fakefs
from fakefs import FakeFS

spec = importlib.util.spec_from_file_location("migrate_v1", pathlib.Path(__file__).parents[2] / "tools" / "migrate_v1.py")
migrate_v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_v1)

OWNER = "Owner@Example.com"
ENV = {"SERPAPI_KEY": "sk", "GEMINI_KEY": "gk", "ICAL_URL": "https://cal.test/secret.ics"}
V1 = {"settings/main": {"home": "ORD"}, "labels/l1": {"key": "u|A", "block": True, "override": None},
      "suggestions/current": {"updated": "t", "windows": [], "top": []}, "latest/w1": {"seen": "2026-10-01", "rows": [{"code": "DEN"}]},
      "routes/DEN_weekend": {"prices": [{"price": 1}]}, "meta/budget": {"month": "2026-10", "used": 5, "last": {}},
      "meta/alerts": {"sent": []}, "meta/summary": {"last": ""}, "devices/tok1": {"platform": "web", "email": "Laura@Example.com"},
      "allow/owner@example.com": {}, "allow/partner@example.com": {}}


def v1_fs():
    fs = FakeFS()
    fs.data.update({k: dict(v) for k, v in V1.items()})
    return fs


def run(fs):
    return migrate_v1.migrate(fs, OWNER, env=ENV, new_sid=lambda: "sid1")


def test_copies_every_collection_into_one_space_then_removes_the_v1_docs():
    fs = v1_fs()
    run(fs)
    for path, doc in V1.items():
        col = path.split("/")[0]
        if col != "allow":
            want = {**doc, "email": doc["email"].lower()} if col == "devices" else doc
            assert fs.data[f"spaces/sid1/{path}"] == want
        assert path not in fs.data
    space = fs.data["spaces/sid1"]
    assert space["name"] == "Chris & Laura" and space["owner"] == "owner@example.com" and space["created"]
    assert space["members"] == ["owner@example.com", "partner@example.com"]
    assert fs.data["spaces/sid1/private/keys"] == {"serpapi": "sk", "gemini": "gk", "calendars": [{"name": "Calendar", "url": ENV["ICAL_URL"]}]}
    assert fs.data["admins/owner@example.com"] == {}


def test_a_second_run_changes_nothing_and_says_so():
    fs = v1_fs()
    run(fs)
    before = {k: dict(v) for k, v in fs.data.items()}
    assert "already" in run(fs)
    assert fs.data == before


def test_nothing_is_deleted_if_a_copy_does_not_read_back_equal(monkeypatch):
    fs = v1_fs()
    real = fakefs.Doc.set

    def flaky(self, data, merge=False):
        real(self, {**data, "block": False} if self.path.endswith("/labels/l1") else data, merge)
    monkeypatch.setattr(fakefs.Doc, "set", flaky)
    with pytest.raises(RuntimeError):
        run(fs)
    assert all(path in fs.data for path in V1) and "spaces/sid1" not in fs.data and "admins/owner@example.com" not in fs.data


def test_missing_secrets_leave_the_keys_empty_not_broken():
    fs = FakeFS()
    migrate_v1.migrate(fs, OWNER, env={}, new_sid=lambda: "sid1")
    assert fs.data["spaces/sid1/private/keys"] == {"calendars": []}
