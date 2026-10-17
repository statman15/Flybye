"""Ask an AI which calendar events really stop us leaving town. Cached per event; the app's override wins."""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

from .store import blocks

PROMPT = """These are events from Chris and Laura's shared calendar. For each one, decide whether it means they \
can't be away on a trip at that time (block=true): work commitments, travel, appointments, events they'd attend, \
hosting, anything hard to move. Not blockers (block=false): reminders, birthdays without a party, bills, holidays \
and observances, chores, TV, things marked "free" that are just notes. When unsure, block.
Answer ONLY a JSON array: [{"i": <index>, "block": true|false, "why": "<5 words>"}]

"""


def http_chat(provider, messages):
    req = urllib.request.Request(provider["url"].rstrip("/") + "/chat/completions", method="POST",
                                 data=json.dumps({"model": provider["model"], "messages": messages}).encode(),
                                 headers={"Authorization": f"Bearer {provider.get('key') or os.environ[provider['key_env']]}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _parse(text):
    return json.loads(re.search(r"\[.*\]", text, re.S).group(0))


def _line(i, e):
    when = e.start.strftime("%a %b %d") + ("" if e.all_day else e.start.strftime(" %H:%M") + e.end.strftime("-%H:%M"))
    return f'{i}. "{e.title}" {when}{" (all day)" if e.all_day else ""}{" (marked free)" if e.free else ""}'


def _ask(batch, cfg, chat):
    msg = [{"role": "user", "content": PROMPT + "\n".join(_line(i, e) for i, e in enumerate(batch))}]
    errors = []
    for p in cfg.get("ai", []):
        try:
            return {a["i"]: a for a in _parse(chat(p, msg))}, p["name"]
        except Exception as e:  # provider down, key missing or unreadable answer: try the next one
            errors.append(f"{p['name']}: {e!r}")
    print(f"AI labels failed, treating {len(batch)} events as busy: {errors}", file=sys.stderr)
    return {}, None


def label_events(events, st, cfg, chat=http_chat):
    first = {}  # one label per "<uid>|<title>", dated by its next occurrence
    for e in events:
        k = f"{e.uid}|{e.title}"
        if k not in first or e.start < first[k].start:
            first[k] = e
    have = st.labels_get(list(first))
    out, todo = {}, []
    for key, e in first.items():
        if key in have:
            out[key] = blocks(have[key])  # the app's override beats the AI
            if have[key].get("start") != e.start.isoformat():
                st.labels_put(key, {"start": e.start.isoformat()})
        else:
            todo.append((key, e))
    now = datetime.now().isoformat(timespec="seconds")
    for n in range(0, len(todo), 40):
        batch = todo[n:n + 40]
        answers, src = _ask([e for _, e in batch], cfg, chat)
        for i, (key, e) in enumerate(batch):
            a = answers.get(i)
            out[key] = bool(a["block"]) if a else True  # no answer: assume busy, ask again next run
            if a:
                st.labels_put(key, {"title": e.title, "start": e.start.isoformat(), "all_day": e.all_day,
                                    "block": bool(a["block"]), "why": str(a.get("why", "")), "src": src, "at": now,
                                    "override": None})
    return out
