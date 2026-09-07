from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import plex_export
import lastfm_client
from auth import admin_required

bp = Blueprint("playlists", __name__)


@bp.route("/")
@admin_required
def index():
    return render_template("playlists.html", playlists=db.list_playlists())


@bp.route("/<int:playlist_id>")
@admin_required
def view(playlist_id):
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        return "Playlist not found.", 404

    if playlist["source"] == "plex_synced":
        try:
            _, _, tracks = plex_client.get_content_tracks("playlist", playlist["plex_ref"])
            db.replace_playlist_tracks(playlist_id, tracks)
        except Exception:
            current_app.logger.exception("Failed to refresh synced playlist id=%r", playlist_id)

    tracks = db.get_playlist_tracks(playlist_id)
    return render_template(
        "playlist_detail.html",
        playlist=playlist,
        tracks=tracks,
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
    )


@bp.route("/api/create", methods=["POST"])
@admin_required
def api_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "Give the playlist a name."}), 400
    playlist_id = db.create_playlist(name, source="native")
    return jsonify({"ok": True, "playlist_id": playlist_id})


@bp.route("/api/<int:playlist_id>/rename", methods=["POST"])
@admin_required
def api_rename(playlist_id):
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name can't be empty."}), 400
    db.rename_playlist(playlist_id, name)
    return jsonify({"ok": True})


@bp.route("/api/<int:playlist_id>/delete", methods=["POST"])
@admin_required
def api_delete(playlist_id):
    db.delete_playlist(playlist_id)
    return jsonify({"ok": True})


@bp.route("/api/<int:playlist_id>/add-track", methods=["POST"])
@admin_required
def api_add_track(playlist_id):
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found."}), 404
    if playlist["source"] != "native":
        return jsonify({"error": "Can't add tracks directly to a Plex-synced playlist."}), 400

    body = request.get_json(silent=True) or {}
    rating_key = body.get("rating_key")
    try:
        track = plex_client.get_track(rating_key)
    except Exception:
        return jsonify({"error": "Couldn't find that track."}), 404

    db.add_track_to_playlist(playlist_id, plex_client._track_to_dict(track))
    return jsonify({"ok": True})


@bp.route("/api/<int:playlist_id>/remove-track", methods=["POST"])
@admin_required
def api_remove_track(playlist_id):
    body = request.get_json(silent=True) or {}
    track_row_id = body.get("track_row_id")
    if not track_row_id:
        return jsonify({"error": "Missing track_row_id."}), 400
    db.remove_track_from_playlist(playlist_id, track_row_id)
    return jsonify({"ok": True})


@bp.route("/api/<int:playlist_id>/reorder", methods=["POST"])
@admin_required
def api_reorder(playlist_id):
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found."}), 404
    if playlist["source"] != "native":
        return jsonify({"error": "Can't reorder a Plex-synced playlist here -- reorder it in Plex."}), 400

    body = request.get_json(silent=True) or {}
    ordered_refs = body.get("track_refs")
    if not ordered_refs:
        return jsonify({"error": "Missing track_refs."}), 400

    current = {row["track_ref"]: row for row in db.get_playlist_tracks(playlist_id)}
    tracks = []
    for ref in ordered_refs:
        row = current.get(str(ref))
        if row:
            tracks.append({
                "rating_key": row["track_ref"],
                "title": row["title"],
                "artist": row["artist"],
                "duration_sec": row["duration_sec"],
            })
    db.replace_playlist_tracks(playlist_id, tracks)
    return jsonify({"ok": True})


@bp.route("/api/import-from-plex", methods=["POST"])
@admin_required
def api_import_from_plex():
    body = request.get_json(silent=True) or {}
    plex_ref = body.get("plex_ref")
    name = body.get("name", "").strip()
    if not plex_ref or not name:
        return jsonify({"error": "Missing playlist selection."}), 400

    playlist_id = db.create_synced_playlist(name, plex_ref)
    try:
        _, _, tracks = plex_client.get_content_tracks("playlist", plex_ref)
        db.replace_playlist_tracks(playlist_id, tracks)
    except Exception:
        current_app.logger.exception("Initial sync failed for imported playlist plex_ref=%r", plex_ref)

    return jsonify({"ok": True, "playlist_id": playlist_id})


@bp.route("/api/<int:playlist_id>/export", methods=["POST"])
@admin_required
def api_export(playlist_id):
    try:
        result = plex_export.export_playlist(playlist_id)
    except plex_export.ExportError as e:
        return jsonify({"error": str(e)}), 409
    except Exception:
        current_app.logger.exception("Export failed unexpectedly for playlist_id=%r", playlist_id)
        return jsonify({"error": "Something went wrong exporting to Plex."}), 500
    return jsonify({"ok": True, **result})
