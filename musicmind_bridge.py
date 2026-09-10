"""
Player -- optional read-only bridge into MusicMind's plex_music_brain.db.

Fully optional: if config.MUSICMIND_DB_PATH isn't set or the file
isn't reachable, every function here falls back to Player's own
live-Plex search/mood-bucket code with no degraded functionality.

POOL_SIZE governs how many results get built and cached per query --
a page is then sliced from this pool via result_cache.paged(), rather
than each page triggering its own rebuild.
"""
import os
import sqlite3
import random

import config
import plex_client
import result_cache

POOL_SIZE = 200


def is_available():
    path = getattr(config, "MUSICMIND_DB_PATH", "")
    return bool(path) and os.path.exists(path)


def _connect():
    return sqlite3.connect(f"file:{config.MUSICMIND_DB_PATH}?mode=ro", uri=True)


def _row_to_track_dict(row):
    try:
        rating_key = int(row["rating_key"])
    except (TypeError, ValueError):
        return None
    duration_ms = row["duration_ms"] if row["duration_ms"] is not None else 0
    return {
        "rating_key": rating_key,
        "title": row["title"],
        "artist": row["artist"],
        "album": row["album"],
        "duration_sec": int(duration_ms / 1000),
    }


def _musicmind_search(query, limit=POOL_SIZE):
    q_like = f"%{query.lower()}%"
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        artist_rows = conn.execute(
            "SELECT rating_key, title, artist, album, duration_ms "
            "FROM tracks WHERE LOWER(artist) LIKE ?",
            (q_like,),
        ).fetchall()
        title_rows = conn.execute(
            "SELECT rating_key, title, artist, album, duration_ms "
            "FROM tracks WHERE LOWER(title) LIKE ?",
            (q_like,),
        ).fetchall()
    finally:
        conn.close()

    results = []
    seen = set()
    for row in list(artist_rows) + list(title_rows):
        d = _row_to_track_dict(row)
        if d and d["rating_key"] not in seen:
            seen.add(d["rating_key"])
            results.append(d)
    return results[:limit]


def _build_search_pool(query):
    if is_available():
        try:
            results = _musicmind_search(query, limit=POOL_SIZE)
            if results:
                return results
        except Exception:
            pass
    return plex_client.search_tracks(query, limit=POOL_SIZE)


def search_tracks_page(query, offset=0, limit=20):
    cache_key = ("search", query.lower())
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = _build_search_pool(query)
        result_cache.cache_set(cache_key, pool)
    return result_cache.paged(pool, offset, limit)


def _mood_pool_from_musicmind(mood_key, pool_size=POOL_SIZE):
    keywords = plex_client.MOOD_BUCKETS.get(mood_key.lower(), [mood_key.lower()])

    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        like_clauses = " OR ".join(["LOWER(tag) LIKE ?"] * len(keywords))
        params = [f"%{kw.lower()}%" for kw in keywords]
        tag_rows = conn.execute(
            f"SELECT DISTINCT rating_key FROM track_tags WHERE {like_clauses}",
            params,
        ).fetchall()

        matched_keys = [row["rating_key"] for row in tag_rows]
        if not matched_keys:
            return []

        placeholders = ",".join("?" * len(matched_keys))
        track_rows = conn.execute(
            "SELECT rating_key, title, artist, album, duration_ms "
            f"FROM tracks WHERE rating_key IN ({placeholders})",
            matched_keys,
        ).fetchall()
    finally:
        conn.close()

    pool = [d for d in (_row_to_track_dict(r) for r in track_rows) if d]
    random.shuffle(pool)
    return pool[:pool_size]


def _build_mood_pool(mood_key, instrumental_only):
    pool = []
    if is_available():
        try:
            pool = _mood_pool_from_musicmind(mood_key, pool_size=POOL_SIZE)
        except Exception:
            pool = []

    if not pool:
        pool = plex_client.tracks_by_mood(mood_key, limit=POOL_SIZE)

    if instrumental_only and is_available() and pool:
        pool = _filter_instrumental(pool)

    return pool


def tracks_by_mood_page(mood_key, offset=0, limit=20, instrumental_only=False):
    cache_key = ("mood", mood_key.lower(), instrumental_only)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = _build_mood_pool(mood_key, instrumental_only)
        result_cache.cache_set(cache_key, pool, ttl=result_cache._MOOD_CACHE_TTL)
    return result_cache.paged(pool, offset, limit)


def _filter_instrumental(tracks):
    rating_keys = [str(t["rating_key"]) for t in tracks]
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in rating_keys)
        rows = conn.execute(
            f"SELECT rating_key FROM tracks "
            f"WHERE rating_key IN ({placeholders}) AND is_instrumental = 1",
            rating_keys,
        ).fetchall()
        conn.close()
        instrumental_keys = {str(row["rating_key"]) for row in rows}
    except Exception:
        return tracks
    return [t for t in tracks if str(t["rating_key"]) in instrumental_keys]


# --- Track browsing --------------------------------------------------------

def _all_tracks_from_musicmind():
    """Fast path: every track directly from MusicMind's own table, no
    filter. Only selects columns already proven to exist elsewhere in
    this file (rating_key/title/artist/album/duration_ms) -- no
    assumption about an added_at-style column that's never actually
    been queried anywhere in this codebase."""
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT rating_key, title, artist, album, duration_ms FROM tracks"
        ).fetchall()
    finally:
        conn.close()
    return [d for d in (_row_to_track_dict(r) for r in rows) if d]


def _build_track_browse_pool():
    """Prefer MusicMind (a local SQLite table scan, fast even for a
    large library), fall back to live Plex on any failure or if
    MusicMind isn't configured."""
    if is_available():
        try:
            pool = _all_tracks_from_musicmind()
            if pool:
                return pool
        except Exception:
            pass
    return plex_client.list_all_tracks()


_TRACK_SORTS = {
    "title": lambda t: t["title"].lower(),
    "artist": lambda t: (t["artist"].lower(), t["title"].lower()),
    "album": lambda t: (t["album"].lower(), t["title"].lower()),
}


def browse_tracks_page(offset=0, limit=48, sort="title"):
    """Cached, paginated, sorted track browse. One cached pool serves
    every sort order (sorting an already-fetched in-memory list is
    cheap), same pattern as library_browse.py's artist/album pools."""
    cache_key = ("browse_tracks",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = _build_track_browse_pool()
        result_cache.cache_set(cache_key, pool, ttl=result_cache._MOOD_CACHE_TTL)
    sort_key = _TRACK_SORTS.get(sort, _TRACK_SORTS["title"])
    sorted_pool = sorted(pool, key=sort_key)
    return result_cache.paged(sorted_pool, offset, limit)


def track_letter_offset(letter):
    """Powers the A-Z quickbar for Browse Tracks. Only meaningful for
    the default title sort -- see result_cache.offset_for_letter()'s
    own docstring for why."""
    cache_key = ("browse_tracks",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = _build_track_browse_pool()
        result_cache.cache_set(cache_key, pool, ttl=result_cache._MOOD_CACHE_TTL)
    sorted_pool = sorted(pool, key=_TRACK_SORTS["title"])
    return result_cache.offset_for_letter(sorted_pool, lambda t: t["title"], letter)


# --- Album search ------------------------------------------------------

def search_albums(query, limit=8):
    """Fast album search: match against MusicMind's own track-level
    album/artist columns (grouped so one representative track stands
    in per album), then resolve each MATCHED album's real Plex rating
    key via a single targeted fetchItem() call per match -- NOT a full
    library-wide album walk. At most `limit` such targeted calls, not
    thousands.

    Returns None (caller falls back to the live-Plex full walk) if
    MusicMind isn't available or anything here fails -- this is a
    pure speed optimization, never a hard dependency."""
    if not is_available():
        return None

    q_like = f"%{query.lower()}%"
    try:
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT album, artist, MIN(rating_key) AS sample_rating_key "
                "FROM tracks WHERE LOWER(album) LIKE ? "
                "GROUP BY album, artist LIMIT ?",
                (q_like, limit),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return None

    results = []
    try:
        plex = plex_client.get_plex()
    except Exception:
        return None

    for row in rows:
        try:
            sample_track = plex.fetchItem(int(row["sample_rating_key"]))
            results.append({
                "content_ref": sample_track.parentRatingKey,
                "title": row["album"],
                "subtitle": row["artist"],
            })
        except Exception:
            # This one album's sample track is gone/stale in MusicMind's
            # snapshot -- skip just this result, not the whole search.
            continue
    return results


def search_tracks_for_share(query, limit=8):
    """Fast track search for Share Mode -- reuses the same proven
    _musicmind_search() Player's own search already relies on, just
    reshaped to the {content_ref, title, subtitle} shape Share's
    picker expects instead of the fuller track-dict shape.

    Genuinely fixes a correctness bug, not just speed: Plex's own
    title__icontains filter (used by the live-Plex fallback in
    search_content()) was confirmed NOT matching real, existing
    multi-word titles -- "Les Fleurs" by Minnie Riperton, verified
    directly to exist in MusicMind's own database, never appeared in
    live-Plex search results for that exact query. MusicMind's literal
    SQL LIKE match doesn't share whatever tokenization quirk Plex's API
    has for multi-word phrases.

    Returns None (caller falls back to the live-Plex path) if
    MusicMind isn't available -- this is a speed AND correctness
    improvement, never a hard dependency."""
    if not is_available():
        return None
    try:
        tracks = _musicmind_search(query, limit=limit)
    except Exception:
        return None
    return [
        {
            "content_ref": t["rating_key"],
            "title": t["title"],
            "subtitle": t["artist"],
        }
        for t in tracks
    ]


def search_albums_for_player(query, limit=5):
    """Fast album search for Player's own main search box -- same
    approach as search_albums() (match locally against MusicMind's
    track-level album/artist columns, grouped, then resolve each
    match's real Plex rating key via a targeted fetchItem() call), but
    returns the {rating_key, title, artist, year} shape Browse's own
    albumTile() renderer expects, rather than Share's
    {content_ref, title, subtitle} shape. Kept as a separate function
    rather than generalizing search_albums() itself -- that one is
    proven and tested for Share; safer not to touch it for this.

    Deliberately small limit (5, not search_albums()'s 8) -- this is a
    "top album matches" section above the main track results, not a
    paginated list of its own.

    Returns None (caller falls back to no albums shown -- the main
    live-Plex-backed track search still works either way) if MusicMind
    isn't available or anything here fails."""
    if not is_available():
        return None

    q_like = f"%{query.lower()}%"
    try:
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT album, artist, year, MIN(rating_key) AS sample_rating_key "
                "FROM tracks WHERE LOWER(album) LIKE ? "
                "GROUP BY album, artist LIMIT ?",
                (q_like, limit),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return None

    results = []
    try:
        plex = plex_client.get_plex()
    except Exception:
        return None

    for row in rows:
        try:
            sample_track = plex.fetchItem(int(row["sample_rating_key"]))
            results.append({
                "rating_key": sample_track.parentRatingKey,
                "title": row["album"],
                "artist": row["artist"],
                "year": row["year"],
            })
        except Exception:
            continue
    return results
