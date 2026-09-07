"""
MusicLounge Player -- DB initialization.

Run once: python3 init_db.py

Room/Share/password-reset/config tables are vendored unchanged from
musiclounge's init_db.py. playlists/playlist_tracks are new, added
for Player's native + Plex-synced playlist model. See
MUSICLOUNGE-PLAYER-V1-SCOPE.md.
"""
import sqlite3
import config

conn = sqlite3.connect(config.DB_PATH)
c = conn.cursor()

# ---------------------------------------------------------------
# Mode A: Room (launched from Player, unchanged from musiclounge)
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS room_sessions (
    session_id      TEXT PRIMARY KEY,
    room_name        TEXT,
    join_code        TEXT,
    started_at       TEXT,
    expires_at       TEXT,
    ended_by_admin   INTEGER DEFAULT 0,
    device_count     INTEGER DEFAULT 0,
    now_playing_ref     TEXT,
    now_playing_title   TEXT,
    now_playing_artist  TEXT,
    now_playing_duration INTEGER,
    position_sec        INTEGER DEFAULT 0,
    is_playing           INTEGER DEFAULT 0,
    volume                INTEGER DEFAULT 80,
    last_skip_at           TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS room_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    position        INTEGER,
    track_ref       TEXT,
    title           TEXT,
    artist          TEXT,
    duration_sec    INTEGER,
    added_at        TEXT,
    played          INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES room_sessions(session_id)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS room_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    action_type     TEXT,
    detail          TEXT,
    ts              TEXT,
    FOREIGN KEY (session_id) REFERENCES room_sessions(session_id)
)
""")

# ---------------------------------------------------------------
# Mode B: Share (/linked) -- launched from Player, unchanged
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS shares (
    share_token       TEXT PRIMARY KEY,
    content_type      TEXT,
    content_ref       TEXT,
    content_title     TEXT,
    content_artist    TEXT,
    created_at        TEXT,
    expires_at        TEXT,
    duration_hours    INTEGER,
    delivery_method   TEXT,
    recipient_email   TEXT,
    from_display_name TEXT,
    revoked           INTEGER DEFAULT 0,
    access_count      INTEGER DEFAULT 0,
    last_accessed_at  TEXT
)
""")

# ---------------------------------------------------------------
# Password reset tokens -- unchanged
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS password_resets (
    token       TEXT PRIMARY KEY,
    created_at  TEXT,
    expires_at  TEXT,
    used        INTEGER DEFAULT 0
)
""")

# ---------------------------------------------------------------
# Shared config -- unchanged (also holds DB-backed admin password hash)
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS config (
    key     TEXT PRIMARY KEY,
    value   TEXT
)
""")

# ---------------------------------------------------------------
# Player: playlists (NEW)
#
# source='native'      -- created/edited in Player, owned by us
# source='plex_synced'  -- read-only mirror of an existing Plex
#                          playlist, plex_ref holds its rating_key,
#                          refreshed on view
# exported_ref          -- Plex rating_key of our last export for a
#                          native playlist, NULL until first export.
#                          Lets plex_export.py verify ownership before
#                          ever overwriting a same-named Plex playlist.
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS playlists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('native', 'plex_synced')),
    plex_ref        TEXT,
    exported_ref    TEXT,
    created_at      TEXT,
    updated_at      TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id     INTEGER NOT NULL,
    position        INTEGER NOT NULL,
    track_ref       TEXT NOT NULL,
    title           TEXT,
    artist          TEXT,
    duration_sec    INTEGER,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
)
""")

# ---------------------------------------------------------------
# Player: play_history (NEW)
#
# One row per "real" play -- logged client-side by
# static/js/play-history.js once a track crosses a listened-duration
# threshold (30s or half the track, whichever is smaller), so a quick
# accidental skip never counts as a play. Only wired up on Player's
# own pages (home, playlist detail) -- deliberately NOT on Room Mode
# (driven by guests' choices, not the admin's own listening) or
# /linked (a share recipient's own session on their own device, not
# the admin's history to pollute).
# ---------------------------------------------------------------

c.execute("""
CREATE TABLE IF NOT EXISTS play_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    track_ref       TEXT NOT NULL,
    title           TEXT,
    artist          TEXT,
    played_at       TEXT NOT NULL
)
""")

conn.commit()
conn.close()
print(f"MusicLounge Player DB initialized at {config.DB_PATH}")
