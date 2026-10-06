import threading
import time
from collections import OrderedDict

import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, Response, stream_with_context, current_app

import config
import db
import musicmind_bridge
import plex_client
from auth import guest_required

bp = Blueprint("room", __name__)


def _resolve_action_room():
    """Resolves which room an action (search/queue-add/skip/playpause/
    volume) should apply to. Works for EITHER a guest (room_id in
    session, room still live) OR an admin.

    This matters because the admin dashboard IS the host device -- it's
    the one with the actual <audio> element and transport controls --
    but the admin never goes through /join, so it never has a guest
    room_id session. Every one of these endpoints used to require
    @guest_required alone, which silently 302-redirected every call
    the dashboard ever made (skip, play/pause, the auto-advance-on-
    track-end handler) to /join. fetch() follows redirects and the
    resulting JSON-parse failure was swallowed by a bare .catch(), so
    it failed completely invisibly: is_playing never cleared, so the
    next 4s poll saw "should be playing" + "audio actually paused"
    and replayed the same finished track forever -- the reported
    "stuck on one track, playing over and over" bug.

    Returns (room_id, None) on success, or (None, (response, status))
    for the caller to return immediately."""
    room_id = session.get("room_id")
    if room_id and db.is_room_live(room_id):
        return room_id, None

    if session.get("is_admin"):
        room = db.get_active_room()
        if room:
            return room["session_id"], None
        return None, (jsonify({"error": "No active room."}), 404)

    if room_id:
        session.pop("room_id", None)
        return None, (jsonify({"error": "This room has ended. Please rejoin.", "room_ended": True}), 410)

    return None, (jsonify({"error": "Not authorized."}), 401)


@bp.route("/join/<code>")
def join_by_code(code):
    """Instant join via QR scan -- skips the manual code-entry form.
    Same join logic as the POST /join path, just triggered by a GET
    so a scanned QR link does the whole thing in one step."""
    room = db.get_room_by_code(code)
    if not room:
        return render_template("join.html", error="That code didn't match an active room.")
    session["room_id"] = room["session_id"]
    db.bump_device_count(room["session_id"])
    db.touch_room(room["session_id"])
    db.log_action(room["session_id"], "join")
    return redirect(url_for("room.guest"))


@bp.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        code = request.form.get("join_code", "").strip()
        room = db.get_room_by_code(code)
        if not room:
            return render_template("join.html", error="That code didn't match an active room.")
        session["room_id"] = room["session_id"]
        db.bump_device_count(room["session_id"])
        db.touch_room(room["session_id"])
        db.log_action(room["session_id"], "join")
        return redirect(url_for("room.guest"))
    return render_template("join.html")


@bp.route("/guest")
@guest_required
def guest():
    room = db.get_room(session["room_id"])
    if not room or not db.is_room_live(session["room_id"]):
        session.pop("room_id", None)
        return redirect(url_for("room.join"))
    return render_template("guest.html", room=room)


# --- JSON API, used by guest.html + admin_dashboard.html's JS ---
# Every action endpoint below accepts either a guest or an admin
# session -- see _resolve_action_room() above for why that matters.

@bp.route("/api/search")
def api_search():
    """Guest-facing search -- now MusicMind-accelerated and paginated,
    the same search_tracks_page() Player's own /api/player/search
    already uses. search_tracks_page()'s underlying _build_search_pool()
    falls back to live plex_client.search_tracks() internally whenever
    MusicMind is unavailable, so this degrades exactly as safely as
    Player's search does -- confirmed directly, not assumed.

    Deliberately does NOT include album results the way Player's search
    does: guests have no album detail page to drill into (Browse is
    admin-only), so an album tile would have nothing sensible to do
    here. Scoped decision, not an oversight."""
    room_id, err = _resolve_action_room()
    if err:
        return err
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": [], "has_more": False, "next_offset": 0})
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    try:
        page = musicmind_bridge.search_tracks_page(q, offset=offset, limit=limit)
        return jsonify(page)
    except Exception:
        current_app.logger.exception("Guest search failed for query: %r", q)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/tags")
def api_tags():
    """Guest-facing tag list for the predictive-typing Tags field --
    same available_tags() Player's own /api/player/tags uses. Empty
    list (not an error) when MusicMind isn't configured, same as
    Player's version -- the frontend field simply has no suggestions
    in that case, no fallback routing built for guests (see api_tag()
    below for why)."""
    room_id, err = _resolve_action_room()
    if err:
        return err
    try:
        tags = musicmind_bridge.available_tags()
        return jsonify({"tags": tags or []})
    except Exception:
        current_app.logger.exception("Guest tag list lookup failed")
        return jsonify({"tags": []})


@bp.route("/api/tag")
def api_tag():
    """Guest-facing paginated tag browse -- same tracks_by_tag_page()
    Player's own /api/player/tag uses, including shuffle_seed threading
    so repeat Explore submissions surface different tracks. Unlike
    /api/search above, this has NO live-Plex fallback -- tags come
    purely from MusicMind's track_tags table, which has no Plex
    equivalent to fall back to. Same limitation Player's own tag
    browsing has; not a guest-specific gap."""
    room_id, err = _resolve_action_room()
    if err:
        return err
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
        current_app.logger.exception("Guest tag browse failed for: %r", tag)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/mood/<mood_key>")
def api_mood(mood_key):
    room_id, err = _resolve_action_room()
    if err:
        return err
    try:
        # Cached pool + a fresh shuffle on every click (no seed), so
        # repeat pill clicks surface different tracks. Plain list, same
        # shape the guest page's loadMood() already expects.
        page = musicmind_bridge.tracks_by_mood_page(mood_key, offset=0, limit=20)
        return jsonify(page["results"])
    except Exception:
        current_app.logger.exception("Plex mood lookup failed for: %r", mood_key)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


def _room_state(room_id):
    room = db.get_room(room_id)
    if not room:
        return None
    queue = db.get_queue(room_id)
    return {
        "now_playing": {
            "ref": room["now_playing_ref"],
            "title": room["now_playing_title"],
            "artist": room["now_playing_artist"],
            "duration_sec": room["now_playing_duration"],
            "is_playing": bool(room["is_playing"]),
            "volume": room["volume"],
        } if room["now_playing_ref"] else None,
        "queue": [dict(q) for q in queue],
        "join_code": room["join_code"],
        "room_name": room["room_name"],
    }


@bp.route("/api/room-state")
def api_room_state():
    # Previously had its own separate resolution logic that trusted
    # session["room_id"] with no liveness check -- if this same
    # browser/device had EVER joined a different room as a guest
    # before, that old (possibly long-ended) room_id would be reused
    # forever, silently overriding whichever room is actually active
    # now. This is exactly what _resolve_action_room() already guards
    # against (checks is_room_live() first, and always prioritizes the
    # admin's actual current room over a stale guest session) -- reuse
    # it here instead of duplicating a less-safe version.
    room_id, err = _resolve_action_room()
    if err:
        return err
    state = _room_state(room_id)
    return jsonify(state) if state else (jsonify({"error": "not found"}), 404)


@bp.route("/api/queue/add", methods=["POST"])
def api_queue_add():
    room_id, err = _resolve_action_room()
    if err:
        return err
    db.touch_room(room_id)

    body = request.get_json(silent=True) or {}
    rating_key = body.get("rating_key")

    try:
        room = db.get_room(room_id)
        if db.queue_count(room_id) >= config.ROOM_MAX_QUEUE_ADDS_PER_SESSION:
            return jsonify({"error": "This room's queue is full for now."}), 429

        try:
            track = plex_client.get_track(rating_key)
        except Exception:
            current_app.logger.exception("Plex track lookup failed for rating_key=%r", rating_key)
            return jsonify({"error": "Couldn't find that track."}), 404

        track_dict = plex_client._track_to_dict(track)
        db.add_to_queue(room_id, track_dict)
        db.log_action(room_id, "queue_add", track_dict["title"])

        if not room["now_playing_ref"]:
            nxt = db.pop_next(room_id)
            if nxt:
                db.set_now_playing(room_id, db.queue_row_to_track(nxt), start_playing=False)

        return jsonify({"ok": True})

    except Exception:
        current_app.logger.exception("queue/add failed unexpectedly for rating_key=%r, room=%r", rating_key, room_id)
        return jsonify({"error": "Something went wrong adding that track."}), 500


@bp.route("/api/skip", methods=["POST"])
def api_skip():
    room_id, err = _resolve_action_room()
    if err:
        return err
    db.touch_room(room_id)

    body = request.get_json(silent=True) or {}
    if body.get("auto") and session.get("is_admin"):
        # Natural end-of-track from the HOST player (admin only -- guests
        # never reach this branch). Idempotent: advances only if the track
        # that ended is still the one playing, so a duplicate (second
        # dashboard tab, retry, a manual skip that already advanced) is a
        # harmless no-op instead of skipping a track. Exempt from the
        # manual-skip rate limit, and doesn't feed it either.
        from_ref = str(body.get("from") or "")
        room = db.get_room(room_id)
        if not from_ref or not room or str(room["now_playing_ref"] or "") != from_ref:
            return jsonify({"ok": True, "noop": True})
        nxt = db.pop_next(room_id)
        if nxt:
            db.set_now_playing(room_id, db.queue_row_to_track(nxt))
        else:
            db.set_play_state(room_id, False)
        db.log_action(room_id, "auto_advance")
        return jsonify({"ok": True})

    if not db.can_skip(room_id):
        return jsonify({"error": "Skipping too fast -- try again in a moment."}), 429
    db.record_skip(room_id)
    nxt = db.pop_next(room_id)
    if nxt:
        db.set_now_playing(room_id, db.queue_row_to_track(nxt))
    else:
        db.set_play_state(room_id, False)
    db.log_action(room_id, "skip")
    return jsonify({"ok": True})


@bp.route("/api/playpause", methods=["POST"])
def api_playpause():
    room_id, err = _resolve_action_room()
    if err:
        return err
    db.touch_room(room_id)
    room = db.get_room(room_id)
    db.set_play_state(room_id, not room["is_playing"])
    db.log_action(room_id, "play_pause")
    return jsonify({"ok": True})


@bp.route("/api/volume", methods=["POST"])
def api_volume():
    room_id, err = _resolve_action_room()
    if err:
        return err
    db.touch_room(room_id)
    body = request.get_json(silent=True) or {}
    try:
        vol = int(body.get("volume", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "bad volume"}), 400
    clamped = db.set_volume(room_id, vol)
    db.log_action(room_id, "volume", str(clamped))
    return jsonify({"ok": True, "volume": clamped})


# --- Cover art: resized + cached ------------------------------------------
#
# Every track row / album tile fetches /art/<key>. Uncached, each one
# cost a Plex metadata round trip PLUS a full-size image download,
# buffered in memory, on a single 4-thread worker -- so a page with
# dozens of tiles (the home page's Recently Added row) queued its own
# startup API calls behind cover art. Now:
#   * ?w=<128|300|600> asks Plex's photo transcoder for a right-sized
#     image (a 44px thumbnail no longer downloads a 1000px cover);
#     no ?w= keeps the original behavior (full-size), so email
#     thumbnails / lock-screen art callers are unaffected.
#   * A small in-process LRU keeps the resulting bytes (and skips the
#     metadata lookup entirely on a hit). Single gunicorn worker, so
#     one dict is the right scope -- same assumption as result_cache.
_ART_WIDTHS = (128, 300, 600)
_ART_TTL = 24 * 3600          # covers rarely change
_ART_MISS_TTL = 600           # remember "no art" briefly, not forever
_ART_MAX_BYTES = 48 * 1024 * 1024
_art_cache = OrderedDict()    # (rating_key, width) -> (ts, content_type|None, bytes|None)
_art_cache_bytes = 0
_art_lock = threading.Lock()
_plex_http = requests.Session()   # keep-alive to Plex instead of a new connection per image


def _art_cache_get(key):
    global _art_cache_bytes
    with _art_lock:
        entry = _art_cache.get(key)
        if entry is None:
            return None
        ts, ctype, data = entry
        ttl = _ART_TTL if data is not None else _ART_MISS_TTL
        if time.time() - ts > ttl:
            _art_cache.pop(key, None)
            _art_cache_bytes -= len(data or b"")
            return None
        _art_cache.move_to_end(key)
        return entry


def _art_cache_put(key, ctype, data):
    global _art_cache_bytes
    with _art_lock:
        old = _art_cache.pop(key, None)
        if old is not None:
            _art_cache_bytes -= len(old[2] or b"")
        _art_cache[key] = (time.time(), ctype, data)
        _art_cache_bytes += len(data or b"")
        while _art_cache_bytes > _ART_MAX_BYTES and _art_cache:
            _, (_, _, dropped) = _art_cache.popitem(last=False)
            _art_cache_bytes -= len(dropped or b"")


def _art_response(ctype, data):
    resp = Response(data, content_type=ctype or "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.route("/art/<rating_key>")
def art(rating_key):
    width = request.args.get("w", type=int)
    if width not in _ART_WIDTHS:
        width = None
    key = (str(rating_key), width)

    hit = _art_cache_get(key)
    if hit is not None:
        _, ctype, data = hit
        return ("", 404) if data is None else _art_response(ctype, data)

    try:
        thumb_path = plex_client.track_art_path(rating_key)
    except Exception:
        return "", 404
    if not thumb_path:
        _art_cache_put(key, None, None)
        return "", 404

    upstream = None
    if width:
        try:
            upstream = _plex_http.get(
                f"{config.PLEX_URL}/photo/:/transcode",
                params={
                    "url": thumb_path,
                    "width": width,
                    "height": width,
                    "minSize": 1,
                    "upscale": 0,
                    "X-Plex-Token": config.PLEX_TOKEN,
                },
                timeout=6,
            )
            if upstream.status_code != 200:
                upstream = None  # fall back to the original below
        except Exception:
            upstream = None

    if upstream is None:
        try:
            upstream = _plex_http.get(
                f"{config.PLEX_URL}{thumb_path}?X-Plex-Token={config.PLEX_TOKEN}",
                timeout=6,
            )
        except Exception:
            return "", 502
        if upstream.status_code != 200:
            return "", 404

    ctype = upstream.headers.get("Content-Type", "image/jpeg")
    _art_cache_put(key, ctype, upstream.content)
    return _art_response(ctype, upstream.content)


@bp.route("/stream/<rating_key>")
def stream(rating_key):
    try:
        part_path = plex_client.track_stream_part(rating_key)
    except Exception:
        return "Track not found", 404

    plex_url = f"{config.PLEX_URL}{part_path}?X-Plex-Token={config.PLEX_TOKEN}"
    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    upstream = requests.get(plex_url, headers=headers, stream=True)

    def generate():
        for chunk in upstream.iter_content(chunk_size=8192):
            yield chunk

    resp = Response(
        stream_with_context(generate()),
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "audio/mpeg"),
    )
    for h in ("Content-Range", "Content-Length", "Accept-Ranges"):
        if h in upstream.headers:
            resp.headers[h] = upstream.headers[h]
    return resp
