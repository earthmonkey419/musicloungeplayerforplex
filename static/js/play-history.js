/*
 * MusicLounge Player -- play-history logging.
 *
 * Deliberately separate from player-bar.js (the engine itself stays
 * agnostic of this kind of business logic -- see its onTimeUpdate
 * doc comment). This script decides WHEN a play counts as "real"
 * (crossed 30 seconds, or half the track if it's shorter than a
 * minute) and logs it exactly once per track-play via
 * /api/player/log-play.
 *
 * Only included on Player's own pages (home, playlist detail) --
 * deliberately NOT on Room Mode's dashboard (driven by guests'
 * choices, not the admin's own listening) or /linked (a share
 * recipient's own session on their own device).
 */
(function () {
  const THRESHOLD_SECONDS = 30;

  let loggedForCurrentTrack = false;
  let lastTrackKey = null;

  MLPlayer.onChange(({ track }) => {
    const key = track ? track.rating_key : null;
    if (key !== lastTrackKey) {
      lastTrackKey = key;
      loggedForCurrentTrack = false;
    }
  });

  MLPlayer.onTimeUpdate(({ currentTime, duration, track }) => {
    if (!track || loggedForCurrentTrack) return;
    const threshold = duration > 0 ? Math.min(THRESHOLD_SECONDS, duration / 2) : THRESHOLD_SECONDS;
    if (currentTime >= threshold) {
      loggedForCurrentTrack = true;
      fetch("/api/player/log-play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rating_key: track.rating_key,
          title: track.title,
          artist: track.artist,
        }),
      }).catch(() => {});
    }
  });
})();
