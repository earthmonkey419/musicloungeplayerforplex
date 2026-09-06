from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import musicmind_bridge
from auth import admin_required

bp = Blueprint("player", __name__)


@bp.route("/")
@admin_required
def index():
    playlists = [dict(p) for p in db.list_playlists()]
    return render_template(
        "player.html",
        playlists=playlists,
        musicmind_available=musicmind_bridge.is_available(),
    )


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
