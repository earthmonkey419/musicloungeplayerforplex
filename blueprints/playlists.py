from flask import Blueprint, render_template, request, jsonify, current_app

import db
import plex_client
import plex_export
import lastfm_client
from auth import admin_required

bp = Blueprint("playlists", __name__)


def _combined_playlists(sort):
    """Shared by the page route and the JSON API route below, so the
    sort dropdown can re-fetch client-side (staying within the SPA
    zone, not interrupting playback) without duplicating this logic."""
    native_rows = [dict(p) for p in db.list_playlists()]
    native_items = []
    for p in native_rows:
        native_items.append({
            "kind": "native",
            "id": p["id"],
            "title": p["name"],
            "created_at": p["created_at"] or "",
            "updated_at": p["updated_at"] or "",
            "track_count": len(db.get_playlist_tracks(p["id"])),
        })

    try:
        plex_playlists = plex_client.list_all_playlists()
    except Exception:
        current_app.logger.exception("Failed to list Plex playlists")
        plex_playlists = []

    plex_items = [{
        "kind": "plex",
        "rating_key": p["rating_key"],
        "title": p["title"],
        "created_at": p["added_at"],
        "updated_at": p["updated_at"],
        "track_count": p["track_count"],
    } for p in plex_playlists]

    combined = native_items + plex_items
    if sort == "name":
        combined.sort(key=lambda x: x["title"].lower())
    elif sort == "date":
        combined.sort(key=lambda x: x["created_at"], reverse=True)
    else:
        sort = "recent"
        combined.sort(key=lambda x: x["updated_at"], reverse=True)

    return combined, sort


# --- Views --------------------------------------------------------------

@bp.route("/")
@admin_required
def index():
    # No more "import a Plex playlist" step -- every Plex playlist is
    # automatically listed here, live, alongside native ones, in one
    # combined sortable list. Native rows come from our own DB;
    # Plex ones are fetched fresh every view (small lists, no caching
    # needed at this scale -- see PLAYER-POLISH-ROADMAP.md if that
    # changes).
    sort = request.args.get("sort", "recent")
    combined, sort = _combined_playlists(sort)
    return render_template("playlists.html", playlists=combined, current_sort=sort, player_family=True)


@bp.route("/api/list")
@admin_required
def api_list():
    sort = request.args.get("sort", "recent")
    combined, sort = _combined_playlists(sort)
    return jsonify({"playlists": combined, "sort": sort})


@bp.route("/<int:playlist_id>")
@admin_required
def view(playlist_id):
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        return "Playlist not found.", 404

    tracks = db.get_playlist_tracks(playlist_id)
    return render_template(
        "playlist_detail.html",
        playlist=playlist,
        tracks=tracks,
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
        player_family=True,
    )


@bp.route("/plex/<rating_key>")
@admin_required
def plex_detail(rating_key):
    # Read-only -- live from Plex every view, same refresh-always
    # philosophy the old plex_synced rows used, just without needing a
    # DB row to remember you'd "imported" it first.
    try:
        _, _, tracks = plex_client.get_content_tracks("playlist", rating_key)
        playlist_obj = plex_client.get_plex().fetchItem(int(rating_key))
        title = playlist_obj.title
    except Exception:
        current_app.logger.exception("Failed to load Plex playlist rating_key=%r", rating_key)
        return "Couldn't load that playlist.", 502

    native_playlists = [dict(p) for p in db.list_playlists() if p["source"] == "native"]
    return render_template(
        "playlist_plex_detail.html",
        title=title,
        rating_key=rating_key,
        tracks=tracks,
        playlists_for_modal=native_playlists,
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
        player_family=True,
    )


# --- Native playlist CRUD (JSON API) -------------------------------------

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
    ordered_refs = body.get("track_refs")  # list of rating_keys, new order
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


# --- Export to Plex --------------------------------------------------------

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
