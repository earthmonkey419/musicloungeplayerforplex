from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import musicmind_bridge
import lastfm_client
from auth import admin_required

bp = Blueprint("player", __name__)


@bp.route("/")
@admin_required
def index():
    playlists = [dict(p) for p in db.list_playlists()]
    recent_plays = [dict(p) for p in db.get_recent_plays(limit=10)]
    return render_template(
        "player.html",
        playlists=playlists,
        recent_plays=recent_plays,
        musicmind_available=musicmind_bridge.is_available(),
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
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
        return jsonify({"results": [], "has_more": False, "next_offset": 0})
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    try:
        return jsonify(musicmind_bridge.search_tracks_page(q, offset=offset, limit=limit))
    except Exception:
        current_app.logger.exception("Player search failed for query: %r", q)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/player/mood/<mood_key>")
@admin_required
def api_mood(mood_key):
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(50, max(1, request.args.get("limit", 20, type=int) or 20))
    instrumental_only = request.args.get("instrumental_only") == "1"
    try:
        page = musicmind_bridge.tracks_by_mood_page(
            mood_key, offset=offset, limit=limit, instrumental_only=instrumental_only
        )
        return jsonify(page)
    except Exception:
        current_app.logger.exception("Player mood lookup failed for: %r", mood_key)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502
