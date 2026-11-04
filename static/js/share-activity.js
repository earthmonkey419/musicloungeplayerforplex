/*
 * MusicLounge Player -- share-link activity beacon (recipient side).
 *
 * Tells the server three things about a share link so the host can see
 * how it is being used: the page was opened, a track started, a track
 * (nearly) finished. Nothing identifies the person: the server derives
 * an anonymous per-browser hash itself.
 *
 * Only included on /linked. Deliberately NOT on Player's own pages or
 * Room Mode (those are the host's own listening and a party's guests).
 * Fire-and-forget: a failed beacon is never retried or surfaced.
 */
(function () {
  const url = location.pathname.replace(/\/+$/, "") + "/event";
  const COMPLETE_FRACTION = 0.9;   // "finished" = reached 90% of the track
  const MIN_PLAY_SECONDS = 3;      // ignore accidental taps / instant skips

  function send(payload) {
    try {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        keepalive: true,
        credentials: "same-origin",
      }).catch(() => {});
    } catch (e) { /* never break playback over analytics */ }
  }

  // Page open. Real browsers run this; most link-preview fetchers do not.
  send({ type: "open", referrer: document.referrer || "" });

  let currentKey = null;
  let startedLogged = false;
  let completeLogged = false;

  MLPlayer.onChange(({ track }) => {
    const key = track ? String(track.rating_key) : null;
    if (key !== currentKey) {
      currentKey = key;
      startedLogged = false;
      completeLogged = false;
    }
  });

  MLPlayer.onTimeUpdate(({ currentTime, duration, track }) => {
    if (!track) return;
    const ref = String(track.rating_key);
    if (!startedLogged && currentTime >= MIN_PLAY_SECONDS) {
      startedLogged = true;
      send({ type: "play_start", track_ref: ref });
    }
    if (!completeLogged && duration > 0 && currentTime >= duration * COMPLETE_FRACTION) {
      completeLogged = true;
      send({ type: "play_complete", track_ref: ref });
    }
  });
})();
