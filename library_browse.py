"""
Player -- library browsing (Artists / Albums / Album -> Tracklist).

Only the top-level artist/album lists need caching/pagination --
walking the whole library on every page load would be slow. Building
the album list from live Plex takes ~8s+ on a 2,300-album library
(Plex generating the XML, not Player), so these two pools use a
stale-while-revalidate scheme instead of a plain TTL cache:

  * Pools persist to cache_data/ on disk, so a restart loads them
    instantly instead of re-fetching from Plex.
  * A background thread warms both pools at startup.
  * Once a pool is older than POOL_TTL it is still served immediately
    while a background thread refreshes it -- no request ever waits
    on a rebuild unless there is genuinely nothing cached anywhere.
  * One lock per pool, so simultaneous requests never start duplicate
    rebuilds.

Sorting is applied to the cached pool at request time (memoized per
pool, so it's computed once per sort order, not per page). Once inside
one artist or one album, result sets are small, so plex_client's own
functions are called directly with no caching.
"""
import bisect
import json
import os
import threading
import time

import plex_client
import result_cache

POOL_TTL = 3600  # seconds before a background refresh is triggered

_DISK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_data")

_FETCHERS = {
    "artists": plex_client.list_all_artists,
    "albums": plex_client.list_all_albums,
}
_ARTIST_SORTS = ("title", "added")
_ALBUM_SORTS = ("title", "artist", "year", "added")

_POOLS = {}            # name -> (timestamp, list)
_LOCKS = {name: threading.Lock() for name in _FETCHERS}
_STATE_LOCK = threading.Lock()
_REFRESHING = set()
_SORTED = {}           # (name, sort) -> (pool it was built from, sorted list)
_LETTER_KEYS = {}      # name -> (sorted list, lowercase keys, first non-alpha idx)


# --- disk persistence --------------------------------------------------

def _disk_path(name):
    return os.path.join(_DISK_DIR, f"{name}_pool.json")


def _save_disk(name, ts, data):
    try:
        os.makedirs(_DISK_DIR, exist_ok=True)
        tmp = _disk_path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": ts, "data": data}, f)
        os.replace(tmp, _disk_path(name))
    except Exception:
        pass  # persistence is a bonus, never a requirement


def _load_disk(name):
    try:
        with open(_disk_path(name), encoding="utf-8") as f:
            blob = json.load(f)
        if blob.get("data"):
            return (float(blob["ts"]), blob["data"])
    except Exception:
        pass
    return None


# --- pool management ---------------------------------------------------

def _rebuild(name):
    data = _FETCHERS[name]()
    if data:  # never replace a good pool with an empty result
        ts = time.time()
        _POOLS[name] = (ts, data)
        _save_disk(name, ts, data)
    return data


def _refresh_async(name):
    with _STATE_LOCK:
        if name in _REFRESHING:
            return
        _REFRESHING.add(name)

    def run():
        try:
            with _LOCKS[name]:
                _rebuild(name)
        except Exception:
            pass  # keep serving the old pool; try again next time it's stale
        finally:
            with _STATE_LOCK:
                _REFRESHING.discard(name)

    threading.Thread(target=run, daemon=True).start()


def _get_pool(name):
    entry = _POOLS.get(name)
    if entry is None:
        disk = _load_disk(name)
        if disk is not None:
            entry = _POOLS.setdefault(name, disk)
    if entry is not None:
        ts, data = entry
        if time.time() - ts > POOL_TTL:
            _refresh_async(name)
        return data
    # Truly cold (no memory, no disk): build once. Concurrent callers
    # wait on the lock, then reuse the result instead of rebuilding.
    with _LOCKS[name]:
        entry = _POOLS.get(name)
        if entry is not None:
            return entry[1]
        return _rebuild(name)


def _warm_all():
    for name in _FETCHERS:
        try:
            _get_pool(name)
        except Exception:
            pass


threading.Thread(target=_warm_all, daemon=True).start()


# --- sorting -----------------------------------------------------------

def _sort_artists(pool, sort):
    if sort == "added":
        return sorted(pool, key=lambda a: a.get("added_at") or "", reverse=True)
    return sorted(pool, key=lambda a: a["title"].lower())  # default: "title"


def _sort_albums(pool, sort):
    if sort == "artist":
        return sorted(pool, key=lambda a: (a["artist"].lower(), a["title"].lower()))
    if sort == "year":
        return sorted(pool, key=lambda a: (-(a["year"] or 0), a["title"].lower()))
    if sort == "added":
        return sorted(pool, key=lambda a: a.get("added_at") or "", reverse=True)
    return sorted(pool, key=lambda a: a["title"].lower())  # default: "title"


def _sorted_view(name, sort, pool):
    valid = _ARTIST_SORTS if name == "artists" else _ALBUM_SORTS
    sort = sort if sort in valid else "title"
    hit = _SORTED.get((name, sort))
    if hit is not None and hit[0] is pool:
        return hit[1]
    sorter = _sort_artists if name == "artists" else _sort_albums
    out = sorter(pool, sort)
    _SORTED[(name, sort)] = (pool, out)
    return out


def _letter_offset(name, letter):
    """A-Z quickbar lookup. Only meaningful for the title sort. The key
    list is built once per sorted pool; each tap is a binary search."""
    sorted_pool = _sorted_view(name, "title", _get_pool(name))
    memo = _LETTER_KEYS.get(name)
    if memo is None or memo[0] is not sorted_pool:
        keys = [(x["title"] or "").lower() for x in sorted_pool]
        first_non_alpha = next(
            (i for i, k in enumerate(keys) if not k or not k[0].isalpha()),
            len(keys),
        )
        memo = (sorted_pool, keys, first_non_alpha)
        _LETTER_KEYS[name] = memo
    _, keys, first_non_alpha = memo
    letter = letter.lower()
    if letter == "#":
        return first_non_alpha
    return bisect.bisect_left(keys, letter)


# --- public API (unchanged signatures) ---------------------------------

def browse_artists_page(offset=0, limit=48, sort="added"):
    pool = _get_pool("artists")
    return result_cache.paged(_sorted_view("artists", sort, pool), offset, limit)


def artist_letter_offset(letter):
    return _letter_offset("artists", letter)


def browse_albums_page(offset=0, limit=48, sort="added"):
    pool = _get_pool("albums")
    return result_cache.paged(_sorted_view("albums", sort, pool), offset, limit)


def album_letter_offset(letter):
    return _letter_offset("albums", letter)
