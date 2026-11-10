"""
Room Mode DB helpers. Short join codes here (not the long/random
share tokens) are intentional and match the scope doc's reasoning:
room codes are host-supervised and short-lived, same class of
guardrail as RiderMusic's 4-digit code -- a different security profile
than the unattended, 24-72hr /linked tokens in share.py.
"""
import sqlite3
import random
import string
import secrets
import uuid
import json
from datetime import datetime, timedelta

import config


def get_db():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.utcnow().isoformat()


def _gen_join_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# --- Sessions ---------------------------------------------------------

def create_room(room_name):
    conn = get_db()
    conn.execute("UPDATE room_sessions SET ended_by_admin = 1 WHERE ended_by_admin = 0")

    session_id = str(uuid.uuid4())
    join_code = _gen_join_code()
    started_at = _now()
    expires_at = (datetime.utcnow() + timedelta(minutes=config.ROOM_SESSION_TIMEOUT_MINUTES)).isoformat()
    conn.execute(
        """INSERT INTO room_sessions
           (session_id, room_name, join_code, started_at, expires_at, volume)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, room_name, join_code, started_at, expires_at, config.ROOM_VOLUME_CEILING),
    )
    conn.commit()
    conn.close()
    return session_id


def get_active_room():
    """The one active room, if any -- ended_by_admin=0 is the only
    thing that matters here. v1 assumes a single concurrent room per
    instance, matching RiderMusic.

    Deliberately does NOT filter on expires_at: a room that's simply
    outlived its idle timeout but was never explicitly ended must
    still be reachable from the dashboard -- otherwise a party running
    longer than ROOM_SESSION_TIMEOUT_MINUTES becomes a "stranded"
    room the admin can see exists (via /admin/stats) but can never
    get back to or end. See also touch_room(), which extends
    expires_at on real activity so a genuinely active room rarely
    hits this wall in the first place -- expiry still matters for
    guest-facing actions (is_room_live()), just not for whether the
    admin can find their own room."""
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM room_sessions
           WHERE ended_by_admin = 0
           ORDER BY started_at DESC LIMIT 1""",
    ).fetchone()
    conn.close()
    return row


def touch_room(session_id):
    """Extends a room's expires_at from now -- a sliding idle timeout
    instead of a fixed one. Called on every real guest/admin action
    (join, skip, playpause, queue-add, volume) so a room only expires
    after genuine inactivity, not just elapsed wall-clock time. This
    is what stops a long-running party from silently going stale
    mid-use."""
    new_expiry = (datetime.utcnow() + timedelta(minutes=config.ROOM_SESSION_TIMEOUT_MINUTES)).isoformat()
    conn = get_db()
    conn.execute("UPDATE room_sessions SET expires_at = ? WHERE session_id = ?", (new_expiry, session_id))
    conn.commit()
    conn.close()


def get_room(session_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM room_sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row


def get_room_by_code(join_code):
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM room_sessions
           WHERE join_code = ? AND ended_by_admin = 0 AND expires_at > ?""",
        (join_code.upper(), _now()),
    ).fetchone()
    conn.close()
    return row


def end_room(session_id):
    conn = get_db()
    conn.execute("UPDATE room_sessions SET ended_by_admin = 1 WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def bump_device_count(session_id):
    conn = get_db()
    conn.execute("UPDATE room_sessions SET device_count = device_count + 1 WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def set_now_playing(session_id, track, start_playing=True):
    """`track` must be the plex_client._track_to_dict() shape: keys
    rating_key/title/artist/duration_sec. If you have a room_queue row
    instead (different column names -- track_ref, not rating_key), pass
    it through queue_row_to_track() first.

    `start_playing` controls whether this promotion also flips
    is_playing to true. Defaults to True, matching skip's existing
    behavior (skipping to the next track should keep audio going).
    Pass start_playing=False when a track is being promoted to
    now_playing with no explicit host play action behind it -- a
    guest's first queue add, or Send to Room populating an empty
    room -- so it doesn't silently start real audio unattended."""
    conn = get_db()
    conn.execute(
        """UPDATE room_sessions SET
           now_playing_ref = ?, now_playing_title = ?, now_playing_artist = ?,
           now_playing_duration = ?, position_sec = 0, is_playing = ?
           WHERE session_id = ?""",
        (track["rating_key"], track["title"], track["artist"], track["duration_sec"],
         1 if start_playing else 0, session_id),
    )
    conn.commit()
    conn.close()


def queue_row_to_track(row):
    """room_queue rows use different column names (track_ref, not
    rating_key) than plex_client._track_to_dict()'s output. This bridges
    the two shapes -- use this, not a bare dict(row), before passing a
    popped queue row into set_now_playing()."""
    return {
        "rating_key": row["track_ref"],
        "title": row["title"],
        "artist": row["artist"],
        "duration_sec": row["duration_sec"],
    }


def set_play_state(session_id, is_playing):
    conn = get_db()
    conn.execute("UPDATE room_sessions SET is_playing = ? WHERE session_id = ?", (1 if is_playing else 0, session_id))
    conn.commit()
    conn.close()


def set_volume(session_id, volume):
    clamped = max(0, min(volume, config.ROOM_VOLUME_CEILING))
    conn = get_db()
    conn.execute("UPDATE room_sessions SET volume = ? WHERE session_id = ?", (clamped, session_id))
    conn.commit()
    conn.close()
    return clamped


def can_skip(session_id):
    room = get_room(session_id)
    if not room or not room["last_skip_at"]:
        return True
    last = datetime.fromisoformat(room["last_skip_at"])
    return (datetime.utcnow() - last).total_seconds() >= config.ROOM_SKIP_RATE_LIMIT_SECONDS


def record_skip(session_id):
    conn = get_db()
    conn.execute("UPDATE room_sessions SET last_skip_at = ? WHERE session_id = ?", (_now(), session_id))
    conn.commit()
    conn.close()


# --- Queue --------------------------------------------------------------

def is_room_live(session_id):
    """A room existing isn't enough -- it must also be un-ended and
    un-expired. Guest API endpoints need this check explicitly: the
    guest_required decorator only confirms a room_id is *present* in
    the session, not that it's still the currently active room."""
    room = get_room(session_id)
    if not room:
        return False
    if room["ended_by_admin"]:
        return False
    if room["expires_at"] <= _now():
        return False
    return True


def queue_count(session_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM room_queue WHERE session_id = ? AND played = 0", (session_id,)
    ).fetchone()
    conn.close()
    return row["n"]


def add_to_queue(session_id, track):
    conn = get_db()
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), 0) as m FROM room_queue WHERE session_id = ?", (session_id,)
    ).fetchone()["m"]
    conn.execute(
        """INSERT INTO room_queue
           (session_id, position, track_ref, title, artist, duration_sec, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, max_pos + 1, track["rating_key"], track["title"], track["artist"],
         track["duration_sec"], _now()),
    )
    conn.commit()
    conn.close()


def get_queue(session_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM room_queue WHERE session_id = ? AND played = 0
           ORDER BY position ASC""",
        (session_id,),
    ).fetchall()
    conn.close()
    return rows


def pop_next(session_id):
    """Marks the earliest un-played queue item as played and returns it,
    or None if the queue is empty."""
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM room_queue WHERE session_id = ? AND played = 0
           ORDER BY position ASC LIMIT 1""",
        (session_id,),
    ).fetchone()
    if row:
        conn.execute("UPDATE room_queue SET played = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()
    return row


def remove_from_queue(session_id, queue_id):
    """Host removes a not-yet-played track from this room's queue. Scoped by
    session_id so one room can never remove another room's rows, and by
    played = 0 so it can't touch history. Returns True if a row was removed."""
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM room_queue WHERE id = ? AND session_id = ? AND played = 0",
        (queue_id, session_id),
    )
    conn.commit()
    removed = cur.rowcount > 0
    conn.close()
    return removed


# --- Actions log ----------------------------------------------------------

def log_action(session_id, action_type, detail=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO room_actions (session_id, action_type, detail, ts) VALUES (?, ?, ?, ?)",
        (session_id, action_type, detail, _now()),
    )
    conn.commit()
    conn.close()


# --- Share Mode (/linked) -------------------------------------------------

def create_share(content_type, content_ref, content_title, content_artist, duration_hours):
    """Mints a share as a DB row -- long random token, expiry set at
    creation time from the fixed 24/48/72hr set. Per the scope doc:
    a DB row rather than a signed token, because it's free (same
    pattern as room_sessions) and keeps revocation possible."""
    token = secrets.token_urlsafe(config.SHARE_TOKEN_BYTES)
    created_at = _now()
    expires_at = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO shares
           (share_token, content_type, content_ref, content_title, content_artist,
            created_at, expires_at, duration_hours)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (token, content_type, content_ref, content_title, content_artist,
         created_at, expires_at, duration_hours),
    )
    conn.commit()
    conn.close()
    return token


def get_share(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM shares WHERE share_token = ?", (token,)).fetchone()
    conn.close()
    return row


def revoke_share(token):
    conn = get_db()
    conn.execute("UPDATE shares SET revoked = 1 WHERE share_token = ?", (token,))
    conn.commit()
    conn.close()


def is_share_live(token):
    """A share existing isn't enough -- must also be un-revoked and
    un-expired. Never distinguish 'expired' from 'never existed' to
    callers -- both should just look like 404, per the scope doc's
    security reasoning."""
    row = get_share(token)
    if not row:
        return False
    if row["revoked"]:
        return False
    if row["expires_at"] <= _now():
        return False
    return True


def has_live_share_for_ref(content_ref):
    """True if some un-revoked, un-expired share is for this exact item.
    Lets that item's cover art be fetched without a session (share emails
    and link previews load it anonymously)."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM shares WHERE content_ref = ? AND revoked = 0 AND expires_at > ? LIMIT 1",
        (str(content_ref), _now()),
    ).fetchone()
    conn.close()
    return row is not None


# --- Share expiry: grace, renewal, and the expired page --------------------
#
# Every share link always has an expiry; nothing here can make one
# permanent. Renewing never pushes the end further than "now + one of the
# configured durations", so a link can be kept going but only ever in
# short, deliberate steps by the host.

_EXPIRED_PAGE_DAYS = 30      # how long after expiry the friendly page still names the share


def share_grace_seconds():
    """How long past expiry the ONE track a visitor was already streaming may
    finish (seek/range requests included). New tracks never start. 0 = no
    grace. Read lazily so an older config.py without the setting works."""
    return max(0, int(getattr(config, "SHARE_EXPIRY_GRACE_MINUTES", 10) or 0)) * 60


def share_state(token):
    """'live' | 'expired' | 'revoked' | 'missing'. For the HOST side and the
    expired page only -- never for anything that must not distinguish
    expired from nonexistent."""
    row = get_share(token)
    if not row:
        return "missing"
    if row["revoked"]:
        return "revoked"
    if row["expires_at"] <= _now():
        return "expired"
    return "live"


def is_share_in_grace(token):
    """True while an un-revoked share is past expiry but still inside the
    grace window. Used only to let an already-started track finish."""
    row = get_share(token)
    if not row or row["revoked"]:
        return False
    now = datetime.utcnow()
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        return False
    return expires <= now < expires + timedelta(seconds=share_grace_seconds())


def renew_share(token, hours):
    """Host action: give a live or expired share more time, keeping its URL
    and all of its activity. Returns the new expires_at, or None if the
    share is missing or was ended on purpose (revoked links stay ended --
    make a new link instead). The new expiry is now + hours, but never
    earlier than the current one, so renewing can't shorten a link and can't
    stack time beyond one preset from today."""
    row = get_share(token)
    if not row or row["revoked"]:
        return None
    now = datetime.utcnow()
    candidate = now + timedelta(hours=hours)
    try:
        current = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        current = now
    new_expiry = max(candidate, current).isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE shares SET expires_at = ?, archived_at = NULL, renewed_at = ?, "
        "renew_count = COALESCE(renew_count, 0) + 1, renewal_requested_at = NULL "
        "WHERE share_token = ?",
        (new_expiry, now.isoformat(), token),
    )
    conn.commit()
    conn.close()
    return new_expiry


def request_share_renewal(token):
    """Recipient action from the expired page: flags the share so the host
    sees 'asked for more time'. Only works on a share that expired on its
    own (never a revoked one) within the last _EXPIRED_PAGE_DAYS days, and
    is idempotent -- a second tap changes nothing. Carries no message from
    the visitor. Returns True if the share is flagged (now or already)."""
    row = get_share(token)
    if not row or row["revoked"] or row["expires_at"] > _now():
        return False
    if not expired_page_visible(row):
        return False
    if "renewal_requested_at" not in row.keys():
        return False                      # migrate_share_renew.py not run yet
    if row["renewal_requested_at"]:
        return True
    conn = get_db()
    conn.execute(
        "UPDATE shares SET renewal_requested_at = ? WHERE share_token = ? AND renewal_requested_at IS NULL",
        (_now(), token),
    )
    conn.commit()
    conn.close()
    return True


def expired_page_visible(row):
    """Whether an expired share is recent enough for the friendly page to
    name it. Older links look like any unknown link."""
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        return False
    return datetime.utcnow() - expires <= timedelta(days=_EXPIRED_PAGE_DAYS)


def record_share_access(token):
    conn = get_db()
    conn.execute(
        "UPDATE shares SET access_count = access_count + 1, last_accessed_at = ? WHERE share_token = ?",
        (_now(), token),
    )
    conn.commit()
    conn.close()


def mark_share_delivery(token, method, recipient_email=None, from_display_name=None):
    conn = get_db()
    conn.execute(
        "UPDATE shares SET delivery_method = ?, recipient_email = ?, from_display_name = ? WHERE share_token = ?",
        (method, recipient_email, from_display_name, token),
    )
    conn.commit()
    conn.close()


# --- Share activity (share_events) -----------------------------------------

import hashlib
import hmac
import re

SHARE_EVENT_TYPES = ("open", "play_start", "play_complete")
# 0 / unset = keep history forever. Read lazily so an existing config.py
# without the setting keeps working.
def _retention_days():
    return int(getattr(config, "SHARE_EVENT_RETENTION_DAYS", 0) or 0)
_OPEN_DEDUPE_MINUTES = 30        # one "open" per visitor per half hour
_PLAY_DEDUPE_SECONDS = 20        # same visitor+track+type inside this = repeat beacon
_MAX_EVENTS_PER_MINUTE = 60      # per visitor per share; beyond this is noise or abuse
_MAX_EVENTS_PER_SHARE = 20000    # hard cap so a runaway client cannot grow the DB

# Link-preview fetchers, crawlers and scripted clients. Previews must still
# get the page (og: tags), they just never count as a listener.
_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|facebot|whatsapp|"
    r"telegram|discord|slack|skype|linkedin|pinterest|embedly|quora|"
    r"applebot|google-?read-?aloud|headless|curl|wget|python-requests|"
    r"httpx|aiohttp|go-http-client|okhttp|java/|libwww|postman",
    re.I,
)


def is_bot_user_agent(user_agent):
    """Empty UA counts as a bot: every real browser sends one."""
    if not user_agent:
        return True
    return bool(_BOT_RE.search(user_agent))


def classify_device(user_agent):
    """Deliberately coarse -- enough to tell phone from desktop, no more."""
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "iphone" in ua or "ipod" in ua or ("android" in ua and "mobile" in ua):
        return "phone"
    if "android" in ua:
        return "tablet"
    if "windows" in ua or "macintosh" in ua or "x11" in ua or "cros" in ua:
        return "desktop"
    return "other"


def referrer_host(referrer):
    """Host only, lowercased, no path or query (those can carry tokens).
    Returns '' for no/garbage referrer and 'direct' is applied at display."""
    if not referrer:
        return ""
    # Hostname characters only: this value comes from the visitor's browser
    # and is later shown on the admin page, so never store anything else.
    m = re.match(r"^[a-z][a-z0-9+.-]*://([a-z0-9.-]+)(?:[/:?#]|$)", referrer.strip(), re.I)
    return m.group(1).lower()[:80] if m else ""


def visitor_hash(visitor_id, share_token):
    """HMAC of the random per-browser id with the share token, keyed by the
    app secret. Stable within one share, unlinkable across shares, and
    useless without SECRET_KEY."""
    key = (config.SECRET_KEY or "").encode()
    msg = f"{visitor_id}|{share_token}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]


def record_share_event(share_token, event_type, vhash, track_ref=None,
                       device=None, referrer=None, track_title=None):
    """Inserts one event unless it is a repeat or over a limit. Returns True
    if a row was written. Never raises for 'expected' rejections."""
    if event_type not in SHARE_EVENT_TYPES:
        return False
    now = datetime.utcnow()
    conn = get_db()
    try:
        recent = conn.execute(
            "SELECT COUNT(*) FROM share_events WHERE share_token = ? AND visitor_hash = ? AND ts > ?",
            (share_token, vhash, (now - timedelta(minutes=1)).isoformat()),
        ).fetchone()[0]
        if recent >= _MAX_EVENTS_PER_MINUTE:
            return False
        total = conn.execute(
            "SELECT COUNT(*) FROM share_events WHERE share_token = ?", (share_token,)
        ).fetchone()[0]
        if total >= _MAX_EVENTS_PER_SHARE:
            return False

        if event_type == "open":
            window = (now - timedelta(minutes=_OPEN_DEDUPE_MINUTES)).isoformat()
            dup = conn.execute(
                "SELECT 1 FROM share_events WHERE share_token = ? AND visitor_hash = ? "
                "AND event_type = 'open' AND ts > ? LIMIT 1",
                (share_token, vhash, window),
            ).fetchone()
        else:
            window = (now - timedelta(seconds=_PLAY_DEDUPE_SECONDS)).isoformat()
            dup = conn.execute(
                "SELECT 1 FROM share_events WHERE share_token = ? AND visitor_hash = ? "
                "AND event_type = ? AND track_ref = ? AND ts > ? LIMIT 1",
                (share_token, vhash, event_type, track_ref, window),
            ).fetchone()
        if dup:
            return False

        conn.execute(
            "INSERT INTO share_events (share_token, event_type, ts, visitor_hash, track_ref, "
            "track_title, device, referrer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (share_token, event_type, now.isoformat(), vhash, track_ref,
             (track_title or None) and track_title[:200], device, referrer or None),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_share_activity(share_token):
    """Everything the host Activity panel needs for one share. All counts
    come from share_events; a share with no events returns zeros."""
    conn = get_db()
    try:
        ev = lambda t: conn.execute(
            "SELECT COUNT(*) FROM share_events WHERE share_token = ? AND event_type = ?",
            (share_token, t),
        ).fetchone()[0]
        opens = ev("open")
        plays_started = ev("play_start")
        plays_completed = ev("play_complete")

        row = conn.execute(
            "SELECT COUNT(DISTINCT visitor_hash), MIN(ts), MAX(ts) FROM share_events "
            "WHERE share_token = ? AND event_type = 'open'",
            (share_token,),
        ).fetchone()
        unique_visitors, first_open, last_open = row[0], row[1], row[2]

        listeners = conn.execute(
            "SELECT COUNT(DISTINCT visitor_hash) FROM share_events "
            "WHERE share_token = ? AND event_type IN ('play_start', 'play_complete')",
            (share_token,),
        ).fetchone()[0]

        per_track = [
            dict(r) for r in conn.execute(
                "SELECT track_ref, MAX(track_title) AS title, "
                "SUM(event_type = 'play_start') AS started, "
                "SUM(event_type = 'play_complete') AS completed "
                "FROM share_events WHERE share_token = ? AND track_ref IS NOT NULL "
                "GROUP BY track_ref ORDER BY started DESC",
                (share_token,),
            )
        ]
        devices = {
            r[0] or "other": r[1] for r in conn.execute(
                "SELECT device, COUNT(*) FROM share_events "
                "WHERE share_token = ? AND event_type = 'open' GROUP BY device",
                (share_token,),
            )
        }
        referrers = {
            (r[0] or "direct"): r[1] for r in conn.execute(
                "SELECT referrer, COUNT(*) FROM share_events "
                "WHERE share_token = ? AND event_type = 'open' GROUP BY referrer "
                "ORDER BY COUNT(*) DESC",
                (share_token,),
            )
        }
        # Hourly buckets (UTC, 'YYYY-MM-DDTHH'), for a sparkline.
        timeline = [
            {"hour": r[0], "opens": r[1], "plays": r[2]} for r in conn.execute(
                "SELECT substr(ts, 1, 13), "
                "SUM(event_type = 'open'), SUM(event_type = 'play_start') "
                "FROM share_events WHERE share_token = ? GROUP BY substr(ts, 1, 13) "
                "ORDER BY 1",
                (share_token,),
            )
        ]
        return {
            "opens": opens,
            "unique_visitors": unique_visitors,
            "listeners": listeners,
            "plays_started": plays_started,
            "plays_completed": plays_completed,
            "first_open": first_open,
            "last_open": last_open,
            "per_track": per_track,
            "devices": devices,
            "referrers": referrers,
            "timeline": timeline,
        }
    finally:
        conn.close()


def get_share_activity_summaries(tokens):
    """{token: {opens, unique_visitors, listeners, plays_started,
    plays_completed}} for many shares in one query -- the stats table
    uses this instead of one query per row."""
    tokens = list(tokens)
    if not tokens:
        return {}
    out = {t: {"opens": 0, "unique_visitors": 0, "listeners": 0,
               "plays_started": 0, "plays_completed": 0} for t in tokens}
    conn = get_db()
    try:
        for i in range(0, len(tokens), 400):          # stay under SQLite's variable limit
            chunk = tokens[i:i + 400]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(
                "SELECT share_token, "
                "SUM(event_type = 'open'), "
                "COUNT(DISTINCT CASE WHEN event_type = 'open' THEN visitor_hash END), "
                "COUNT(DISTINCT CASE WHEN event_type IN ('play_start', 'play_complete') THEN visitor_hash END), "
                "SUM(event_type = 'play_start'), SUM(event_type = 'play_complete') "
                f"FROM share_events WHERE share_token IN ({marks}) GROUP BY share_token",
                chunk,
            ):
                out[r[0]] = {"opens": r[1] or 0, "unique_visitors": r[2] or 0,
                             "listeners": r[3] or 0, "plays_started": r[4] or 0,
                             "plays_completed": r[5] or 0}
    finally:
        conn.close()
    return out


def archive_finished_shares():
    """'Clear expired/revoked' -- hides finished links from the default
    list but keeps the share row and ALL of its activity. Live links are
    never touched. Returns how many were archived."""
    now = _now()
    conn = get_db()
    cur = conn.execute(
        "UPDATE shares SET archived_at = ? WHERE archived_at IS NULL "
        "AND (revoked = 1 OR expires_at <= ?)",
        (now, now),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def set_share_archived(token, archived):
    conn = get_db()
    conn.execute(
        "UPDATE shares SET archived_at = ? WHERE share_token = ?",
        (_now() if archived else None, token),
    )
    conn.commit()
    conn.close()


def delete_share_permanently(token):
    """The only path that destroys share history. Refuses a live link
    (end it first). Returns True if something was deleted."""
    if is_share_live(token):
        return False
    conn = get_db()
    conn.execute("DELETE FROM share_events WHERE share_token = ?", (token,))
    cur = conn.execute("DELETE FROM shares WHERE share_token = ?", (token,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n > 0


def prune_share_events(days=None):
    """Optional retention. Does nothing unless a positive number of days
    is passed or SHARE_EVENT_RETENTION_DAYS is set -- history is kept
    forever by default. Returns rows deleted."""
    days = _retention_days() if days is None else days
    if days <= 0:
        return 0
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = get_db()
    cur = conn.execute("DELETE FROM share_events WHERE ts < ?", (cutoff,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


# --- Admin password (DB-backed, seeded once from config.py) ---------------
#
# config.ADMIN_PASSWORD only matters on the very first login after this
# feature is deployed: that first check bootstrap-hashes it into this
# table, and from then on the DATABASE is the source of truth, not the
# config file/env var. This is what makes an in-app password reset
# possible at all -- a value that only lives in a file the app can't
# rewrite at runtime (Docker env vars especially) can never be changed
# by the app itself. Once bootstrapped, editing config.py's
# ADMIN_PASSWORD after the fact has no further effect; use the reset
# flow (or clear the stored hash from the config table) to change it
# going forward.

def get_config_value(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_config_value(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def verify_admin_password(password):
    from werkzeug.security import generate_password_hash, check_password_hash
    import config

    stored_hash = get_config_value("admin_password_hash")
    if stored_hash is None:
        stored_hash = generate_password_hash(config.ADMIN_PASSWORD)
        set_config_value("admin_password_hash", stored_hash)
    return check_password_hash(stored_hash, password)


def set_admin_password(new_password):
    from werkzeug.security import generate_password_hash
    set_config_value("admin_password_hash", generate_password_hash(new_password))


# --- Password reset tokens -------------------------------------------------

def create_password_reset():
    """Mints a reset token, 30-minute expiry. Long/random, same
    security posture as share tokens."""
    token = secrets.token_urlsafe(32)
    created_at = _now()
    expires_at = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO password_resets (token, created_at, expires_at, used) VALUES (?, ?, ?, 0)",
        (token, created_at, expires_at),
    )
    conn.commit()
    conn.close()
    return token


def is_password_reset_valid(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM password_resets WHERE token = ?", (token,)).fetchone()
    conn.close()
    if not row:
        return False
    if row["used"]:
        return False
    if row["expires_at"] <= _now():
        return False
    return True


def use_password_reset(token):
    conn = get_db()
    conn.execute("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# --- Playlists (native + plex_synced) -- new for Player -------------------

def create_playlist(name, source="native"):
    now = _now()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO playlists (name, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, source, now, now),
    )
    playlist_id = cur.lastrowid
    conn.commit()
    conn.close()
    return playlist_id


def get_playlist(playlist_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    conn.close()
    return row


def list_playlists():
    conn = get_db()
    rows = conn.execute("SELECT * FROM playlists ORDER BY updated_at DESC").fetchall()
    conn.close()
    return rows


def rename_playlist(playlist_id, name):
    conn = get_db()
    conn.execute(
        "UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now(), playlist_id),
    )
    conn.commit()
    conn.close()


def delete_playlist(playlist_id):
    conn = get_db()
    conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
    conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    conn.commit()
    conn.close()


def get_playlist_tracks(playlist_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM playlist_tracks WHERE playlist_id = ? ORDER BY position ASC",
        (playlist_id,),
    ).fetchall()
    conn.close()
    return rows


def replace_playlist_tracks(playlist_id, tracks):
    """Overwrites a playlist's full track list in one shot -- used by
    both manual reordering and Plex-synced refresh. `tracks` is a
    list of plex_client._track_to_dict()-shaped dicts, already in the
    desired order."""
    conn = get_db()
    conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
    for i, t in enumerate(tracks):
        conn.execute(
            """INSERT INTO playlist_tracks
               (playlist_id, position, track_ref, title, artist, duration_sec)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (playlist_id, i, t["rating_key"], t["title"], t["artist"], t["duration_sec"]),
        )
    conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (_now(), playlist_id))
    conn.commit()
    conn.close()


def add_track_to_playlist(playlist_id, track):
    """Appends one track to a native playlist -- the common case
    (search result -> 'add to playlist')."""
    conn = get_db()
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) as m FROM playlist_tracks WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()["m"]
    conn.execute(
        """INSERT INTO playlist_tracks
           (playlist_id, position, track_ref, title, artist, duration_sec)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (playlist_id, max_pos + 1, track["rating_key"], track["title"], track["artist"], track["duration_sec"]),
    )
    conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (_now(), playlist_id))
    conn.commit()
    conn.close()


def add_tracks_to_playlist(playlist_id, tracks):
    """Bulk-appends multiple tracks to a native playlist in one
    connection -- powers 'add this whole album to a playlist' from the
    shared Room/Share popover. Avoids looping add_track_to_playlist()
    N times, which would mean N separate connections and N live Plex
    lookups for one action. Computes the starting position once, then
    inserts every track from there. Same defensive normalization
    responsibility as _send_tracks_to_room(): callers may pass
    DOM-sourced track dicts missing duration_sec, so default to 0
    rather than raising a KeyError."""
    conn = get_db()
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) as m FROM playlist_tracks WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()["m"]
    for i, t in enumerate(tracks):
        conn.execute(
            """INSERT INTO playlist_tracks
               (playlist_id, position, track_ref, title, artist, duration_sec)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (playlist_id, max_pos + 1 + i, t.get("rating_key"),
             t.get("title", "Unknown Title"), t.get("artist", "Unknown Artist"),
             t.get("duration_sec") or 0),
        )
    conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (_now(), playlist_id))
    conn.commit()
    conn.close()


def remove_track_from_playlist(playlist_id, track_row_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM playlist_tracks WHERE id = ? AND playlist_id = ?",
        (track_row_id, playlist_id),
    )
    conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (_now(), playlist_id))
    conn.commit()
    conn.close()


def mark_playlist_exported(playlist_id, plex_ref):
    conn = get_db()
    conn.execute(
        "UPDATE playlists SET exported_ref = ?, updated_at = ? WHERE id = ?",
        (plex_ref, _now(), playlist_id),
    )
    conn.commit()
    conn.close()


# --- Play history (Player's own pages only -- see init_db.py) -------------

def log_play(track):
    """Records one real play. Called client-side once a track crosses
    the listened-duration threshold -- see static/js/play-history.js."""
    conn = get_db()
    conn.execute(
        "INSERT INTO play_history (track_ref, title, artist, played_at) VALUES (?, ?, ?, ?)",
        (str(track["rating_key"]), track.get("title"), track.get("artist"), _now()),
    )
    conn.commit()
    conn.close()


def get_recent_plays(limit=10):
    """Distinct tracks, most recent play first. Dedups by track_ref
    (keeping each track's latest play time) rather than showing the
    same song repeated if it was replayed -- "recently played" reads
    better as variety than as a literal play-by-play log."""
    conn = get_db()
    rows = conn.execute(
        """SELECT track_ref, title, artist, MAX(played_at) as played_at
           FROM play_history
           GROUP BY track_ref
           ORDER BY played_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


# --- Personal queue persistence (Player's own pages only) ------------------
#
# Reuses the existing generic config(key, value) table rather than a
# new schema -- this is a singleton (one admin, one queue), stored as
# one JSON blob under a fixed key. Room Mode's real relational queue
# table is the right design for a multi-device shared queue; Player's
# is just "remember what I had queued so a refresh doesn't lose it,"
# which doesn't need that complexity.

_PLAYER_QUEUE_KEY = "player_queue_state"


def save_player_queue(queue, current_index):
    value = json.dumps({"queue": queue, "current_index": current_index})
    conn = get_db()
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_PLAYER_QUEUE_KEY, value),
    )
    conn.commit()
    conn.close()


def get_player_queue():
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (_PLAYER_QUEUE_KEY,)).fetchone()
    conn.close()
    if not row:
        return {"queue": [], "current_index": -1}
    try:
        data = json.loads(row["value"])
        if not isinstance(data, dict) or not isinstance(data.get("queue"), list):
            return {"queue": [], "current_index": -1}
        return data
    except (ValueError, TypeError):
        return {"queue": [], "current_index": -1}
