"""Who may fetch /stream/<key> and /art/<key>.

Before this, both routes answered anyone who could reach the app, so a
visitor could walk rating keys and pull the whole library through the
proxy. Access is now limited to:

  * the host (admin session) -- everything
  * a guest in a live Room -- cover art only (guests never stream audio;
    the host's device plays it)
  * a share recipient -- only tracks (and cover art) that belong to a live
    share they have opened. Opening /linked/<token> grants that share to
    the browser session; the grant is re-checked against the shares table
    on every request, so expiry and "End this link" take effect at once.
  * the shared item's own cover (/art/<content_ref> of a live share) is
    public, because share emails and link previews fetch it with no
    session.

One deliberate softening: when a share expires mid-listen, a track the
browser had already started streaming may finish (and be seeked) for
SHARE_EXPIRY_GRACE_MINUTES after expiry, so a song never cuts off halfway.
No track the browser hadn't already requested can start, and a link the
host ENDS has no grace at all.

This is access control, not DRM: someone who can play a track can always
capture it. What it removes is anonymous library access and casual
"navigate to the URL and save" downloads.
"""
import threading
import time

from flask import request, session

import db
import plex_client

_GRANTS_KEY = "share_tokens"
_PLAYING_KEY = "share_playing"   # [[token, rating_key], ...]: tracks this browser recently streamed from a live share
_MAX_PLAYING = 3
_MAX_GRANTS = 5            # session cookie is small; keep the newest few
_KEYS_TTL = 600            # seconds a share's track list is trusted
_keys_cache = {}           # token -> (timestamp, frozenset of rating keys)
_lock = threading.Lock()

# Sec-Fetch-Dest values that mean "the user navigated to this URL" (as
# opposed to an <audio>/<img> element or fetch()). Missing header (older
# browsers) is allowed.
_NAVIGATION_DESTS = {"document", "iframe", "frame", "embed", "object"}


def is_admin():
    return bool(session.get("is_admin"))


def _guest_in_live_room():
    room_id = session.get("room_id")
    return bool(room_id and db.is_room_live(room_id))


def remember_share(token, content_ref, tracks):
    """Called by the /linked view with the tracks it is about to render, and
    grants that share to this browser session."""
    keys = {str(content_ref)}
    keys.update(str(t["rating_key"]) for t in tracks)
    with _lock:
        _keys_cache[token] = (time.time(), frozenset(keys))
    grants = [t for t in session.get(_GRANTS_KEY, []) if t != token]
    grants.append(token)
    session[_GRANTS_KEY] = grants[-_MAX_GRANTS:]


def _share_keys(token):
    with _lock:
        hit = _keys_cache.get(token)
    if hit and time.time() - hit[0] < _KEYS_TTL:
        return hit[1]
    share = db.get_share(token)
    if not share:
        return frozenset()
    keys = {str(share["content_ref"])}
    try:
        _, _, tracks = plex_client.get_content_tracks(share["content_type"], share["content_ref"])
        keys.update(str(t["rating_key"]) for t in tracks)
    except Exception:
        pass  # Plex unreachable: fall back to the shared item itself
    keys = frozenset(keys)
    with _lock:
        _keys_cache[token] = (time.time(), keys)
    return keys


def _remember_playing(token, key):
    """Note the tracks this browser has streamed from a live share, so the
    grace window knows what may finish. Keeps the last few (the track
    playing plus the one the gapless engine preloads behind it). Written
    only when it changes, so range requests on one track don't re-issue the
    session cookie."""
    pair = [token, key]
    playing = [p for p in session.get(_PLAYING_KEY, []) if isinstance(p, list) and len(p) == 2]
    if pair in playing:
        return
    playing.append(pair)
    session[_PLAYING_KEY] = playing[-_MAX_PLAYING:]


def _in_progress_track_allows(key):
    """Grace: an expired (never revoked) share still lets a track this
    browser had already started streaming finish."""
    for token, playing_key in (p for p in session.get(_PLAYING_KEY, []) if isinstance(p, list) and len(p) == 2):
        if playing_key != key or token not in session.get(_GRANTS_KEY, []):
            continue
        if db.is_share_in_grace(token) and key in _share_keys(token):
            return True
    return False


def _granted_share_allows(rating_key, streaming=False):
    key = str(rating_key)
    for token in session.get(_GRANTS_KEY, []):
        if db.is_share_live(token) and key in _share_keys(token):
            if streaming:
                _remember_playing(token, key)
            return True
    return _in_progress_track_allows(key)


def can_view_art(rating_key):
    if is_admin() or _guest_in_live_room():
        return True
    if _granted_share_allows(rating_key):
        return True
    return db.has_live_share_for_ref(rating_key)


def can_stream(rating_key):
    if is_admin():
        return True
    if request.headers.get("Sec-Fetch-Dest", "").lower() in _NAVIGATION_DESTS:
        return False
    return _granted_share_allows(rating_key, streaming=True)
