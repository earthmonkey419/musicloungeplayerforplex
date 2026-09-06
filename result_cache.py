"""
Player -- in-process TTL cache for search/mood result pools.

Ported from RiderMusic's proven implementation. Exists because
building a mood-bucket pool from live Plex means one query per
matching genre tag -- RiderMusic measured a broad bucket like "rock"
taking ~25 seconds cold on a real library (60+ sequential Plex
queries). Without caching, every mood-pill tap would pay that cost
again.

NOTE: this is a plain in-process dict, assumes a single gunicorn
worker (mlplayer's ecosystem.config.cjs runs it that way).
"""
import time

_RESULT_CACHE = {}
_CACHE_TTL = 600          # seconds -- search results
_MOOD_CACHE_TTL = 3600    # seconds -- mood pools are expensive to
                          # rebuild and don't depend on who's asking.


def cache_set(key, results, ttl=_CACHE_TTL):
    _RESULT_CACHE[key] = (time.time(), results, ttl)
    _evict_stale()


def cache_get(key):
    entry = _RESULT_CACHE.get(key)
    if not entry:
        return None
    ts, results, ttl = entry
    if time.time() - ts > ttl:
        _RESULT_CACHE.pop(key, None)
        return None
    return results


def _evict_stale():
    now = time.time()
    stale = [k for k, (ts, _, ttl) in _RESULT_CACHE.items() if now - ts > ttl]
    for k in stale:
        _RESULT_CACHE.pop(k, None)


def paged(all_results, offset, limit):
    page = all_results[offset:offset + limit]
    has_more = (offset + limit) < len(all_results)
    return {
        "results": page,
        "has_more": has_more,
        "next_offset": offset + len(page),
    }
