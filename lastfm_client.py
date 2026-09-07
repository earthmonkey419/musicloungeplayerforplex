"""
Player -- optional Last.fm scrobbling integration.

Fully optional: if config.LASTFM_API_KEY/LASTFM_API_SECRET aren't set,
is_configured() is False and every call below is a safe no-op. Even
with credentials configured, scrobbling stays inactive until the
admin explicitly authorizes via Settings -- Last.fm's own "desktop
auth" flow, not standard OAuth:
  1. auth.getToken (unsigned) -- get a temporary token
  2. Send the admin to Last.fm's own site to approve that token
  3. auth.getSession (signed) -- exchange the approved token for a
     PERMANENT session key, which never expires until revoked
  4. Store that session key via db.set_config_value()

Signature algorithm: sort all params alphabetically by key,
concatenate as key1value1key2value2... (no separators, no encoding),
append the shared secret, MD5 hash the result. format and callback
are excluded from the signature base string.
"""
import hashlib
import time
from urllib.parse import quote

import requests

import config
import db

API_ROOT = "https://ws.audioscrobbler.com/2.0/"

_SESSION_KEY_CONFIG_KEY = "lastfm_session_key"
_USERNAME_CONFIG_KEY = "lastfm_username"


def is_configured():
    return bool(getattr(config, "LASTFM_API_KEY", "")) and bool(getattr(config, "LASTFM_API_SECRET", ""))


def is_authorized():
    return bool(db.get_config_value(_SESSION_KEY_CONFIG_KEY))


def get_connected_username():
    return db.get_config_value(_USERNAME_CONFIG_KEY)


def _sign(params):
    signable = {k: v for k, v in params.items() if k not in ("format", "callback")}
    base = "".join(f"{k}{signable[k]}" for k in sorted(signable.keys()))
    base += config.LASTFM_API_SECRET
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def _call(method, params, http_method="GET", signed=True):
    params = dict(params)
    params["method"] = method
    params["api_key"] = config.LASTFM_API_KEY
    if signed:
        params["api_sig"] = _sign(params)
    params["format"] = "json"

    if http_method == "GET":
        resp = requests.get(API_ROOT, params=params, timeout=6)
    else:
        resp = requests.post(API_ROOT, data=params, timeout=6)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Last.fm API error {data['error']}: {data.get('message')}")
    return data


def get_auth_url(callback_url):
    """Web-application auth flow: redirect straight to Last.fm with
    just api_key + cb (percent-encoded) -- Last.fm generates its own
    token and appends it to the redirect back to callback_url as
    ?token=X once the admin approves.

    Deliberately does NOT call auth.getToken first. That endpoint is
    documented as "non-web application authorization only" (the
    desktop-app flow) -- real-world testing confirmed that calling it
    first makes Last.fm treat the whole exchange as a desktop auth
    request that never redirects back, no matter what cb parameter or
    registered app callback URL is set. The actual web-app flow skips
    getToken entirely; Last.fm mints the token itself as part of the
    redirect."""
    auth_url = (
        f"https://www.last.fm/api/auth/?api_key={config.LASTFM_API_KEY}"
        f"&cb={quote(callback_url, safe='')}"
    )
    return auth_url


def complete_auth(token):
    data = _call("auth.getSession", {"token": token}, signed=True)
    session = data["session"]
    db.set_config_value(_SESSION_KEY_CONFIG_KEY, session["key"])
    db.set_config_value(_USERNAME_CONFIG_KEY, session["name"])
    return session["name"]


def disconnect():
    db.set_config_value(_SESSION_KEY_CONFIG_KEY, "")
    db.set_config_value(_USERNAME_CONFIG_KEY, "")


def update_now_playing(artist, title):
    """Does NOT swallow exceptions -- the calling route catches, logs,
    and returns a safe response, so failures are visible in the
    server logs instead of disappearing silently."""
    if not (is_configured() and is_authorized()):
        return
    _call("track.updateNowPlaying", {
        "artist": artist,
        "track": title,
        "sk": db.get_config_value(_SESSION_KEY_CONFIG_KEY),
    }, http_method="POST", signed=True)


def scrobble(artist, title, timestamp=None):
    """Same logging contract as update_now_playing() above."""
    if not (is_configured() and is_authorized()):
        return
    _call("track.scrobble", {
        "artist": artist,
        "track": title,
        "timestamp": timestamp or int(time.time()),
        "sk": db.get_config_value(_SESSION_KEY_CONFIG_KEY),
    }, http_method="POST", signed=True)
