import secrets
import time
from datetime import datetime

from flask import Blueprint, render_template, current_app, request, session, jsonify

import db
import plex_client
import media_access

bp = Blueprint("linked", __name__)

# {share_token: (timestamp, {rating_key: "Title -- Artist"})}. Used only to
# snapshot a readable track title into each activity event, so history
# still reads properly after a track is removed from Plex.
_TITLES_TTL = 600
_titles_cache = {}


def _display_title(track):
    title = (track.get("title") or "").strip()
    artist = (track.get("artist") or "").strip()
    return f"{title} \u2014 {artist}" if title and artist else (title or artist)


def _remember_titles(token, tracks):
    _titles_cache[token] = (time.time(), {str(t["rating_key"]): _display_title(t) for t in tracks})


def _track_title(token, track_ref):
    hit = _titles_cache.get(token)
    if not hit or time.time() - hit[0] > _TITLES_TTL:
        share = db.get_share(token)
        try:
            _, _, tracks = plex_client.get_content_tracks(share["content_type"], share["content_ref"])
            _remember_titles(token, tracks)
        except Exception:
            return None
        hit = _titles_cache.get(token)
    return hit[1].get(str(track_ref)) if hit else None


def _expired_page(share_token):
    """The friendly page for a link that EXPIRED on its own (not one the host
    ended). Returns None for everything else -- revoked, unknown, or expired
    long ago -- which keeps getting the generic 404, so those still can't be
    told apart. Tokens are 256-bit random, so this reveals nothing to anyone
    who didn't already hold the link."""
    row = db.get_share(share_token)
    if not row or row["revoked"] or row["expires_at"] > datetime.utcnow().isoformat():
        return None
    if not db.expired_page_visible(row):
        return None
    keys = row.keys()
    return render_template(
        "link_expired.html",
        share=row,
        shared_by=(row["from_display_name"] or "").strip(),
        can_ask=("renewal_requested_at" in keys),
        already_asked=bool("renewal_requested_at" in keys and row["renewal_requested_at"]),
        token=share_token,
    )


@bp.route("/<share_token>")
def view_share(share_token):
    # Unknown, revoked and long-expired links all get the same bare 404 so
    # they can't be told apart. A link that expired recently on its own
    # gets a friendlier 410 that says so and lets the recipient ask for a
    # new one (see _expired_page).
    if not db.is_share_live(share_token):
        page = _expired_page(share_token)
        if page is not None:
            return page, 410
        return render_template("link_expired.html", share=None, shared_by="", can_ask=False,
                               already_asked=False, token=share_token), 404

    share = db.get_share(share_token)

    try:
        title, artist, tracks = plex_client.get_content_tracks(share["content_type"], share["content_ref"])
    except Exception:
        current_app.logger.exception("Linked view failed to load content for token=%r", share_token)
        # Degrade gracefully: show what we stored at share-creation time
        # rather than a hard failure, even if Plex is unreachable right now.
        title = share["content_title"]
        artist = share["content_artist"]
        tracks = []

    media_access.remember_share(share_token, share["content_ref"], tracks)
    _remember_titles(share_token, tracks)

    # Link-preview fetchers (iMessage, Slack, Facebook...) still get the
    # page -- they need the og: tags -- but never count as an open.
    if not db.is_bot_user_agent(request.headers.get("User-Agent", "")):
        db.record_share_access(share_token)
        # Random per-browser id, only ever stored hashed with the share
        # token (db.visitor_hash). Lets the host see unique visitors
        # without storing IPs.
        if "vid" not in session:
            session["vid"] = secrets.token_urlsafe(12)
        session.permanent = True

    return render_template(
        "linked.html",
        share=share,
        tracks=tracks,
        content_title=title,
        content_artist=artist,
        server_now=datetime.utcnow().isoformat(),
        grace_seconds=db.share_grace_seconds(),
        needs_audio_bar=True,
        hide_bar_ui=True,
    )


@bp.route("/<share_token>/request-renewal", methods=["POST"])
def request_renewal(share_token):
    """'Ask for a new link' on the expired page. Only flags the share for the
    host (no message, no contact details are taken from the visitor). Answers
    the same for 'flagged' and 'already flagged'; refuses anything that
    isn't a recently expired, un-revoked share with a plain 404."""
    if db.request_share_renewal(share_token):
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@bp.route("/<share_token>/event", methods=["POST"])
def share_event(share_token):
    """Activity beacon from the recipient's page: 'open', 'play_start' or
    'play_complete'. Always answers 204 (even when it drops the event) so
    the client has nothing to retry or learn from. Dropped silently when:
    the share is dead, this browser never opened the link, the client is
    a bot, the type is unknown, or a play event names a track that is not
    part of this share."""
    if not db.is_share_live(share_token):
        return "", 404
    if share_token not in session.get("share_tokens", []):
        return "", 204
    ua = request.headers.get("User-Agent", "")
    if db.is_bot_user_agent(ua) or "vid" not in session:
        return "", 204

    body = request.get_json(silent=True) or {}
    event_type = body.get("type")
    if event_type not in db.SHARE_EVENT_TYPES:
        return "", 204

    track_ref = None
    if event_type != "open":
        track_ref = str(body.get("track_ref") or "")
        if not track_ref or track_ref not in media_access._share_keys(share_token):
            return "", 204

    referrer = db.referrer_host(body.get("referrer", "")) if event_type == "open" else None
    db.record_share_event(
        share_token,
        event_type,
        db.visitor_hash(session["vid"], share_token),
        track_ref=track_ref,
        device=db.classify_device(ua),
        referrer=referrer,
        track_title=_track_title(share_token, track_ref) if track_ref else None,
    )
    return "", 204
