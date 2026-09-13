"""
MusicLounge Player -- app entrypoint.

Route map:
  /                    Player shell -- search, browse, playlists,
                       personal transport (the new default view)
  /playlists           Native + Plex-synced playlist management
  /admin/login         shared admin auth (reused unchanged)
  /admin/dashboard     Room Mode host view -- launched FROM Player via
                       a link, renders under this same domain, no
                       redirect to musiclounge.vp-fun.com
  /admin/share         Share Mode admin flow -- likewise launched from
                       Player, same domain
  /join                Room Mode guest join (QR/code -> room) --
                       guests of a Room hosted from mlplayer land here
  /guest               Room Mode guest portal (search/browse/queue)
  /linked/<token>      Share Mode recipient view -- locked player
  /browse              Library browsing -- Artists -> Albums -> Tracklist

Room Mode + Share Mode + Linked + Admin are reused as code from the
musiclounge repo, unchanged -- see MUSICLOUNGE-PLAYER-V1-SCOPE.md.
Each deployment (musiclounge.vp-fun.com and mlplayer.vp-fun.com) runs
its own independent instance/DB of this code; they don't talk to
each other at runtime.
"""
from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timedelta
import config


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SESSION_COOKIE_SECURE"] = config.COOKIE_SECURE
    # Bounds "Stay logged in" (see admin.login()) -- only sessions
    # explicitly marked session.permanent = True use this lifetime at
    # all; a normal login without the checkbox stays a browser-session
    # cookie as before (gone when the browser closes), unaffected by
    # this setting. 30 days, not indefinite, so a lost/stolen device
    # eventually times out on its own even if nobody notices.
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    @app.context_processor
    def inject_globals():
        return {"current_year": datetime.utcnow().year}

    from blueprints.player import bp as player_bp
    from blueprints.playlists import bp as playlists_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.room import bp as room_bp
    from blueprints.share import bp as share_bp
    from blueprints.linked import bp as linked_bp
    from blueprints.browse import bp as browse_bp

    app.register_blueprint(player_bp)                          # "/" -- Player is the default view
    app.register_blueprint(playlists_bp, url_prefix="/playlists")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(room_bp)                             # unprefixed, unchanged -- guest join/api/art/stream
    app.register_blueprint(share_bp, url_prefix="/admin/share")
    app.register_blueprint(linked_bp, url_prefix="/linked")
    app.register_blueprint(browse_bp, url_prefix="/browse")

    @app.after_request
    def no_store(response):
        # Scoped to /static/ specifically now, not fully unconditional
        # anymore -- an earlier version of this fix applied
        # unconditionally to EVERY response, which fixed the original
        # problem (Flask's own default Cache-Control: max-age=14400 on
        # static JS/CSS meant deploys could take 4 hours to actually
        # reach a browser, confirmed via cf-cache-status: REVALIDATED)
        # but broke something else: it also silently overwrote
        # room.art()'s own deliberate Cache-Control: public,
        # max-age=86400, which Share's email thumbnails depend on --
        # email clients' link-preview crawlers generally need a real,
        # cacheable directive to reliably fetch and display a preview
        # image, and got no-store instead. Confirmed directly:
        # /art/<rating_key> was returning no-store despite explicitly
        # setting its own header, silently breaking Share email
        # thumbnails as a result. Static files still need the forced
        # override (Flask sets their Cache-Control before any route
        # code runs, so there's no "route deliberately chose this"
        # signal to respect there); every other route's own explicit
        # Cache-Control is now left alone.
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        elif "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT)
