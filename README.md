<p align="center">
  <img src="static/og-image.jpg" alt="MusicLounge Player" width="480">
</p>

<h1 align="center">MusicLounge Player</h1>
<p align="center"><em>The full listening lounge for Plex — search, browse, and build playlists, just for you.</em></p>

---

MusicLounge Player is a self-hosted, browser-based music player for your own Plex music library. It's built to feel like a real app — persistent playback that survives navigation, a real queue, library browsing by artist and album, native + Plex-synced playlists, Last.fm scrobbling, and installable as a home-screen PWA on iOS/Android.

It also includes two social listening modes, launched right from the player:

- **Room Mode** — start a shared listening session; guests join by code and add to one shared queue, no accounts needed.
- **Share Mode** — send a track, album, artist, or playlist as a private, time-limited link.

**Status:** actively developed. Latest release: v2.3.0 — see [`CHANGELOG.md`](CHANGELOG.md) for what shipped and what's coming.

## Player vs. Jukebox (Lite)

MusicLounge Player is the recommended MusicLounge app, and the one new features
land in first. Its sibling, [MusicLounge Jukebox (Lite) for Plex](https://github.com/earthmonkey419/musiclounge),
is a pared-down option for when all you want is to start a room or send a link, with no
personal library browsing. Both are free, self-hosted, and share Room Mode and Share Mode,
and both use the same gapless playback engine. Player adds personal search and browse,
playlists, a persistent queue, radio, and more on top of that.

|                            | Player | Jukebox (Lite) |
| -------------------------- | :----: | :------------: |
| Personal search & browse   |   ✓    |       —        |
| Playlists (native + synced)|   ✓    |       —        |
| Personal queue & transport |   ✓    |       —        |
| Radio & mixes              |   ✓    |       —        |
| Room Mode                  |   ✓    |       ✓        |
| Share Mode                 |   ✓    |       ✓        |
| Gapless playback           |   ✓    |       ✓        |

Showcase site: [musicloungeplayer.vp-fun.com](https://musicloungeplayer.vp-fun.com)

## Features

- **Search** your whole library, with fast infinite-scroll results — album, artist, and playlist results appear as tile rows alongside the tracks when relevant. Results have Play All, Add to Queue, Play Next, and Add to Playlist buttons in the header
- **Browse** by Artist, Album, or Track, with sort (name, recently added, year, artist), plus an A-Z quickbar to jump straight to a letter in long lists. Mood and Genre pill rows (genres need MusicMind) filter the search page
- **Playlists** — build native playlists, or sync existing Plex playlists (synced ones stay read-only and always current)
- **Radio and mixes** — start a continuous station from any track or album (⋯ menu → Start Radio), or from the search page: **Random Radio**, **Library Radio** (random tracks from the whole library), **Album Radio** (random albums back to back, each in album order), and **Recently Added** (a shuffled mix of everything added in the last 14 days). Stations top themselves up as the queue runs low. Track and album radio use MusicMind's tag and audio-analysis similarity when connected, and fall back to Plex's sonic analysis otherwise; Library and Album Radio need neither
- **One shared "⋯" menu** on any track, album, or playlist — Play Next, Add to Queue, Add to Playlist, Start Radio, Start a Room, Share a Link, or (from a track) jump to its Album
- **Persistent queue** — survives page reloads and navigation, with a real editable queue view (reorder, remove, jump-to-track) that opens scrolled to what's playing
- **Gapless playback** between tracks, and **repeat** (off / all / one) on the player bar, remembered between visits
- **Recently Played**, logged automatically once a track has genuinely been listened to (skips don't count)
- **Expanded Now Playing view** — tap the mini-player for large art, a real scrub bar, full transport controls, and a proper side-by-side layout in landscape. The album name shows under the artist
- **Lock-screen and CarPlay controls** — real title, artist, album, and art through the Media Session API
- **Last.fm scrobbling** — connect once in Settings, then now-playing and scrobbles happen automatically
- **Room Mode** — shared queue, one now-playing, join by QR code or short code. The host can remove upcoming tracks from the queue; repeat is turned off in Rooms, since the server decides what plays next
- **Share Mode** — private links with configurable expiry, optional email delivery (with an embedded thumbnail). Recipients see the artist on every track and a Now Playing card, and can tap the album art to enlarge it
- **Installable PWA** — add to your phone's home screen for a real app icon and standalone (no browser chrome) experience
- **AirPlay support** on iOS — works out of the box via Safari's own audio route picker, no extra setup
- Persistent playback across navigation — the audio never stops just because you clicked something

## Screenshots

| Home | Browse | Playlists |
|:---:|:---:|:---:|
| <img src="docs/screenshots/home.jpg" width="240"> | <img src="docs/screenshots/browse-albums.jpg" width="240"> | <img src="docs/screenshots/playlists.jpg" width="240"> |

| Now Playing | Room (host view) | Share |
|:---:|:---:|:---:|
| <img src="docs/screenshots/now-playing.jpg" width="240"> | <img src="docs/screenshots/room-host.jpg" width="240"> | <img src="docs/screenshots/share.jpg" width="240"> |

## Tech stack

- **Backend:** Flask, gunicorn, SQLite (WAL mode)
- **Frontend:** Vanilla JS (no framework) — a shared playback engine (`MLPlayer`) used identically across every page, plus lightweight SPA-style navigation for uninterrupted playback within the Player/Playlists/Browse zone
- **Plex integration:** [python-plexapi](https://github.com/pkkid/python-plexapi)

## Requirements

- A running Plex Media Server with a Music library
- Python 3.12, **or** Docker/Docker Compose (Portainer-friendly)

## Getting started

### Option A — Docker / Portainer (recommended)

```bash
git clone https://github.com/earthmonkey419/musicloungeplayerforplex.git
cd musicloungeplayerforplex
cp .env.example .env
# edit .env -- at minimum set PLEX_URL, PLEX_TOKEN, ADMIN_PASSWORD, SECRET_KEY
docker compose up -d --build
```

The app will be available at `http://<host>:8680`. Config lives entirely in `.env` (see `.env.example` for every available setting, each documented) — nothing secret is baked into the image. Data (the SQLite database) persists in a named Docker volume across rebuilds.

For Portainer: create a new Stack pointing at this repo (or paste `docker-compose.yml` directly), and supply the same environment variables under the stack's environment section instead of a `.env` file.

### Option B — Manual (Python + gunicorn)

```bash
git clone https://github.com/earthmonkey419/musicloungeplayerforplex.git
cd musicloungeplayerforplex
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.py config.py
# edit config.py directly, or set the same values as environment variables
python init_db.py
gunicorn -w 1 --threads 4 --worker-class gthread -b 0.0.0.0:8680 app:app
```

A process manager (PM2, systemd, supervisord) is recommended for keeping it running — see `ecosystem.config.cjs` for a working PM2 example.

## Configuration

Every setting is documented in `config.example.py`. The essentials:

| Variable | What it's for |
|---|---|
| `PLEX_URL` | Your Plex server's URL (e.g. `http://192.168.1.x:32400`) |
| `PLEX_TOKEN` | A dedicated Plex token — create one with `python3 make_plex_token.py` (see below) |
| `MUSIC_LIB` | The name of your Music library in Plex |
| `ADMIN_PASSWORD` | The password for the single admin account this app uses |
| `SECRET_KEY` | Any long random string, used for session security |

Optional integrations (fully functional with nothing else configured; these just add more):

- **Last.fm scrobbling** — `LASTFM_API_KEY` / `LASTFM_API_SECRET` ([get a key](https://www.last.fm/api/account/create)), then connect your account once from Settings
- **MusicMind bridge** — `MUSICMIND_DB_PATH`, the path to [MusicMind for Plex](https://musicmind.vp-fun.com/)'s `musicmind.db`, an optional read-only companion database. Fully optional (everything falls back to live Plex queries with no missing functionality), but when connected it meaningfully accelerates search, mood/genre browsing, and Track browsing — MusicMind's own real genre data also powers the Genres pill row on the search page.
- **SMTP** — for emailing Share Mode links directly instead of just copying them

**Getting a Plex token (recommended):** give MusicLounge Player its own. On any
machine with Python (`pip install plexapi requests`, or inside the app's
venv), run `python3 make_plex_token.py` from the app folder, open the link it
prints, sign in to Plex and approve. It registers a device named "MusicLounge Player"
under Plex's Authorized Devices and prints the token to use as `PLEX_TOKEN`.
Add `--write` to have it update `config.py` and/or `.env` for you (the old
files are kept as `<name>.bak-<timestamp>`). Then restart the app
(`pm2 restart mlplayer`, or `docker compose up -d`).

Why not copy a token out of Plex Web? A token taken from the browser belongs
to that browser session and stops working the moment you sign out of it,
taking the app with it. Don't remove the "MusicLounge Player" entry from Authorized
Devices, and give each of your apps its own token. (Plex's
[manual guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) still works if you prefer.)

## Architecture notes

This is a single-admin, browser-based tool — there's no multi-user account system, by design. Anyone with the admin password has full access; anyone with a Room join code or Share link gets the scoped, guest-facing experience for that session only. Starting a Room and creating Share links both require the admin login. Recipients and Room guests don't log in.

Audio and cover art go through the app's own proxy, so your real Plex token never reaches a browser. `/stream/<id>` and `/art/<id>` don't answer anonymous requests: audio is limited to the admin and to tracks in a share link that browser has opened (checked against the live link on every request, so expiry and "End this link" cut it off immediately), and direct navigation to a stream URL is refused. This is access control, not DRM.

## Known limitations

- **Installed PWA + backgrounding:** if you add Player to your home screen (iOS) and background it mid-queue, the *current* track keeps playing, but it won't automatically advance to the next one until you bring the app back to the foreground — confirmed to be iOS suspending the installed PWA's JavaScript more aggressively than a regular browser tab (a plain Safari/Chrome tab doesn't have this gap). If gapless background listening through a long queue matters more to you than the home-screen app feel, use it as a regular browser tab instead.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

Part of the [Verbena Projects](https://vp-fun.com) family of Plex tools, alongside
[MusicLounge Jukebox (Lite) for Plex](https://github.com/earthmonkey419/musiclounge),
[MusicMind for Plex](https://musicmind.vp-fun.com/), and
[RiderMusic Jukebox for Plex](https://ridermusic.vp-fun.com/).
