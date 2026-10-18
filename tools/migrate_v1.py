"""One-time move of the v1 Firestore data (top-level settings, labels, ...) into a v2 space.

    python tools/migrate_v1.py --owner someone@example.com      (or OWNER_EMAIL=...; needs FIREBASE_SA)

Reads SERPAPI_KEY, GEMINI_KEY and ICAL_URL from the environment into the space's private/keys. Copies everything,
checks every copy reads back equal, and only then deletes the v1 docs. Safe to run twice. Prints counts only."""
import argparse
import os
import secrets
import sys
from datetime import datetime, timezone

V1 = ["settings", "labels", "suggestions", "latest", "routes", "meta", "devices"]


def _fix(col, data):
    """Emails are stored lowercase in v2."""
    return {**data, "email": data["email"].lower()} if col == "devices" and data.get("email") else data


def migrate(fs, owner, env=os.environ, new_sid=lambda: secrets.token_hex(8), name="Chris & Laura"):
    owner = owner.strip().lower()
    for s in fs.collection("spaces").stream():
        if s.to_dict().get("owner") == owner:
            return "A space for this owner already exists: nothing to do (already migrated)."
    allowed = [s.id.lower() for s in fs.collection("allow").stream()]
    sid = new_sid()
    space = fs.collection("spaces").document(sid)
    copied = []
    for col in V1:
        for s in fs.collection(col).stream():
            data = _fix(col, s.to_dict())
            space.collection(col).document(s.id).set(data)
            copied.append((col, s.id, data))
    keys = {k: env[e] for k, e in (("serpapi", "SERPAPI_KEY"), ("gemini", "GEMINI_KEY")) if env.get(e)}
    keys["calendars"] = [{"name": "Calendar", "url": env["ICAL_URL"]}] if env.get("ICAL_URL") else []
    space.collection("private").document("keys").set(keys)
    copied.append(("private", "keys", keys))
    for col, id, data in copied:
        if space.collection(col).document(id).get().to_dict() != data:
            raise RuntimeError(f"copy of {col} did not read back equal: nothing deleted")
    space.set({"name": name, "owner": owner, "members": sorted({owner, *allowed}), "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    fs.collection("admins").document(owner).set({})
    old = [(col, id) for col, id, _ in copied if col in V1] + [("allow", s.id) for s in fs.collection("allow").stream()]
    for col, id in old:
        fs.collection(col).document(id).delete()
    return f"Migrated {len(old)} docs into one space and removed the v1 copies."


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--owner", default=os.environ.get("OWNER_EMAIL"))
    a = p.parse_args()
    if not a.owner:
        sys.exit("Give the owner's email with --owner or OWNER_EMAIL.")
    from flybye import store
    print(migrate(store.connect(), a.owner))
