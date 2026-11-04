"""One-off migration: adds the share_events table (share-link activity
tracking) to an existing database. Safe to run more than once.

    python3 migrate_share_events.py
"""
import sqlite3

import config

conn = sqlite3.connect(config.DB_PATH)
conn.execute("""
CREATE TABLE IF NOT EXISTS share_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    share_token   TEXT NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('open', 'play_start', 'play_complete')),
    ts            TEXT NOT NULL,
    visitor_hash  TEXT NOT NULL,
    track_ref     TEXT,
    device        TEXT,
    referrer      TEXT,
    FOREIGN KEY (share_token) REFERENCES shares(share_token) ON DELETE CASCADE
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_share_events_token_ts ON share_events (share_token, ts)")
conn.commit()
n = conn.execute("SELECT COUNT(*) FROM share_events").fetchone()[0]
print(f"share_events ready in {config.DB_PATH} ({n} rows)")
conn.close()
