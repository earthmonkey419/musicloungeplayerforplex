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
