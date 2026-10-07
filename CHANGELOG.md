# Changelog

All notable changes to MusicLounge Player for Plex are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

### Changed
- Previous (player bar, lock screen, CarPlay) now restarts the current track after 3 seconds, or when there is nothing earlier to go back to, instead of skipping back or being disabled; it stays enabled whenever a track is loaded, in both shuffle and non-shuffle modes
- Room Mode now requires an explicit play to start instead of auto-playing on promotion
- Player audio keeps going while browsing Room pages until a room actually exists
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
