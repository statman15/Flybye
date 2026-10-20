"""Firestore, one space at a time: everything lives under spaces/{sid}. The only module that talks to it."""
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
    return firestore.client()


class Store:
    def __init__(self, fs, sid, now=lambda: datetime.now(TZ)):
        self.fs, self.sid, self.now = fs, sid, now
        self.space = fs.collection("spaces").document(sid)

    @staticmethod
    def spaces(fs):
        return [s.id for s in fs.collection("spaces").stream()]

    def _col(self, col):
        return self.space.collection(col)

    def _get(self, col, id, default):
        s = self._col(col).document(id).get()
        return s.to_dict() if s.exists else default

    def _set(self, col, id, data, merge=False):
        self._col(col).document(id).set(data, merge=merge)

    def keys(self):
        """The space's own SerpApi and Gemini keys and its calendar links."""
        return self._get("private", "keys", {})

    def activity(self):
        return self._get("meta", "activity", {})

    def set_activity(self, doc):
        self._set("meta", "activity", doc)

    def climate(self, code, mm):
        """Typical weather for a city and month; shared by all spaces, so it lives at the top."""
        s = self.fs.collection("climate").document(f"{code}_{mm}").get()
        return s.to_dict() if s.exists else None

    def set_climate(self, code, mm, doc):
        self.fs.collection("climate").document(f"{code}_{mm}").set(doc)

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
        return sorted((s.to_dict() for s in self._col("labels").stream() if s.to_dict()["at"] > since),
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

    def latest_ids(self):
        # ponytail: lists every stored window (old ones too); prune latest/ if this gets slow
        return [s.id for s in self._col("latest").stream()]

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
        """Tokens of current members only: someone removed from the space stops getting its pushes (and their token goes)."""
        snap = self.space.get()
        members = {m.lower() for m in (snap.to_dict() or {}).get("members", [])} if snap.exists else None
        keep = []
        for d in self._col("devices").stream():
            email = ((d.to_dict() or {}).get("email") or "").lower()
            if members is not None and email not in members:
                self.drop_token(d.id)
            else:
                keep.append(d.id)
        return keep

    def drop_token(self, token):
        self._col("devices").document(token).delete()
