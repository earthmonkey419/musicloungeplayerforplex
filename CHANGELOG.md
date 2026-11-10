# Changelog

All notable changes to MusicLounge Player for Plex are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Share pages show album information. A link to a single album (or to two or more tracks that all come from one album) gets an album header with the cover, title, artist, year, track count, runtime, genres and label when Plex has them, plus a collapsible **About this album** blurb when Plex has a summary; a partial selection reads "5 of 12 tracks". The artist is shown once in the header instead of on every row, except where a track's artist differs (compilations). Playlists and mixed shares keep the playlist layout, with the album and year shown under each track. Fields Plex doesn't have are simply left out

## [2.6.0] - 2026-11-10

### Added
- Share links can be renewed: every live or expired link in Settings now has an **Extend** / **Renew** control with the same durations used to create links. The link keeps its URL and all of its activity history, comes back out of the archive if it was archived, and never ends up with less time than it had. Links you ended (**End Link**) stay ended; create a new one instead
- Expired share links now show a friendly page (instead of a bare "not found") that names what was shared and who sent it, with an **Ask for a new link** button. Tapping it flags the link for you: it shows **ASKED FOR MORE TIME** in Settings until you renew it. The recipient sends no message and no details. This page only appears for links that expired on their own within the last 30 days; ended, unknown and long-expired links still get the plain not-found page, and the page answers 410 instead of 404 for an expired link
- Settings: live links within 6 hours of expiring show an **EXPIRING SOON** badge
- A **7 days** option for share links, shown as "7 days" when creating or renewing a link. It is `168` in `SHARE_LINK_DURATIONS_HOURS`, whose default is now `24,48,72,168`. If your `config.py` or environment sets that list explicitly, add `168` to it
- New optional `SHARE_EXPIRY_GRACE_MINUTES` setting (default 10; 0 = cut off at the exact moment of expiry)

### Changed
- When a share link expires while someone is listening, the track that is playing now finishes instead of cutting off mid-song, and then playback stops with an "expired" card offering **Ask for a new link**. Nothing after it starts. The server allows only tracks that browser had already started streaming, and only for the grace period; a link you End has no grace at all. The countdown on the recipient page now follows the server's clock, so a wrong device clock can't expire a link early or late
- Every share link still always has an expiry: links can only be created or renewed with the configured durations, never as permanent links
- The "pick a valid duration" message now lists your configured durations instead of a fixed 24/48/72 hours

### Upgrading
- Existing installs run `python3 migrate_share_renew.py` once (adds three columns to `shares`; safe to repeat). Until it has run, everything keeps working but the renew controls and **Ask for a new link** stay hidden. New installs get the columns from `init_db.py`

## [2.5.0] - 2026-11-09

### Added
- New music now shows up on its own. Player checks Plex every minute (a few tiny requests: track count, album count and newest album) and, as soon as a scan adds or removes music, rebuilds the Browse artist and album lists in the background and drops its cached search, mood and track-browse results. Previously the lists could take an hour or more to catch up, and needed a second visit after that
- Player also watches MusicMind's database the same way, so search, moods and track browse pick up new tracks within a minute of a MusicMind ingest finishing. Tag, play-count and analysis updates don't count as a change, so a long-running analysis won't keep clearing caches
- Settings: a **Library** card with a **Refresh library now** button and a status line (last check, last refresh and why). The button is for changes the automatic check can't see, such as re-tagged items
- After a restart, Player compares the library with what its saved lists were built from and refreshes them if music changed while it was down
- `LIBRARY_WATCH_INTERVAL` in `config.py` (seconds, default 60, minimum 15; `0` turns the automatic check off). No migration needed; copy the new setting from `config.example.py` if you want to change it

### Changed
- Several refresh requests arriving while a rebuild is already running now trigger one more rebuild afterwards instead of being ignored, so a scan that finishes mid-rebuild is not missed

### Fixed
- Settings: ending a share link (and archiving, restoring, deleting links, ending a room, clearing ended rooms) no longer reloads the whole page, so the playing track keeps playing
- Settings: the top link is now **← Back to Player** and moves within the app. It used to open the Rooms page (`/admin/dashboard`) with a full page load, which also stopped playback
- Settings: the Copy Link button no longer fires twice after the page content refreshes in place

## [2.4.2] - 2026-11-04

### Fixed
- Radio: stations no longer queue runs of tracks from the same artist or album. Each batch is reordered so neighbouring tracks differ by artist and album, and the opening queue of a Random Radio station is spread the same way
- Random Radio: stations are far more varied. Candidates are now drawn from a wide band of similar tracks instead of the strict top matches, with at most one track per artist per batch, and the starting tracks no longer repeat an artist. Refills keep the same behaviour. Track and Album Radio still stay tightly similar to the track you started from

## [2.4.1] - 2026-11-03

### Fixed
- Search: multi-word queries now work ("a love supreme", "john coltrane"); every word must match somewhere in the artist, title or album, with whole-phrase matches on artist, then title, then album ranked first
- Streaming: the proxy now closes its Plex connection when playback stops or the listener disconnects, uses timeouts, and answers 502 instead of hanging when Plex is unreachable
- Room guest page: starting a new search is no longer ignored while an earlier search is still loading

### Security
- Session cookie is now `SameSite=Lax`; every response carries `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`

## [2.4.0] - 2026-11-03

### Added
- Share-link activity for hosts: each share link records when it is opened and which tracks are started and finished, with link-preview bots (iMessage, Slack, Facebook, crawlers) filtered out. Visitors are counted with an anonymous per-browser hash, never an IP address, and the recipient page says the host can see this activity. New installs get the table from `init_db.py`; existing installs run `python3 migrate_share_events.py` and then `python3 migrate_share_archive.py` once
- Settings page: each share link now has an **Activity** button that expands opens, unique visitors, listeners, tracks started/finished (per track, with names), device and referrer mix, and an hourly timeline. The old "Plays" column is now "Opens", with a Listening column beside it, and the shares CSV export includes the activity totals
- Share-link history is kept: "Clear expired/revoked" is now **Archive expired/revoked**. Archived links are hidden from the list (use **Show archived**, with a Restore button) but keep all their activity. A separate **Delete…** button permanently removes a finished link and its history. Track names are saved with each play so old activity stays readable if a track later leaves Plex
- New optional `SHARE_EVENT_RETENTION_DAYS` setting (default 0 = keep activity forever)
- The album name now shows under the artist in the bottom player bar and in the expanded Now Playing view
- Two new station buttons on the search page: **Library Radio** (random tracks from the whole library) and **Album Radio** (random albums back to back, each in album order). Both are continuous like the other stations and work without MusicMind or Plex sonic analysis

### Changed
- After logging in you now land on the page you were trying to reach (e.g. Share Some Music) instead of always the dashboard, and the login screen says why it's asking

### Security
- Share Mode creation (the page, library search, link creation, and "Email It") now requires the host login, same as starting a Room. Previously these were reachable without logging in, so anyone who could reach the app could browse the library, mint links, and send email through your SMTP settings. Recipients' `/linked/<token>` pages are unaffected
- `/stream/<id>` and `/art/<id>` no longer answer anonymous requests, which previously let anyone walk track IDs and download the whole library through the proxy. Audio is now limited to the host and to tracks in a share link the browser has opened (checked against the live share on every request, so expiry and "End this link" cut it off immediately). Cover art is also available to guests in a live Room, and to anyone for the shared item's own cover (share emails and link previews need it). Direct navigation to a stream URL (the browser's "save" path) is refused. This is access control, not DRM
- Cover art is now cached `private` rather than `public`
- Streams are sent `Content-Disposition: inline`, `X-Content-Type-Options: nosniff` and `Cache-Control: private`

## [2.3.0] - 2026-10-24

### Added
- Artists and playlists now appear in the main search results (tile rows above and below the albums)
- Room host can remove upcoming tracks from the queue (✕ on each row of the dashboard queue)
- Share links: recipients now see the artist on every track, a Now Playing readout, and can tap the album art to enlarge it

### Fixed
- Share creation: picking a search result no longer fails for titles containing an apostrophe (e.g. "Sgt. Pepper's")

## [2.2.0] - 2026-10-22

### Changed
- Opening the queue now scrolls to the track that's playing, so it's easy to see what's coming up next

## [2.1.1] - 2026-10-18

### Fixed
- Shuffle on share-link pages stopped after one pass (a 2.1.0 regression); it now keeps looping there as before

## [2.1.0] - 2026-10-18

### Added
- Add to Queue and Play Next buttons in the results header, for both the Tracks and Albums sections (search, mood, tag and genre results). Albums resolve to their full tracklists, in the order the albums appear
- Repeat control (off / all / one) on the now-playing bar and the expanded Now Playing view. The mode is remembered between visits, and repeat loop points stay gapless. Repeat is ignored in Room Mode, where the server decides what plays next
- Gospel mood bucket, with tag exclusions
- "Powered by MusicLounge Player for Plex" link in the page footer

### Changed
- With repeat off, shuffle now plays through the queue once and stops, instead of reshuffling and looping indefinitely. Turn on repeat all to keep looping

## [2.0.0] - 2026-10-11

### Added
- Unified `MLPlayer` audio engine shared by Player, Playlists, Room Mode, and Share links
- Persistent playback across navigation (Player, Playlists, Browse); audio no longer stops when changing pages
- Editable queue view: remove, drag-reorder, jump-to-track, Add to Queue
- Play Next on tracks, albums, and playlists (shuffle-aware)
- Play All for search results and the Tracks browse tab; Play All Albums for matched-album results
- Bulk Add to Playlist from search results, album results, and album detail pages
- Recently Played history (threshold-based, so skips don't count)
- Expanded Now Playing view with large art, drag-to-seek, and full transport controls
- Media Session support: real title/artist/album/art and working controls on CarPlay, lock screens, and Bluetooth displays
- Last.fm scrobbling (connect flow, now-playing, scrobbles)
- Artists / Albums / Tracks browse with sorting and tracklist drill-down
- Genre browsing (top genres from MusicMind)
- A-Z quickbar on Artists, Albums, and Tracks browse pages
- Go to Album from any track row
- Album results in main Player search
- Unified ⋯ menu: Start Room, Share Link, Go to Album, Play Next, Add to Playlist, Start Radio
- Radio: continuous stations seeded from any track or album (⋯ menu → Start Radio); more tracks are added automatically as the queue runs low. Uses MusicMind's tag + Synapse similarity when available, falling back to Plex sonic analysis
- Random Radio button on the Player search page (random tag-based station; random mood station without MusicMind)
- Recently Added button on the Player search page: plays a shuffled mix of every track added to Plex in the last 14 days
- Album art thumbnail in Share emails
- Installable PWA (manifest, Apple meta tags, home-screen icon, standalone mode)
- Docker / Portainer support (Dockerfile, docker-compose.yml, `.env.example`)
- README with Docker and manual setup, plus in-app Help page (`/help`)
- MIT license
- Curated Moods pill row backed by real MusicMind mood/energy tags (replacing genre-mislabeled buttons like Funk/Soul/Jazz), with an honest "Genres" fallback label when MusicMind isn't available
- Horizontal-scroll layout for pill rows on narrow screens, matching Recently Added's existing scroll-arrow pattern
- Cache-busted static files: every `url_for('static')` link carries `?v=<mtime>` and is cached for a year, so deploys reach browsers and Cloudflare immediately
- Resized, cached cover art: `/art/<key>?w=128|300|600` uses Plex's photo transcoder with an in-process LRU cache and keep-alive connections to Plex
- Gapless playback: the next track is preloaded and handed off between two audio elements (`static/js/gapless.js`), removing the audible gap between tracks
- `make_plex_token.py`: generates a dedicated Plex token for the app instead of copying one from Plex Web
- Now Playing share menu, with Go to Artist, a copy-link fallback, and a Settings re-copy option

### Changed
- Previous (player bar, lock screen, CarPlay) now restarts the current track after 3 seconds, or when there is nothing earlier to go back to, instead of skipping back or being disabled; it stays enabled whenever a track is loaded, in both shuffle and non-shuffle modes
- Room Mode now requires an explicit play to start instead of auto-playing on promotion
- Player audio keeps going while browsing Room pages until a room actually exists
- Queue view now shows the true shuffle order (played, current, upcoming) while shuffle is on; drag-reorder is disabled in that view
- Home page Recently Added row loads 30 albums instead of 50
- Clicking ▶ on a single track plays only that track instead of replacing the queue with the whole page
- Playlist search/import scoped to audio only
- Share Mode album and track search now use MusicMind first, falling back to live Plex (album search went from 24+ seconds to sub-second)
- Result caching and pagination for search, mood buckets, and browse
- Mobile playback controls redesigned with inline SVG icons (replacing emoji)
- Guest- and recipient-facing pages (Room dashboard, Share, Settings, login) re-themed to match the Player palette

### Fixed
- Gapless playback (v3): a late play() rejection from a superseded track change could undo a newer swap or trigger false blocked-playback handling, and stray audio could sound on the idle element. Each start now carries a generation counter, and a periodic guard silences anything that is not the active element
- MusicMind fast path never activating (DB path pointed at a nonexistent file; all search/mood/browse had been using slow live-Plex fallbacks)
- Share track search silently missing real multi-word titles
- Search race condition where a slow earlier response could overwrite newer results (Player and Share)
- Room and Share links not playing audio
- Static JS/CSS cached at Cloudflare's edge for up to 4 hours after deploys; cache override now scoped to `/static/` so the art route keeps its long-lived cache for email previews
- Now-playing bar and Queue popup appearing on Share (`/linked`) and Room dashboard pages
- Mobile now-playing bar reverting to desktop sizing
- Expanded Now Playing controls cut off in landscape
- Track titles heavily truncated on mobile
- Mobile hamburger menu, overflowing mobile controls, SPA script redeclaration, album/artist art mismatch, and Last.fm scrobbles lost across navigation
- Compilation/VA album tracks showing "Various Artists" instead of the real per-track performer (track artist lookup preferred the album-level Plex tag over the track-level one)
- Real artist resolution (`COALESCE(real_artist, artist)`) now applied to search, mood, and tag lookups too, not just album detail and Radio -- VA compilation tracks were still showing "Various Artists" in search results and pill browsing
- Mood/tag pill results were fully random with no popularity bias -- added play_count-weighted shuffle so popular tracks surface more often without ever excluding anything
- Artist search treated "Mary J Blige" and "Mary J. Blige" as different artists -- periods are now normalized before matching
- Instrumental-only filter let borderline vocal tracks through -- now requires `vi_results.p_voice < 0.4`, not just the coarser `is_instrumental` flag

## [1.0.0]

### Added
- Player shell with native and synced Plex playlists
- Playback, Room Mode and Share Mode integration
- MusicMind search bridge
