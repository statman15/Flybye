"""Ask an AI which calendar events really stop us leaving town. Cached per event; config overrides win."""
import json
import re
import urllib.request
from datetime import datetime

PROMPT = """These are events from Chris and Laura's shared calendar. For each one, decide whether it means they \
can't be away on a trip at that time (block=true): work commitments, travel, appointments, events they'd attend, \
hosting, anything hard to move. Not blockers (block=false): reminders, birthdays without a party, bills, holidays \
and observances, chores, TV, things marked "free" that are just notes. When unsure, block.
Answer ONLY a JSON array: [{"i": <index>, "block": true|false, "why": "<5 words>"}]

"""


def http_chat(provider, messages):
    req = urllib.request.Request(provider["url"].rstrip("/") + "/chat/completions", method="POST",
                                 data=json.dumps({"model": provider["model"], "messages": messages}).encode(),
                                 headers={"Authorization": f"Bearer {provider['key']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _parse(text):
    return json.loads(re.search(r"\[.*\]", text, re.S).group(0))


def _line(i, e):
    when = e.start.strftime("%a %b %d") + ("" if e.all_day else e.start.strftime(" %H:%M") + e.end.strftime("-%H:%M"))
    return f'{i}. "{e.title}" {when}{" (all day)" if e.all_day else ""}{" (marked free)" if e.free else ""}'


def _ask(batch, cfg, chat):
    msg = [{"role": "user", "content": PROMPT + "\n".join(_line(i, e) for i, e in enumerate(batch))}]
    for p in cfg.get("ai", []):
        try:
            return {a["i"]: a for a in _parse(chat(p, msg))}, p["name"]
        except Exception:  # provider down or unreadable answer: try the next one
            continue
    return {}, None


def label_events(events, db, cfg, chat=http_chat):
    over = {k.lower(): v == "block" for k, v in cfg.get("overrides", {}).items()}
    out, todo = {}, {}
    for e in events:
        key = f"{e.uid}|{e.title}"
        if key in out or key in todo:
            continue
        o = over.get(e.uid.lower(), over.get(e.title.lower()))
        row = db.execute("SELECT block FROM labels WHERE key=?", (key,)).fetchone()
        if o is not None:
            out[key] = o
        elif row:
            out[key] = bool(row["block"])
        else:
            todo[key] = e
    items = list(todo.items())
    now = datetime.now().isoformat(timespec="seconds")
    for n in range(0, len(items), 40):
        batch = items[n:n + 40]
        answers, src = _ask([e for _, e in batch], cfg, chat)
        for i, (key, e) in enumerate(batch):
            a = answers.get(i)
            out[key] = bool(a["block"]) if a else True  # no answer: assume busy, ask again next run
            if a:
                db.execute("INSERT OR REPLACE INTO labels VALUES(?,?,?,?,?,?)",
                           (key, e.title, int(bool(a["block"])), str(a.get("why", "")), src, now))
    db.commit()
    return out
