from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import library_browse
import musicmind_bridge
import lastfm_client
from auth import admin_required

bp = Blueprint("browse", __name__)


def _lastfm_active():
    return lastfm_client.is_configured() and lastfm_client.is_authorized()


@bp.route("/")
@admin_required
def artists():
    # Single browse index page -- which entity type (artists/albums/
    # tracks) and sort order are read client-side from the URL query
    # string and UI controls, not branched here. Keeps one template
    # and one set of pagination JS instead of duplicating it per type.
    # native_playlists is only actually needed for the Tracks type
    # (Add to Playlist modal) but costs nothing to pass unconditionally.
    native_playlists = [dict(p) for p in db.list_playlists() if p["source"] == "native"]
    return render_template(
        "browse_index.html",
        lastfm_active=_lastfm_active(),
        playlists_for_modal=native_playlists,
        player_family=True,
    )


@bp.route("/api/artists")
@admin_required
def api_artists():
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(96, max(1, request.args.get("limit", 48, type=int) or 48))
    sort = request.args.get("sort", "title")
    try:
        return jsonify(library_browse.browse_artists_page(offset=offset, limit=limit, sort=sort))
    except Exception:
        current_app.logger.exception("Browse artists failed")
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/albums")
@admin_required
def api_albums():
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(96, max(1, request.args.get("limit", 48, type=int) or 48))
    sort = request.args.get("sort", "title")
    try:
        return jsonify(library_browse.browse_albums_page(offset=offset, limit=limit, sort=sort))
    except Exception:
        current_app.logger.exception("Browse albums failed")
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/tracks")
@admin_required
def api_tracks():
    offset = max(0, request.args.get("offset", 0, type=int) or 0)
    limit = min(96, max(1, request.args.get("limit", 48, type=int) or 48))
    sort = request.args.get("sort", "title")
    try:
        return jsonify(musicmind_bridge.browse_tracks_page(offset=offset, limit=limit, sort=sort))
    except Exception:
        current_app.logger.exception("Browse tracks failed")
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/api/letter-offset")
@admin_required
def api_letter_offset():
    """Powers the A-Z quickbar: given a browse type and a letter,
    returns the offset where that letter's section begins in the
    title-sorted pool, so the frontend can jump straight there rather
    than loading every page in between."""
    browse_type = request.args.get("type", "")
    letter = request.args.get("letter", "").strip()
    if browse_type not in ("artists", "albums", "tracks") or not letter:
        return jsonify({"error": "Invalid type or letter."}), 400
    try:
        if browse_type == "artists":
            offset = library_browse.artist_letter_offset(letter)
        elif browse_type == "albums":
            offset = library_browse.album_letter_offset(letter)
        else:
            offset = musicmind_bridge.track_letter_offset(letter)
        return jsonify({"offset": offset})
    except Exception:
        current_app.logger.exception("Letter offset lookup failed for type=%r letter=%r", browse_type, letter)
        return jsonify({"error": "Couldn't reach the music library. Try again in a moment."}), 502


@bp.route("/artist/<rating_key>")
@admin_required
def artist_detail(rating_key):
    try:
        artist_title, albums = plex_client.get_artist_detail(rating_key)
    except Exception:
        current_app.logger.exception("Failed to load artist rating_key=%r", rating_key)
        return "Couldn't load that artist.", 502
    return render_template(
        "browse_artist_detail.html",
        artist_title=artist_title,
        albums=albums,
        rating_key=rating_key,
        lastfm_active=_lastfm_active(),
        player_family=True,
    )


@bp.route("/api/album-for-track/<rating_key>")
@admin_required
def api_album_for_track(rating_key):
    """Resolves a track's parent album rating key -- powers "Go to
    Album" from a track row. A JSON lookup rather than a redirecting
    route deliberately: spa-nav.js's own fetch-based navigation
    explicitly falls back to a full page reload whenever a fetch gets
    redirected to a different path than requested (a safeguard for
    expired-session-redirects-to-login), which would have caught this
    too and defeated persistent playback on every album jump. Having
    the frontend resolve the real album URL first and navigate
    directly to it avoids a redirect entirely."""
    try:
        track = plex_client.get_plex().fetchItem(int(rating_key))
        return jsonify({"album_rating_key": track.parentRatingKey})
    except Exception:
        current_app.logger.exception("api_album_for_track failed to resolve rating_key=%r", rating_key)
        return jsonify({"error": "Couldn't find that track's album."}), 404


@bp.route("/album/<rating_key>")
@admin_required
def album_detail(rating_key):
    try:
        album_title, artist_title, tracks = plex_client.get_album_detail(rating_key)
    except Exception:
        current_app.logger.exception("Failed to load album rating_key=%r", rating_key)
        return "Couldn't load that album.", 502
    native_playlists = [dict(p) for p in db.list_playlists() if p["source"] == "native"]
    return render_template(
        "browse_album_detail.html",
        album_title=album_title,
        artist_title=artist_title,
        tracks=tracks,
        rating_key=rating_key,
        playlists_for_modal=native_playlists,
        lastfm_active=_lastfm_active(),
        player_family=True,
    )
