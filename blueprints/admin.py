from flask import Blueprint, render_template, request, redirect, url_for, session, Response, current_app, jsonify
import io
import csv
import base64
from datetime import datetime
import qrcode
import config
import db
import plex_client
import lastfm_client
from auth import admin_required
from email_utils import send_password_reset_email

bp = Blueprint("admin", __name__)


SHARE_CSV_COLUMNS = [
    "share_token", "content_type", "content_ref", "content_title", "content_artist",
    "created_at", "expires_at", "duration_hours", "delivery_method", "recipient_email",
    "from_display_name", "revoked", "access_count", "last_accessed_at",
]
ROOM_CSV_COLUMNS = [
    "session_id", "room_name", "join_code", "started_at", "expires_at", "ended_by_admin",
    "device_count", "now_playing_ref", "now_playing_title", "now_playing_artist",
    "now_playing_duration", "position_sec", "is_playing", "volume", "last_skip_at",
]


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if db.verify_admin_password(request.form.get("password", "")):
            session["is_admin"] = True
            # Opt-in only -- unchecked, this stays a browser-session
            # cookie (today's unchanged behavior: closing the browser
            # logs you out). Checked, it persists up to
            # PERMANENT_SESSION_LIFETIME (see app.py) even after the
            # browser closes -- a real, understood tradeoff (a lost or
            # stolen device stays logged in for that whole window) the
            # admin is choosing themselves, not something forced on by
            # default.
            session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("player.index"))
        return render_template("admin_login.html", error="Wrong password.")
    return render_template("admin_login.html")


@bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("player.index"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        if config.ADMIN_RECOVERY_EMAIL:
            token = db.create_password_reset()
            reset_url = request.host_url.rstrip("/") + url_for("admin.reset_password", token=token)
            try:
                send_password_reset_email(reset_url)
            except Exception:
                current_app.logger.exception("Failed to send password reset email")
        return render_template("admin_forgot_password.html", sent=True)
    return render_template("admin_forgot_password.html", sent=False)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if not db.is_password_reset_valid(token):
        return render_template("admin_forgot_password.html", sent=False,
                                error="That reset link is invalid or has expired. Request a new one below.")

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(new_password) < 8:
            return render_template("admin_reset_password.html", token=token, error="Password must be at least 8 characters.")
        if new_password != confirm:
            return render_template("admin_reset_password.html", token=token, error="Passwords don't match.")
        db.set_admin_password(new_password)
        db.use_password_reset(token)
        return redirect(url_for("admin.login"))

    return render_template("admin_reset_password.html", token=token, error=None)


@bp.route("/stats")
@admin_required
def stats():
    conn = db.get_db()
    now = datetime.utcnow().isoformat()

    share_rows = conn.execute("SELECT * FROM shares ORDER BY created_at DESC LIMIT 200").fetchall()
    shares = []
    for row in share_rows:
        d = dict(row)
        if d["revoked"]:
            d["status"] = "revoked"
        elif d["expires_at"] <= now:
            d["status"] = "expired"
        else:
            d["status"] = "live"
        shares.append(d)

    rooms = conn.execute(
        "SELECT * FROM room_sessions ORDER BY started_at DESC LIMIT 100"
    ).fetchall()

    conn.close()
    return render_template(
        "admin_stats.html",
        shares=shares,
        rooms=rooms,
        lastfm_configured=lastfm_client.is_configured(),
        lastfm_authorized=lastfm_client.is_authorized(),
        lastfm_username=lastfm_client.get_connected_username(),
        lastfm_active=lastfm_client.is_configured() and lastfm_client.is_authorized(),
        player_family=True,
    )


@bp.route("/lastfm/connect")
@admin_required
def lastfm_connect():
    if not lastfm_client.is_configured():
        return redirect(url_for("admin.stats"))
    # request.host_url, not url_for(..., _external=True) -- this app
    # sits behind a Cloudflare Tunnel, and _external=True depends on
    # Flask correctly inferring the public hostname through that
    # proxy, which isn't guaranteed. request.host_url is the same
    # safer pattern already used for password-reset emails and join
    # links elsewhere in this file.
    callback_url = request.host_url.rstrip("/") + url_for("admin.lastfm_callback")
    auth_url = lastfm_client.get_auth_url(callback_url)
    return redirect(auth_url)


@bp.route("/lastfm/callback")
@admin_required
def lastfm_callback():
    token = request.args.get("token")
    if not token:
        return redirect(url_for("admin.stats"))
    try:
        lastfm_client.complete_auth(token)
    except Exception:
        current_app.logger.exception("Failed to complete Last.fm auth")
    session.pop("lastfm_pending_token", None)
    return redirect(url_for("admin.stats"))


@bp.route("/lastfm/disconnect", methods=["POST"])
@admin_required
def lastfm_disconnect():
    lastfm_client.disconnect()
    return redirect(url_for("admin.stats"))


@bp.route("/stats/download/<kind>")
@admin_required
def stats_download(kind):
    if kind not in ("shares", "rooms"):
        return "Invalid export type.", 400

    conn = db.get_db()
    if kind == "shares":
        rows = conn.execute("SELECT * FROM shares ORDER BY created_at DESC").fetchall()
        columns = SHARE_CSV_COLUMNS
    else:
        rows = conn.execute("SELECT * FROM room_sessions ORDER BY started_at DESC").fetchall()
        columns = ROOM_CSV_COLUMNS
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[c] for c in columns])

    resp = Response(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename=musiclounge-{kind}.csv"
    return resp


@bp.route("/stats/clear", methods=["POST"])
@admin_required
def stats_clear():
    kind = request.form.get("kind")
    conn = db.get_db()
    now = datetime.utcnow().isoformat()
    if kind == "shares":
        conn.execute("DELETE FROM shares WHERE revoked = 1 OR expires_at <= ?", (now,))
    elif kind == "rooms":
        conn.execute("DELETE FROM room_sessions WHERE ended_by_admin = 1")
    conn.commit()
    conn.close()
    return redirect(url_for("admin.stats"))


@bp.route("/stats/end-room", methods=["POST"])
@admin_required
def stats_end_room():
    session_id = request.form.get("session_id")
    if session_id:
        db.end_room(session_id)
    return redirect(url_for("admin.stats"))


@bp.route("/stats/revoke-share", methods=["POST"])
@admin_required
def stats_revoke_share():
    token = request.form.get("token")
    if token:
        db.revoke_share(token)
    return redirect(url_for("admin.stats"))


@bp.route("/dashboard", methods=["GET", "POST"])
@admin_required
def dashboard():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "start":
            room_name = request.form.get("room_name", "").strip() or "My Lounge"
            db.create_room(room_name)
        elif action == "end":
            room = db.get_active_room()
            if room:
                db.end_room(room["session_id"])
        return redirect(url_for("admin.dashboard"))

    room = db.get_active_room()
    queue = db.get_queue(room["session_id"]) if room else []

    qr_data_uri = None
    join_url = None
    if room:
        join_url = request.host_url.rstrip("/") + url_for("room.join_by_code", code=room["join_code"])
        qr_img = qrcode.make(join_url, border=2)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    return render_template(
        "admin_dashboard.html",
        room=room,
        queue=queue,
        qr_data_uri=qr_data_uri,
        join_url=join_url,
        needs_audio_bar=bool(room),
        hide_bar_ui=bool(room),
        # player_family (and so the SPA persistent-playback zone) only
        # when no room is active yet -- the "no room running" state is
        # just a plain "Start a Room" form with no room-specific JS at
        # all, so it's safe to fold into the same zone Player/Browse/
        # Playlists already share, letting Player's own audio keep
        # playing while someone's just looking at this page rather
        # than committing to hosting. The moment a room actually
        # exists, this drops back to today's separate, full-page
        # behavior (server-authoritative audio, its own richer Now
        # Playing UI) -- no attempt to keep Player's audio going once
        # someone has actually committed to a room; see spa-nav.js's
        # data-player-family check, which falls back to a real
        # navigation exactly at this boundary.
        player_family=(room is None),
    )

def _send_tracks_to_room(tracks, room_name_if_new):
    """Shared by both routes below. Adds `tracks` (a list of track
    dicts) to whatever Room is currently active, creating one named
    `room_name_if_new` only if none is active -- this never silently
    ends/replaces an existing room (which could have real guests in
    it), it only ever adds to it. Matches db.create_room()'s own
    single-active-room design, just applied one level up: we CHECK
    for an active room first rather than always calling create_room()
    (which would itself end any existing one).

    Also promotes the first track to now_playing if nothing was
    already playing -- matches exactly what room.api_add_to_queue()
    does for a guest's own first add (see that route: it checks
    `if not room["now_playing_ref"]`, then pop_next() + set_now_playing()).
    Without this, tracks landed in the queue correctly but the Now
    Playing card stayed empty until a guest happened to add something
    themselves, which is what actually triggered the promotion."""
    room = db.get_active_room()
    was_empty_before = not room or not room["now_playing_ref"]
    if not room:
        db.create_room(room_name_if_new or "My Lounge")
        room = db.get_active_room()
    for track in tracks:
        # Defensive normalization -- some pages' currentTracks() reads
        # straight off DOM data-* attributes (rating_key/title/artist
        # only, no duration_sec, since it was never needed for
        # display there before this feature existed). Filling in a
        # safe default here is far simpler and lower-risk than
        # retrofitting duration_sec into every affected template's
        # markup for a value that was never actually needed until now.
        db.add_to_queue(room["session_id"], {
            "rating_key": track.get("rating_key"),
            "title": track.get("title", "Unknown Title"),
            "artist": track.get("artist", "Unknown Artist"),
            "duration_sec": track.get("duration_sec") or 0,
        })
    if was_empty_before:
        nxt = db.pop_next(room["session_id"])
        if nxt:
            db.set_now_playing(room["session_id"], db.queue_row_to_track(nxt), start_playing=False)
    return room


@bp.route("/room/send-content", methods=["POST"])
@admin_required
def room_send_content():
    """Powers the per-item "Start a Room with this" action on a
    track/playlist/album. Reuses get_content_tracks() -- the same
    resolver Share links already use -- so a track/album/playlist all
    correctly resolve to their real track list, capped at that
    function's existing 100-track safety limit (no separate 20-track
    cap here -- that cap is specifically for the queue-send case
    below, where a queue could have accumulated unintentionally large;
    a playlist/album the admin explicitly picked is a different,
    deliberate case)."""
    body = request.get_json(silent=True) or {}
    content_type = body.get("content_type")
    content_ref = body.get("content_ref")
    content_title = body.get("content_title", "")
    if content_type not in ("track", "album", "playlist"):
        return jsonify({"error": "Unsupported content type."}), 400
    try:
        _, _, tracks = plex_client.get_content_tracks(content_type, content_ref)
    except Exception:
        current_app.logger.exception("room_send_content failed type=%r ref=%r", content_type, content_ref)
        return jsonify({"error": "Couldn't load that content."}), 502
    if not tracks:
        return jsonify({"error": "No tracks found for that."}), 404
    _send_tracks_to_room(tracks, content_title)
    return jsonify({"ok": True, "redirect": url_for("admin.dashboard")})


@bp.route("/room/send-queue", methods=["POST"])
@admin_required
def room_send_queue():
    """Powers "Send Queue to Room" from the Queue popup. Tracks come
    directly from the client (MLPlayer.getQueue()) since a personal
    queue isn't a single Plex-addressable entity the server could
    resolve on its own, unlike send-content above. Capped at 20 --
    server-side, not just client-side -- per the original brainstorm:
    a queue could have accumulated unintentionally large, unlike a
    playlist/album the admin deliberately picked."""
    body = request.get_json(silent=True) or {}
    tracks = body.get("tracks", [])
    if not tracks:
        return jsonify({"error": "Queue is empty."}), 400
    tracks = tracks[:20]
    room_name = tracks[0].get("title", "My Lounge")
    _send_tracks_to_room(tracks, room_name)
    return jsonify({"ok": True, "redirect": url_for("admin.dashboard")})
