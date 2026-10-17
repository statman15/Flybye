"""SQLite: AI labels, every price seen, every search spent, alerts sent, small key/values."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS labels(key TEXT PRIMARY KEY, title TEXT, block INT, why TEXT, src TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS prices(seen TEXT, window_id TEXT, kind TEXT, out TEXT, ret TEXT, code TEXT, name TEXT,
  price REAL, hotel REAL, minutes INT, airline TEXT, stops INT, source TEXT);
CREATE INDEX IF NOT EXISTS prices_code ON prices(code, kind);
CREATE TABLE IF NOT EXISTS searches(at TEXT, engine TEXT, window_id TEXT);
CREATE TABLE IF NOT EXISTS alerts(at TEXT, code TEXT, out TEXT, ret TEXT, price REAL, kind TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def get(db, k, default=None):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def put(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
    db.commit()
