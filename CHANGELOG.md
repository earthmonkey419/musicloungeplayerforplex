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
- Unified ⋯ menu: Start Room, Share Link, Go to Album, Play Next, Add to Playlist
- Album art thumbnail in Share emails
- Installable PWA (manifest, Apple meta tags, home-screen icon, standalone mode)
- Docker / Portainer support (Dockerfile, docker-compose.yml, `.env.example`)
- README with Docker and manual setup, plus in-app Help page (`/help`)
- MIT license

### Changed
- Room Mode now requires an explicit play to start instead of auto-playing on promotion
- Player audio keeps going while browsing Room pages until a room actually exists
- Clicking ▶ on a single track plays only that track instead of replacing the queue with the whole page
- Playlist search/import scoped to audio only
- Share Mode album and track search now use MusicMind first, falling back to live Plex (album search went from 24+ seconds to sub-second)
- Result caching and pagination for search, mood buckets, and browse
- Mobile playback controls redesigned with inline SVG icons (replacing emoji)
- Guest- and recipient-facing pages (Room dashboard, Share, Settings, login) re-themed to match the Player palette

### Fixed
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

## [1.0.0]

### Added
- Player shell with native and synced Plex playlists
- Playback, Room Mode and Share Mode integration
- MusicMind search bridge
