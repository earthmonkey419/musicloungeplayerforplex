"""
Player -- library browsing (Artists / Albums / Album -> Tracklist).

Only the top-level artist/album lists need caching/pagination --
walking the whole library on every page load would be slow, same
reasoning as search/mood pools (see musicmind_bridge.py). Sorting is
applied to the cached pool at request time, not baked into the cache
itself -- one cached pool per entity type serves every sort order,
since sorting an already-in-memory Python list is cheap.

Once you're inside one artist (their albums) or one album (its
tracklist), those result sets are small by nature, so no caching is
needed there -- plex_client's own functions are called directly.
"""
import plex_client
import result_cache

POOL_TTL = 3600  # 1 hour -- the library's artist/album lists don't
                 # change often enough to justify rebuilding sooner


def _sort_artists(pool, sort):
    if sort == "added":
        return sorted(pool, key=lambda a: a.get("added_at") or "", reverse=True)
    return sorted(pool, key=lambda a: a["title"].lower())  # default: "title"


def browse_artists_page(offset=0, limit=48, sort="added"):
    cache_key = ("browse_artists",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = plex_client.list_all_artists()
        result_cache.cache_set(cache_key, pool, ttl=POOL_TTL)
    return result_cache.paged(_sort_artists(pool, sort), offset, limit)


def artist_letter_offset(letter):
    """Powers the A-Z quickbar for Browse Artists. Only meaningful for
    the default title sort -- see result_cache.offset_for_letter()'s
    own docstring for why."""
    cache_key = ("browse_artists",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = plex_client.list_all_artists()
        result_cache.cache_set(cache_key, pool, ttl=POOL_TTL)
    sorted_pool = _sort_artists(pool, "title")
    return result_cache.offset_for_letter(sorted_pool, lambda a: a["title"], letter)


def _sort_albums(pool, sort):
    if sort == "artist":
        return sorted(pool, key=lambda a: (a["artist"].lower(), a["title"].lower()))
    if sort == "year":
        return sorted(pool, key=lambda a: (-(a["year"] or 0), a["title"].lower()))
    if sort == "added":
        return sorted(pool, key=lambda a: a.get("added_at") or "", reverse=True)
    return sorted(pool, key=lambda a: a["title"].lower())  # default: "title"


def browse_albums_page(offset=0, limit=48, sort="added"):
    cache_key = ("browse_albums",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = plex_client.list_all_albums()
        result_cache.cache_set(cache_key, pool, ttl=POOL_TTL)
    return result_cache.paged(_sort_albums(pool, sort), offset, limit)


def album_letter_offset(letter):
    """Powers the A-Z quickbar for Browse Albums. Only meaningful for
    the default title sort -- see result_cache.offset_for_letter()'s
    own docstring for why."""
    cache_key = ("browse_albums",)
    pool = result_cache.cache_get(cache_key)
    if pool is None:
        pool = plex_client.list_all_albums()
        result_cache.cache_set(cache_key, pool, ttl=POOL_TTL)
    sorted_pool = _sort_albums(pool, "title")
    return result_cache.offset_for_letter(sorted_pool, lambda a: a["title"], letter)
