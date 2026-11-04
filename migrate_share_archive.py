"""One-off migration (run after migrate_share_events.py): adds
shares.archived_at and share_events.track_title so that clearing old
share links archives them instead of deleting their history.
Safe to run more than once.

    python3 migrate_share_archive.py
"""
import sqlite3

import config

conn = sqlite3.connect(config.DB_PATH)


def cols(table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


if "archived_at" not in cols("shares"):
    conn.execute("ALTER TABLE shares ADD COLUMN archived_at TEXT")
    print("Added shares.archived_at")
if "track_title" not in cols("share_events"):
    conn.execute("ALTER TABLE share_events ADD COLUMN track_title TEXT")
    print("Added share_events.track_title")
conn.commit()
print(f"Share history columns ready in {config.DB_PATH}")
conn.close()
