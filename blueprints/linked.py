import secrets
import time

from flask import Blueprint, render_template, current_app, request, session

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


@bp.route("/<share_token>")
def view_share(share_token):
    # Still a 404 whether the token is expired, revoked, or never
    # existed — never distinguish, per the scope doc's security
    # reasoning. Just a nicer page than Flask's bare default.
    if not db.is_share_live(share_token):
        return render_template("link_expired.html"), 404

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
        needs_audio_bar=True,
        hide_bar_ui=True,
    )


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
