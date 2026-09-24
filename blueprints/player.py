from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import musicmind_bridge
import lastfm_client
import library_browse
from auth import admin_required

bp = Blueprint("player", __name__)


@bp.route("/")
@admin_required
def index():
    playlists = [dict(p) for p in db.list_playlists()]
    recent_plays = [dict(p) for p in db.get_recent_plays(limit=10)]
    try:
        recent_albums = library_browse.browse_albums_page(offset=0, limit=50, sort="added")["results"]
    except Exception:
        current_app.logger.exception("Recently added albums failed")
        recent_albums = []
    return render_template(
        "player.html",
        playlists=playlists,
        recent_plays=recent_plays,
        recent_albums=recent_albums,
        musicmind_available=musicmind_bridge.is_available(),
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
        player_family=True,
    )


@bp.route("/help")
@admin_required
def help_page():
    return render_template(
        "help.html",
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
        player_family=True,
    )


@bp.route("/api/player/lastfm/now-playing", methods=["POST"])
@admin_required
def api_lastfm_now_playing():
    body = request.get_json(silent=True) or {}
    artist = body.get("artist")
    title = body.get("title")
    if not artist or not title:
        return jsonify({"ok": False}), 200
    try:
        lastfm_client.update_now_playing(artist, title)
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.exception("Last.fm now-playing update failed for artist=%r title=%r", artist, title)
        return jsonify({"ok": False, "error": str(e)}), 200


@bp.route("/api/player/lastfm/scrobble", methods=["POST"])
@admin_required
def api_lastfm_scrobble():
    body = request.get_json(silent=True) or {}
    artist = body.get("artist")
    title = body.get("title")
    if not artist or not title:
        return jsonify({"ok": False}), 200
    try:
        lastfm_client.scrobble(artist, title)
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.exception("Last.fm scrobble failed for artist=%r title=%r", artist, title)
        return jsonify({"ok": False, "error": str(e)}), 200


@bp.route("/api/player/log-play", methods=["POST"])
@admin_required
def api_log_play():
    body = request.get_json(silent=True) or {}
    rating_key = body.get("rating_key")
    if not rating_key:
        return jsonify({"error": "Missing rating_key."}), 400
    try:
        db.log_play({
            "rating_key": rating_key,
            "title": body.get("title", ""),
            "artist": body.get("artist", ""),
        })
        return jsonify({"ok": True})
    except Exception:
        current_app.logger.exception("Failed to log play for rating_key=%r", rating_key)
        return jsonify({"ok": False}), 200


@bp.route("/api/player/queue", methods=["GET"])
@admin_required
def api_get_queue():
    return jsonify(db.get_player_queue())


@bp.route("/api/player/queue", methods=["POST"])
@admin_required
def api_save_queue():
    body = request.get_json(silent=True) or {}
    queue = body.get("queue", [])
    current_index = body.get("current_index", -1)
    if not isinstance(queue, list):
        return jsonify({"error": "queue must be a list"}), 400
    try:
        db.save_player_queue(queue, current_index)
        return jsonify({"ok": True})
    except Exception:
        current_app.logger.exception("Failed to save player queue")
        return jsonify({"ok": False}), 200


@bp.route("/api/player/search")
@admin_required
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": [], "albums": [], "has_more": False, "next_offset": 0})
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    try:
        page = musicmind_bridge.search_tracks_page(q, offset=offset, limit=limit)
        # Albums only on the first page -- this is a "top matches"
        # section shown once above the track results, not something
        # to re-fetch on every subsequent "load more" page for the
        # same query. None (MusicMind unavailable) degrades to an
        # empty list -- the track results still work either way.
        page["albums"] = (musicmind_bridge.search_albums_for_player(q) or []) if offset == 0 else []
        return jsonify(page)
    except Exception:
        current_app.logger.exception("Player search failed for query: %r", q)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/player/mood/<mood_key>")
@admin_required
def api_mood(mood_key):
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    instrumental_only = request.args.get("instrumental_only") == "1"
    shuffle_seed = request.args.get("seed", type=int)
    try:
        page = musicmind_bridge.tracks_by_mood_page(
            mood_key, offset=offset, limit=limit, instrumental_only=instrumental_only,
            shuffle_seed=shuffle_seed,
        )
        return jsonify(page)
    except Exception:
        current_app.logger.exception("Player mood lookup failed for: %r", mood_key)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/player/content-tracks")
@admin_required
def api_content_tracks():
    """Read-only tracklist resolver -- powers "Play Next" for an album
    or playlist from the shared Room/Share popover. A single track's
    own data is already known client-side (no resolution needed); this
    is only for the album/playlist case, where the frontend doesn't
    have the full tracklist on hand. Reuses the same get_content_tracks()
    Share links and Start-a-Room already rely on for this exact
    resolution, just returned directly as JSON with no other side
    effects (no room, no share link created)."""
    content_type = request.args.get("type", "")
    content_ref = request.args.get("ref", "")
    if content_type not in ("album", "playlist") or not content_ref:
        return jsonify({"error": "Invalid type or ref."}), 400
    try:
        _, _, tracks = plex_client.get_content_tracks(content_type, content_ref)
        return jsonify({"tracks": tracks})
    except Exception:
        current_app.logger.exception("content-tracks resolver failed type=%r ref=%r", content_type, content_ref)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/player/tags")
@admin_required
def api_tags():
    """Lists the library's reliable tags for the predictive-typing
    tags field, sourced from MusicMind's track_tags table when
    available -- far more granular than the old tracks.genre-based
    version (confirmed directly against real data: "new wave" alone
    has 4,364 tagged tracks, vs. tracks.genre's 17 broad categories
    that would have folded it into "Pop/Rock"). Genre-like and mood/
    energy-like tags aren't distinguished in track_tags, so both come
    back together -- a deliberate scoping decision. Empty list (not
    an error) when MusicMind isn't configured -- the frontend falls
    back to its own small hardcoded set rather than showing nothing."""
    try:
        tags = musicmind_bridge.available_tags()
        return jsonify({"tags": tags or []})
    except Exception:
        current_app.logger.exception("Tag list lookup failed")
        return jsonify({"tags": []})


@bp.route("/api/player/tag")
@admin_required
def api_tag():
    """Paginated track browse for one tag. A query param, not a path
    segment -- tag values can contain "/" or other characters that
    would break a path segment."""
    tag = request.args.get("name", "")
    if not tag:
        return jsonify({"error": "Missing tag name."}), 400
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    shuffle_seed = request.args.get("seed", type=int)
    try:
        page = musicmind_bridge.tracks_by_tag_page(tag, offset=offset, limit=limit, shuffle_seed=shuffle_seed)
        if page is None:
            return jsonify({"error": "Tag browsing needs MusicMind, which isn't available right now."}), 502
        return jsonify(page)
    except Exception:
        current_app.logger.exception("Tag browse failed for: %r", tag)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


# --- Radio -----------------------------------------------------------------
# Three engines, chosen once at /start and echoed back by the client as `ctx`:
#   sim   -- MusicMind tag+Synapse similarity (musicmind_bridge.radio_next)
#   sonic -- Plex's own sonicallySimilar() (Plex Pass + analyzed library)
#   mood  -- random mood-bucket pool (Random Radio only; always available)
# Errors are 422 + JSON, never 502 (Cloudflare replaces 502 bodies with HTML).

import random as _radio_random
import result_cache as _radio_cache

RADIO_BATCH = 10
RADIO_MAX_SEEDS = 40


def _radio_error(message):
    return jsonify({"error": message}), 422


def _radio_plex_track_dict(t):
    return {
        "rating_key": int(t.ratingKey),
        "title": t.title,
        "artist": t.grandparentTitle or "",
        "album": t.parentTitle or "",
        "duration_sec": int((t.duration or 0) / 1000),
    }


def _radio_sonic_available():
    """One cached probe per hour: does this Plex server actually return
    sonically-similar tracks? (needs Plex Pass + sonic analysis)"""
    cached = _radio_cache.cache_get(("radio_sonic_ok",))
    if cached is not None:
        return cached["ok"]
    ok = False
    try:
        plex = plex_client.get_plex()
        section = next(s for s in plex.library.sections() if s.type == "artist")
        sample = section.searchTracks(limit=1)
        if sample:
            ok = bool(sample[0].sonicallySimilar(limit=1))
    except Exception:
        ok = False
    _radio_cache.cache_set(("radio_sonic_ok",), {"ok": ok}, ttl=3600)
    return ok


def _radio_sonic_batch(seeds, exclude, limit):
    plex = plex_client.get_plex()
    seed = plex.fetchItem(int(_radio_random.choice(seeds)))
    ex = {str(k) for k in exclude} | {str(s) for s in seeds}
    found = seed.sonicallySimilar(limit=limit * 4)
    _radio_random.shuffle(found)  # nearest-4x-limit pool, shuffled: close but not repetitive
    out, per_artist = [], {}
    for t in found:
        if str(t.ratingKey) in ex:
            continue
        artist = t.grandparentTitle or ""
        if per_artist.get(artist, 0) >= 2:
            continue
        per_artist[artist] = per_artist.get(artist, 0) + 1
        out.append(_radio_plex_track_dict(t))
        if len(out) >= limit:
            break
    return out


def _radio_mood_batch(mood, exclude, limit):
    key = ("radio_mood_pool", mood)
    pool = _radio_cache.cache_get(key)
    if pool is None:
        pool = musicmind_bridge._build_mood_pool(mood, False)
        if pool:  # never cache an empty result
            _radio_cache.cache_set(key, pool, ttl=_radio_cache._MOOD_CACHE_TTL)
    ex = {str(k) for k in exclude}
    fresh = [t for t in (pool or []) if str(t["rating_key"]) not in ex]
    _radio_random.shuffle(fresh)
    return fresh[:limit]


def _radio_batch(ctx, seeds, exclude, limit):
    """Returns a list of track dicts (possibly empty), or None on engine failure."""
    mode = (ctx or {}).get("mode")
    if mode == "sim":
        return musicmind_bridge.radio_next(seeds, exclude_keys=exclude, limit=limit)
    if mode == "sonic":
        return _radio_sonic_batch(seeds, exclude, limit)
    if mode == "mood":
        return _radio_mood_batch(ctx.get("mood") or "rock", exclude, limit)
    return None


@bp.route("/api/player/radio/capabilities")
@admin_required
def api_radio_capabilities():
    mm = musicmind_bridge.is_available()
    track = mm or _radio_sonic_available()
    return jsonify({
        "track_radio": bool(track),
        "random_radio": True,  # mood-bucket fallback always exists
        "engine": "musicmind" if mm else ("plex-sonic" if track else "mood"),
    })


def _radio_start_seeded(kind, ref):
    mm = musicmind_bridge.is_available()
    plex = plex_client.get_plex()
    item = plex.fetchItem(int(ref))

    if kind == "track":
        seeds = [int(ref)]
        first = musicmind_bridge._track_dicts(seeds) if mm else [_radio_plex_track_dict(item)]
        label = item.title
    else:
        plex_tracks = item.tracks()
        if not plex_tracks:
            return _radio_error("That album has no tracks.")
        all_keys = [int(t.ratingKey) for t in plex_tracks]
        pick = _radio_random.choice(all_keys)
        seeds = _radio_random.sample(all_keys, min(len(all_keys), RADIO_MAX_SEEDS))
        first = (musicmind_bridge._track_dicts([pick]) if mm
                 else [_radio_plex_track_dict(t) for t in plex_tracks if int(t.ratingKey) == pick])
        label = item.title

    if mm:
        ctx = {"mode": "sim"}
    elif _radio_sonic_available():
        ctx = {"mode": "sonic"}
    else:
        return _radio_error("Radio needs MusicMind, or a Plex server with sonic analysis.")

    exclude = [t["rating_key"] for t in first]
    batch = _radio_batch(ctx, [str(s) for s in seeds], exclude, RADIO_BATCH)
    if not batch:
        return _radio_error("Couldn't find similar tracks for that one.")
    return jsonify({
        "tracks": first + batch,
        "seeds": [str(s) for s in seeds],
        "label": f"Radio: {label}",
        "ctx": ctx,
    })


def _radio_start_random():
    if musicmind_bridge.is_available():
        picked = musicmind_bridge.random_tag_seeds(3)
        if picked and picked[1]:
            tag, keys = picked
            first = musicmind_bridge._track_dicts(keys)
            batch = musicmind_bridge.radio_next(keys, exclude_keys=keys, limit=RADIO_BATCH) or []
            if first or batch:
                return jsonify({
                    "tracks": first + batch,
                    "seeds": [str(k) for k in keys],
                    "label": f"Random Radio: {tag}",
                    "ctx": {"mode": "sim"},
                })
    mood = _radio_random.choice(list(plex_client.MOOD_BUCKETS.keys()))
    tracks = _radio_mood_batch(mood, [], RADIO_BATCH * 2)
    if not tracks:
        return _radio_error("Couldn't build a random station right now.")
    return jsonify({
        "tracks": tracks,
        "seeds": [],
        "label": f"Random Radio: {mood}",
        "ctx": {"mode": "mood", "mood": mood},
    })


@bp.route("/api/player/radio/start", methods=["POST"])
@admin_required
def api_radio_start():
    data = request.get_json(silent=True) or {}
    kind = data.get("type")
    ref = data.get("ref")
    try:
        if kind == "random":
            return _radio_start_random()
        if kind in ("track", "album") and ref:
            return _radio_start_seeded(kind, ref)
        return _radio_error("Unknown radio request.")
    except Exception:
        current_app.logger.exception("Radio start failed: %r", data)
        return _radio_error("Couldn't start radio. Try again in a moment.")


@bp.route("/api/player/radio/next", methods=["POST"])
@admin_required
def api_radio_next():
    data = request.get_json(silent=True) or {}
    try:
        seeds = [str(s) for s in (data.get("seeds") or [])][:RADIO_MAX_SEEDS]
        exclude = [str(k) for k in (data.get("exclude") or [])][:600]
        limit = min(20, max(1, int(data.get("limit") or RADIO_BATCH)))
        tracks = _radio_batch(data.get("ctx") or {}, seeds, exclude, limit)
    except Exception:
        current_app.logger.exception("Radio refill failed")
        return _radio_error("Radio refill failed.")
    if tracks is None:
        return _radio_error("Radio engine unavailable.")
    return jsonify({"tracks": tracks})
