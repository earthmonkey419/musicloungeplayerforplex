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

import musicmind_bridge
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
_DIRTY = set()          # pools that must be rebuilt again after the current run
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
            # A rebuild is already running, possibly from before the
            # change that triggered this call -- have it go round once
            # more instead of silently dropping the request.
            _DIRTY.add(name)
            return
        _REFRESHING.add(name)

    def run():
        try:
            while True:
                try:
                    with _LOCKS[name]:
                        _rebuild(name)
                except Exception:
                    pass  # keep serving the old pool; try again next time it's stale
                with _STATE_LOCK:
                    if name in _DIRTY:
                        _DIRTY.discard(name)
                        continue
                    _REFRESHING.discard(name)
                    break
        except BaseException:
            with _STATE_LOCK:
                _REFRESHING.discard(name)
            raise

    threading.Thread(target=run, daemon=True).start()


def refresh_all():
    """Rebuild every pool from Plex in the background. The old pools
    keep serving until each new one is ready, so nobody waits."""
    for name in _FETCHERS:
        _refresh_async(name)


def is_refreshing():
    with _STATE_LOCK:
        return bool(_REFRESHING)


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


# --- albums by MusicMind tag (Browse -> Genres) ------------------------

# An album counts for a tag when at least this share of its tracks carry
# it. Tags are per-track AI labels, so one tagged track on a 14-track
# album is noise, not a genre match. If that bar leaves nothing, the
# looser "any tagged track" set is used so a rare tag never shows empty.
MIN_TAG_SHARE = 0.25
_VARIOUS = {"various artists", "various", "va", "v.a."}


def _match_tag_groups_to_albums(groups, albums):
    """Map MusicMind (album title, artist, tagged-track count) rows onto
    the Plex album pool. Returns {album rating_key: tagged track count}.

    MusicMind has no album key, so matching is by title (case-folded),
    with the track artist breaking ties when several albums share a
    title ("Greatest Hits"). A title unique in the pool matches on title
    alone, which is what keeps Various Artists albums working: their
    per-track artists never equal the album artist "Various Artists".
    An ambiguous title that can't be resolved by artist is skipped
    rather than guessed."""
    by_title = {}
    for a in albums:
        by_title.setdefault((a.get("title") or "").strip().lower(), []).append(a)

    counts = {}
    for g in groups:
        cands = by_title.get((g["album"] or "").strip().lower())
        if not cands:
            continue
        if len(cands) == 1:
            pick = cands[0]
        else:
            artist = (g["artist"] or "").strip().lower()
            same = [c for c in cands if (c.get("artist") or "").strip().lower() == artist]
            if len(same) == 1:
                pick = same[0]
            else:
                various = [c for c in cands if (c.get("artist") or "").strip().lower() in _VARIOUS]
                if not same and len(various) == 1:
                    pick = various[0]  # per-track artist on a compilation
                else:
                    continue
        counts[pick["rating_key"]] = counts.get(pick["rating_key"], 0) + g["tagged"]
    return counts


def _build_tag_album_pool(tag):
    """Albums for one tag, best match first. Each item is a copy of the
    Plex pool's album dict plus "tagged" (tracks with the tag). Returns
    None if MusicMind isn't available."""
    groups = musicmind_bridge.tag_album_groups(tag)
    if groups is None:
        return None
    albums = _get_pool("albums") or []
    counts = _match_tag_groups_to_albums(groups, albums)
    by_key = {a["rating_key"]: a for a in albums}

    def share(rk):
        total = by_key[rk].get("track_count") or 0
        return min(1.0, counts[rk] / total) if total else 1.0

    keys = [rk for rk in counts if share(rk) >= MIN_TAG_SHARE] or list(counts)
    keys.sort(key=lambda rk: (-share(rk), -counts[rk], (by_key[rk].get("title") or "").lower()))
    return [dict(by_key[rk], tagged=counts[rk]) for rk in keys]


def available_genres():
    """Browse -> Genres list. Returns (source, names): MusicMind's tags
    when MusicMind is available, otherwise Plex's own album genres
    (coarser, but needs nothing else). names is [] if neither works."""
    tags = musicmind_bridge.available_tags()
    if tags:
        return "musicmind", [t["tag"] for t in tags]
    cached = result_cache.cache_get(("plex_album_genres",))
    if cached is None:
        try:
            cached = plex_client.list_album_genres()
        except Exception:
            return "plex", []
        if cached:
            result_cache.cache_set(("plex_album_genres",), cached, ttl=result_cache._MOOD_CACHE_TTL)
    return "plex", cached or []


def _plex_genre_page(genre, offset, limit, sort):
    cache_key = ("plex_genre_albums", genre.lower())
    keys = result_cache.cache_get(cache_key)
    if keys is None:
        keys = plex_client.album_keys_for_genre(genre)
        if keys:
            result_cache.cache_set(cache_key, keys, ttl=result_cache._MOOD_CACHE_TTL)
    pool = [a for a in (_get_pool("albums") or []) if a["rating_key"] in keys]
    # No "best match" with a Plex genre: an album has it or it doesn't.
    sort = sort if sort in _ALBUM_SORTS else "title"
    return result_cache.paged(_sort_albums(pool, sort), offset, limit)


def genre_albums_page(genre, offset=0, limit=48, sort="match"):
    """Albums for one Browse -> Genres choice. Uses MusicMind when it is
    available (genre is one of its tags), else Plex genres -- the same
    rule available_genres() uses, so list and results always agree."""
    if available_genres()[0] == "musicmind":
        page = albums_by_tag_page(genre, offset=offset, limit=limit, sort=sort)
        if page is not None:
            return page
    return _plex_genre_page(genre, offset, limit, sort)


def albums_by_tag_page(tag, offset=0, limit=48, sort="match"):
    """Paginated albums for one MusicMind tag. sort is "match" (share of
    the album's tracks carrying the tag, the default) or any normal
    album sort. Returns None if MusicMind isn't available."""
    cache_key = ("tag_album_pool", tag.lower())
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = _build_tag_album_pool(tag)
        if pool is None:
            return None
        if pool:  # never cache an empty result -- it would stick for an hour
            result_cache.cache_set(cache_key, pool, ttl=result_cache._MOOD_CACHE_TTL)
    if sort in _ALBUM_SORTS:
        pool = _sort_albums(pool, sort)
    return result_cache.paged(pool, offset, limit)


def all_albums():
    """The cached whole-library album pool (list of dicts with rating_key,
    title, artist, track_count, ...). Used by Album Radio to pick albums."""
    return _get_pool("albums") or []
