(function () {
  const SCROBBLE_CAP_SECONDS = 240; // 4 minutes

  let nowPlayingSentFor = null;
  let scrobbledForCurrentTrack = false;
  let lastTrackKey = null;

  MLPlayer.onChange(({ track }) => {
    const key = track ? track.rating_key : null;
    if (key !== lastTrackKey) {
      lastTrackKey = key;
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
