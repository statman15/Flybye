"""Firestore: settings, AI labels, prices, searches spent, alerts, suggestions, devices. The only module that talks to it."""
import hashlib
import json
import os
from datetime import datetime, timedelta

from .windows import TZ


def label_id(key):
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def blocks(label):
    """The block that counts: the app's override if there is one, else the AI's call."""
    return label["block"] if label.get("override") is None else label["override"]


def connect():
    import firebase_admin
    from firebase_admin import credentials, firestore
    firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SA"])))
    return Store(firestore.client())


class Store:
    def __init__(self, fs, now=lambda: datetime.now(TZ)):
        self.fs, self.now = fs, now

    def _get(self, col, id, default):
        s = self.fs.collection(col).document(id).get()
        return s.to_dict() if s.exists else default

    def _set(self, col, id, data, merge=False):
        self.fs.collection(col).document(id).set(data, merge=merge)

    def settings(self, seed):
        """The app edits settings/main; the first run seeds it from config.yaml."""
        s = self._get("settings", "main", None)
        if s is None:
            self._set("settings", "main", seed)
            return seed
        return s

    def labels_get(self, keys):
        got = {k: self._get("labels", label_id(k), None) for k in keys}
        return {k: v for k, v in got.items() if v is not None}

    def labels_put(self, key, fields):
        self._set("labels", label_id(key), {"key": key, **fields}, merge=True)

    def labels_since(self, since):
        return sorted((s.to_dict() for s in self.fs.collection("labels").stream() if s.to_dict()["at"] > since),
                      key=lambda l: l["at"])

    def budget(self, month):
        b = self._get("meta", "budget", {"month": month, "used": 0, "last": {}})
        return b if b["month"] == month else {**b, "month": month, "used": 0}

    def log_search(self, window_id):
        now = self.now()
        b = self.budget(f"{now:%Y-%m}")
        cutoff = (now - timedelta(days=60)).isoformat(timespec="seconds")
        last = {k: v for k, v in b["last"].items() if v >= cutoff}
        last[window_id] = now.isoformat(timespec="seconds")
        self._set("meta", "budget", {"month": b["month"], "used": b["used"] + 1, "last": last})

    def route_prices(self, code, kind):
        return self._get("routes", f"{code}_{kind}", {"prices": []})["prices"]

    def add_prices(self, rows, seen):
        by_route = {}
        for r in rows:
            by_route.setdefault((r["code"], r["kind"]), []).append({"seen": seen, "window_id": r["window_id"], "price": r["price"]})
        for (code, kind), new in by_route.items():
            self._set("routes", f"{code}_{kind}", {"prices": (self.route_prices(code, kind) + new)[-60:]})
        by_window = {}
        for r in rows:
            by_window.setdefault(r["window_id"], []).append(r)
        for w, rs in by_window.items():
            self._set("latest", w, {"seen": seen, "rows": rs})

    def latest_rows(self, window_ids, since):
        out = []
        for w in window_ids:
            d = self._get("latest", w, None)
            if d and d["seen"] >= since:
                out += d["rows"]
        return out

    def alerts(self):
        return self._get("meta", "alerts", {"sent": []})["sent"]

    def add_alert(self, a):
        self._set("meta", "alerts", {"sent": (self.alerts() + [a])[-100:]})

    def summary_last(self):
        return self._get("meta", "summary", {"last": ""})["last"]

    def set_summary_last(self, iso):
        self._set("meta", "summary", {"last": iso})

    def write_suggestions(self, doc):
        self._set("suggestions", "current", doc)

    def device_tokens(self):
        return [s.id for s in self.fs.collection("devices").stream()]

    def drop_token(self, token):
        self.fs.collection("devices").document(token).delete()
