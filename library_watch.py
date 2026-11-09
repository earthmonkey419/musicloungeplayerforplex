"""
Player -- keeps cached library data in step with Plex and MusicMind.

Player caches the library in several places (Browse artist/album pools,
the artist-search list, search/mood/track-browse pools). Left alone they
only catch up after a TTL, which made newly scanned music take an hour or
more to appear. This module watches for the library actually changing and
refreshes those caches right then:

  * Plex: every LIBRARY_WATCH_INTERVAL seconds, three cheap requests (track
    count, album count, newest album). When they differ from last time, the
    Browse pools are rebuilt in the background and the other caches dropped.
  * MusicMind: the same idea against musicmind.db (track count + highest
    rowid), so a finished ingest shows up in search / moods / track browse
    within a minute. Tag, play-count and analysis updates don't change
    those numbers, so a long-running analysis won't keep clearing caches.

The last Plex signature is saved next to the pool files, so a restart that
reloads old pools from disk notices they are stale and refreshes them.

Settings -> "Refresh library now" calls refresh_now() for the cases this
can't see (re-tagged or edited items, or a change made while Plex was
unreachable). Set LIBRARY_WATCH_INTERVAL = 0 in config.py to disable the
background watcher (the manual button still works).
"""
import json
import os
import threading
import time

import config
import library_browse
import musicmind_bridge
import plex_client
import result_cache

_SIG_PATH = os.path.join(library_browse._DISK_DIR, "library_signature.json")

_LOCK = threading.Lock()
_STARTED = False
_SIGS = {"plex": None, "mm": None}   # last-seen signatures (watcher + manual refresh share these)
_STATE = {
    "last_check": None,       # epoch of the last successful Plex poll
    "last_plex_change": None,
    "last_musicmind_change": None,
    "last_refresh": None,     # last time caches were refreshed, for any reason
    "last_reason": "",
    "last_error": "",
}


def interval():
    try:
        return max(0, int(getattr(config, "LIBRARY_WATCH_INTERVAL", 60)))
    except (TypeError, ValueError):
        return 60


# --- signatures ---------------------------------------------------------

def plex_signature():
    """Cheap fingerprint of the Plex music library: how many tracks and
    albums, and which album was added most recently. Counts come from
    zero-size queries, so this is light even on a large library."""
    section = plex_client.get_music_section()
    tracks = section.totalViewSize(libtype="track", includeCollections=False)
    albums = section.totalViewSize(libtype="album", includeCollections=False)
    newest = section.search(libtype="album", sort="addedAt:desc", maxresults=1, container_size=1)
    newest_sig = [newest[0].ratingKey, str(newest[0].addedAt)] if newest else None
    return [tracks, albums, newest_sig]


def musicmind_signature():
    if not musicmind_bridge.is_available():
        return None
    conn = musicmind_bridge._connect()
    try:
        row = conn.execute("SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM tracks").fetchone()
        return [row[0], row[1]]
    finally:
        conn.close()


def _load_saved_signature():
    try:
        with open(_SIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("plex")
    except Exception:
        return None


def _save_signature(sig):
    try:
        os.makedirs(os.path.dirname(_SIG_PATH), exist_ok=True)
        tmp = _SIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"plex": sig}, f)
        os.replace(tmp, _SIG_PATH)
    except Exception:
        pass  # persistence is a bonus, never a requirement


# --- refreshing ---------------------------------------------------------

def _refresh_plex_caches():
    plex_client.clear_artist_cache()
    result_cache.clear()
    library_browse.refresh_all()


def _refresh_musicmind_caches():
    result_cache.clear()


def refresh_now():
    """Manual refresh from Settings. Browse pools rebuild in the
    background; everything else is simply dropped and refetched on use."""
    _refresh_plex_caches()
    now = time.time()
    with _LOCK:
        _STATE["last_refresh"] = now
        _STATE["last_reason"] = "manual refresh"
    # Re-baseline so the watcher doesn't immediately "discover" the same change.
    try:
        sig = plex_signature()
        _save_signature(sig)
        with _LOCK:
            _SIGS["plex"] = sig
    except Exception:
        pass
    try:
        mm = musicmind_signature()
        if mm is not None:
            with _LOCK:
                _SIGS["mm"] = mm
    except Exception:
        pass


def status():
    with _LOCK:
        out = dict(_STATE)
    out["interval"] = interval()
    out["enabled"] = interval() > 0
    out["musicmind"] = musicmind_bridge.is_available()
    out["rebuilding"] = library_browse.is_refreshing()
    return out


# --- background watcher -------------------------------------------------

def _poll_once():
    """One pass against the last-seen signatures. Plex and MusicMind
    are checked independently so one being down doesn't hide changes
    in the other."""
    state = _SIGS
    try:
        sig = plex_signature()
        with _LOCK:
            _STATE["last_check"] = time.time()
            _STATE["last_error"] = ""
        prev = state["plex"]
        if prev is not None and sig != prev:
            _refresh_plex_caches()
            now = time.time()
            with _LOCK:
                _STATE["last_plex_change"] = now
                _STATE["last_refresh"] = now
                _STATE["last_reason"] = "Plex library changed"
        if sig != prev:
            _save_signature(sig)
        state["plex"] = sig
    except Exception as e:
        with _LOCK:
            _STATE["last_error"] = f"Plex check failed: {type(e).__name__}"

    try:
        mm = musicmind_signature()
        prev = state["mm"]
        if mm is not None and prev is not None and mm != prev:
            _refresh_musicmind_caches()
            now = time.time()
            with _LOCK:
                _STATE["last_musicmind_change"] = now
                _STATE["last_refresh"] = now
                _STATE["last_reason"] = "MusicMind updated"
        if mm is not None:
            state["mm"] = mm
    except Exception:
        pass  # MusicMind briefly locked or mid-write: try again next pass


def _loop():
    saved = _load_saved_signature()
    _SIGS["plex"] = saved
    first = True
    while True:
        _poll_once()
        if first:
            first = False
            if saved is None and _SIGS["plex"] is not None:
                # No record of what the pools were built from (first run
                # of this version): rebuild once so they are known-fresh.
                _refresh_plex_caches()
                with _LOCK:
                    _STATE["last_refresh"] = time.time()
                    _STATE["last_reason"] = "startup"
        time.sleep(max(15, interval()))


def start():
    """Start the watcher thread once per process (no-op if disabled)."""
    global _STARTED
    if interval() <= 0:
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    threading.Thread(target=_loop, name="library-watch", daemon=True).start()
