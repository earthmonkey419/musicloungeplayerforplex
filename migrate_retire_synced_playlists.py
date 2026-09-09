"""
One-time cleanup: Playlists page no longer requires an explicit
"import from Plex" step -- every Plex playlist is now automatically
listed and viewable directly (see plex_client.list_all_playlists()).
The old source='plex_synced' DB rows that tracked which playlists had
been explicitly imported are now redundant -- the same Plex playlists
show up automatically either way. Safe to run every startup: once
these rows are gone, this is a no-op.
"""
import sqlite3
import config

conn = sqlite3.connect(config.DB_PATH)
synced_ids = [r[0] for r in conn.execute(
    "SELECT id FROM playlists WHERE source = 'plex_synced'"
).fetchall()]

if not synced_ids:
    print("No plex_synced playlists to retire.")
else:
    placeholders = ",".join("?" * len(synced_ids))
    conn.execute(f"DELETE FROM playlist_tracks WHERE playlist_id IN ({placeholders})", synced_ids)
    conn.execute(f"DELETE FROM playlists WHERE id IN ({placeholders})", synced_ids)
    conn.commit()
    print(f"Retired {len(synced_ids)} plex_synced playlist(s) -- their Plex "
          f"originals are untouched and will still show up automatically.")

conn.close()
