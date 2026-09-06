"""
MusicLounge Player -- config.

Same file-based-or-env-var pattern as musiclounge and ridermusic:
copy to config.py and edit directly, or set every value below as an
environment variable (Docker/Portainer) -- either works, mix and
match if you like.
"""
import os


def _bool(key, default):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(key, default):
    val = os.environ.get(key)
    return int(val) if val is not None else default


def _int_list(key, default):
    val = os.environ.get(key)
    if val is None:
        return default
    return [int(x.strip()) for x in val.split(",") if x.strip()]


# --- Plex ---
PLEX_URL = os.environ.get("PLEX_URL", "http://10.0.0.251:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "REPLACE_ME")
MUSIC_LIB = os.environ.get("MUSIC_LIB", "Music")

# --- Admin ---
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "REPLACE_ME")
ADMIN_RECOVERY_EMAIL = os.environ.get("ADMIN_RECOVERY_EMAIL", "")
COOKIE_SECURE = _bool("COOKIE_SECURE", False)
SECRET_KEY = os.environ.get("SECRET_KEY", "REPLACE_ME_RANDOM")

# --- Server ---
HOST = os.environ.get("HOST", "0.0.0.0")
# NOTE: pick a port not already bound on the NAS -- musiclounge uses
# 8679, ridermusic uses 6869, musicmind uses 8787. Verify before
# deploying (`ss -ltnp` or similar) rather than trusting this default.
PORT = _int("PORT", 8680)

# --- Database ---
DB_PATH = os.environ.get("DB_PATH", "mlplayer.db")

# --- Mode A: Room (launched from Player, same code as musiclounge) ---
ROOM_SESSION_TIMEOUT_MINUTES = _int("ROOM_SESSION_TIMEOUT_MINUTES", 90)
ROOM_VOLUME_CEILING = _int("ROOM_VOLUME_CEILING", 80)
ROOM_SKIP_RATE_LIMIT_SECONDS = _int("ROOM_SKIP_RATE_LIMIT_SECONDS", 20)
ROOM_MAX_QUEUE_ADDS_PER_SESSION = _int("ROOM_MAX_QUEUE_ADDS_PER_SESSION", 50)

# --- Mode B: Share (launched from Player, same code as musiclounge) ---
SHARE_LINK_DURATIONS_HOURS = _int_list("SHARE_LINK_DURATIONS_HOURS", [24, 48, 72])
SHARE_TOKEN_BYTES = _int("SHARE_TOKEN_BYTES", 32)

# --- SMTP (Share Mode "Email It") ---
SMTP_HOST = os.environ.get("SMTP_HOST", "REPLACE_ME")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "REPLACE_ME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "REPLACE_ME")
SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)
SMTP_FROM_ADDRESS = os.environ.get("SMTP_FROM_ADDRESS", "REPLACE_ME")
SMTP_FROM_DISPLAY_NAME = os.environ.get("SMTP_FROM_DISPLAY_NAME", "MusicLounge Player")

# --- Optional: MusicMind read-only bridge ---
# Leave blank to disable entirely -- Player falls back to plain
# genre-tag mood buckets with no degraded functionality. Point this
# at MusicMind's plex_music_brain.db (read-only; Player never writes
# to it) to enable instrumental-only filtering enrichment.
MUSICMIND_DB_PATH = os.environ.get("MUSICMIND_DB_PATH", "")
