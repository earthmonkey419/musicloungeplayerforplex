"""One-off migration (run after migrate_share_archive.py): adds the columns
behind share-link renewal -- shares.renewed_at, shares.renew_count and
shares.renewal_requested_at. Safe to run more than once.

    python3 migrate_share_renew.py
"""
import sqlite3

import config

conn = sqlite3.connect(config.DB_PATH)


def cols(table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


have = cols("shares")
if "renewed_at" not in have:
    conn.execute("ALTER TABLE shares ADD COLUMN renewed_at TEXT")
    print("Added shares.renewed_at")
if "renew_count" not in have:
    conn.execute("ALTER TABLE shares ADD COLUMN renew_count INTEGER DEFAULT 0")
    print("Added shares.renew_count")
if "renewal_requested_at" not in have:
    conn.execute("ALTER TABLE shares ADD COLUMN renewal_requested_at TEXT")
    print("Added shares.renewal_requested_at")
conn.commit()
print(f"Share renewal columns ready in {config.DB_PATH}")
conn.close()
