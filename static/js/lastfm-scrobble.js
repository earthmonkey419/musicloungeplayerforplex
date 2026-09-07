/*
 * MusicLounge Player -- Last.fm scrobbling.
 *
 * Last.fm's own official scrobble rule: a track must be at least 30
 * seconds long, and must be played for at least half its duration OR
 * 4 minutes, whichever comes first. "Now playing" updates fire once
 * per new track immediately (no threshold).
 */
(function () {
  const SCROBBLE_CAP_SECONDS = 240; // 4 minutes

  let nowPlayingSentFor = null;
  let scrobbledForCurrentTrack = false;
  let lastTrackKey = null;

  MLPlayer.onChange(({ track, isRehydration }) => {
    const key = track ? track.rating_key : null;
    if (key !== lastTrackKey) {
      lastTrackKey = key;
      if (isRehydration) {
        // This track was already playing before a page navigation --
        // not a genuine new listen. Don't re-send "now playing" (it
        // was already sent once), and don't let a fresh scrobble
        // timer start for it on this page: we have no way to know
        // how much of it was already heard before navigating, so a
        // second independent threshold-crossing here could produce a
        // duplicate scrobble. Known interim limitation until
        // persistent playback across navigation is built.
        scrobbledForCurrentTrack = true;
        return;
      }
      scrobbledForCurrentTrack = false;
      if (track && nowPlayingSentFor !== key) {
        nowPlayingSentFor = key;
        fetch("/api/player/lastfm/now-playing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ artist: track.artist, title: track.title }),
        }).catch(() => {});
      }
    }
  });

  MLPlayer.onTimeUpdate(({ currentTime, duration, track }) => {
    if (!track || scrobbledForCurrentTrack) return;
    if (duration < 30) return;
    const threshold = Math.min(duration / 2, SCROBBLE_CAP_SECONDS);
    if (currentTime >= threshold) {
      scrobbledForCurrentTrack = true;
      fetch("/api/player/lastfm/scrobble", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artist: track.artist, title: track.title }),
      }).catch(() => {});
    }
  });
})();
