/*
 * MusicLounge Player -- shared playback engine.
 *
 * This used to be Player's own thing while Room Mode and Share links
 * each ran their own separate, bespoke <audio> element and transport
 * JS -- three different audio implementations in one app. This is
 * the single shared one, used everywhere: Player, Playlists, Room
 * Mode's dashboard, and Share's /linked page.
 *
 * Public API:
 *   MLPlayer.playTrack(track)
 *   MLPlayer.playQueue(tracks, startIndex)
 *   MLPlayer.pause()
 *   MLPlayer.resume()
 *   MLPlayer.isPaused()
 *   MLPlayer.getCurrent()          -> {track, index, queueLength} | null
 *   MLPlayer.setShuffle(bool)
 *   MLPlayer.isShuffleOn()
 *   MLPlayer.onChange(callback)    -> callback({track, index, isPaused})
 *                                     fires on every play/pause/track
 *                                     change, for pages with their own
 *                                     additional now-playing display
 *                                     (Room's big card, /linked's
 *                                     track-row highlighting) to stay
 *                                     in sync with the shared bar.
 *   MLPlayer.attemptAutoplay(track, onBlocked)
 *                                     Room-specific need: resuming
 *                                     playback on page load/poll
 *                                     without a fresh user gesture,
 *                                     which browsers may block. Calls
 *                                     onBlocked() if so, so the page
 *                                     can show a "tap to start" banner.
 *
 * Shuffle uses the same Fisher-Yates-queue-plus-history approach
 * proven in the original /linked player: a shuffled order is built
 * once, tracks are popped off it as they play, and a history stack
 * makes "previous" work correctly even while shuffled.
 *
 * Requires templates/partials/_now_playing_bar.html to be included
 * on the page before this script runs.
 */
window.MLPlayer = (function () {
  const audioEl = document.getElementById("audio-el");
  const nowPlayingBar = document.getElementById("now-playing-bar");
  const npTitle = document.getElementById("np-title");
  const npArtist = document.getElementById("np-artist");
  const npArt = document.getElementById("np-art");
  const npPlayPause = document.getElementById("np-playpause");
  const npVolume = document.getElementById("np-volume");
  const npPrev = document.getElementById("np-prev");
  const npNext = document.getElementById("np-next");
  const npShuffle = document.getElementById("np-shuffle");

  let queue = [];
  let queueIndex = -1;
  let shuffleOn = false;
  let shuffleOrder = [];   // remaining shuffled indices, popped as played
  let shuffleHistory = []; // indices played while shuffled, for "prev"
  let changeListeners = [];
  let endedListeners = [];
  let timeUpdateListeners = [];

  function notifyChange(isRehydration) {
    const current = getCurrent();
    changeListeners.forEach(cb => {
      try { cb({ track: current ? current.track : null, index: queueIndex, isPaused: audioEl.paused, isRehydration: !!isRehydration }); }
      catch (e) { console.error("MLPlayer onChange listener error:", e); }
    });
  }

  function updateNavButtons() {
    if (shuffleOn) {
      // With shuffle on, "prev" is valid whenever there's history,
      // "next" is valid whenever there's more queue left (or it can
      // reshuffle once exhausted) -- not simply index-based.
      npPrev.disabled = shuffleHistory.length === 0;
      npNext.disabled = queue.length <= 1;
    } else {
      npPrev.disabled = queueIndex <= 0;
      npNext.disabled = queueIndex >= queue.length - 1;
    }
  }

  function renderNowPlaying(track, isPlayingIcon) {
    nowPlayingBar.hidden = false;
    npTitle.textContent = track.title;
    npArtist.textContent = track.artist;
    npArt.src = `/art/${track.rating_key}`;
    npPlayPause.classList.toggle("is-playing", isPlayingIcon !== false);
    updateMediaSessionMetadata(track);
    updateMediaSessionPlaybackState();
  }

  function updateMediaSessionMetadata(track) {
    // Feeds the OS-level media surfaces -- CarPlay, lock screen,
    // Bluetooth car displays, Control Center -- with real track info.
    // Without this, those surfaces fall back to guessing from
    // whatever scraps are available (often showing "No Artist Info"
    // and a garbled title, which is exactly what CarPlay showed
    // before this existed).
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title || "",
      artist: track.artist || "",
      album: track.album || "",
      artwork: [{ src: `/art/${track.rating_key}`, sizes: "512x512", type: "image/jpeg" }],
    });
  }

  function updateMediaSessionPlaybackState() {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = audioEl.paused ? "paused" : "playing";
  }

  function rebuildShuffleOrder() {
    shuffleOrder = queue.map((_, i) => i).filter(i => i !== queueIndex);
    for (let i = shuffleOrder.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffleOrder[i], shuffleOrder[j]] = [shuffleOrder[j], shuffleOrder[i]];
    }
  }

  function playAt(index, fromShuffleAdvance) {
    if (index < 0 || index >= queue.length) return;

    if (shuffleOn && !fromShuffleAdvance) {
      if (queueIndex !== -1) shuffleHistory.push(queueIndex);
      const pos = shuffleOrder.indexOf(index);
      if (pos !== -1) shuffleOrder.splice(pos, 1);
    }

    queueIndex = index;
    const track = queue[queueIndex];
    audioEl.src = `/stream/${track.rating_key}`;
    audioEl.play().catch(() => {});
    renderNowPlaying(track);
    updateNavButtons();
    notifyChange();
  }

  function playQueue(tracks, startIndex) {
    queue = tracks.slice();
    shuffleHistory = [];
    if (shuffleOn) rebuildShuffleOrder();
    playAt(startIndex || 0);
  }

  function enqueue(track) {
    // Appends without interrupting whatever's currently playing --
    // distinct from playQueue()/playTrack(), which replace the queue
    // and start playback immediately. If nothing is loaded at all
    // (fresh page, nothing played yet), there's nothing to append
    // to -- just start playing it instead of silently doing nothing.
    queue.push(track);
    if (shuffleOn) shuffleOrder.push(queue.length - 1);
    if (queueIndex === -1) {
      playAt(queue.length - 1, true);
    } else {
      updateNavButtons();
    }
  }

  function playTrack(track) {
    playQueue([track], 0);
  }

  function jumpTo(index) {
    // Manual selection from the queue view -- goes through the normal
    // playAt() path (pushes shuffle history, removes from shuffle
    // order) rather than the "fromShuffleAdvance" shortcut, since this
    // is a deliberate pick, not an automatic advance.
    playAt(index);
  }

  function removeFromQueue(index) {
    if (index < 0 || index >= queue.length) return;
    const wasCurrent = index === queueIndex;

    queue.splice(index, 1);
    // Shuffle bookkeeping: drop the removed index, shift anything
    // after it down by one so the remaining indices still point at
    // the right tracks post-splice.
    shuffleOrder = shuffleOrder.filter(i => i !== index).map(i => i > index ? i - 1 : i);
    shuffleHistory = shuffleHistory.filter(i => i !== index).map(i => i > index ? i - 1 : i);

    if (wasCurrent) {
      if (queue.length === 0) {
        queueIndex = -1;
        audioEl.pause();
        audioEl.removeAttribute("src");
        nowPlayingBar.hidden = true;
        notifyChange();
      } else {
        // Whatever now occupies this same position is the natural
        // "next" track -- advance into it. Clamp in case the removed
        // track was the last one in the queue.
        playAt(Math.min(index, queue.length - 1), true);
      }
    } else {
      if (index < queueIndex) queueIndex -= 1;
      updateNavButtons();
      notifyChange();
    }
  }

  function reorderQueue(fromIndex, toIndex) {
    if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= queue.length) return;
    toIndex = Math.max(0, Math.min(toIndex, queue.length - 1));

    const [moved] = queue.splice(fromIndex, 1);
    queue.splice(toIndex, 0, moved);

    // Keep queueIndex pointing at the same TRACK (the one actually
    // playing), not the same numeric slot, as things shift around it.
    // NOTE: shuffleOrder/shuffleHistory are deliberately NOT remapped
    // here -- reordering while shuffled may leave the remaining
    // shuffle order slightly stale (pointing at a still-valid but not
    // perfectly repositioned set of upcoming tracks). Acceptable v1
    // limitation: it can't point at the wrong track or crash, worst
    // case is a slightly different remaining shuffle order than a
    // full rebuild would produce.
    if (queueIndex === fromIndex) {
      queueIndex = toIndex;
    } else if (fromIndex < queueIndex && toIndex >= queueIndex) {
      queueIndex -= 1;
    } else if (fromIndex > queueIndex && toIndex <= queueIndex) {
      queueIndex += 1;
    }

    updateNavButtons();
    notifyChange();
  }

  function goNext() {
    if (shuffleOn) {
      if (queueIndex !== -1) shuffleHistory.push(queueIndex);
      if (shuffleOrder.length === 0) {
        rebuildShuffleOrder();
        if (shuffleOrder.length === 0) return;
      }
      const next = shuffleOrder.shift();
      playAt(next, true);
    } else {
      playAt(queueIndex + 1);
    }
  }

  function goPrev() {
    if (shuffleOn) {
      if (shuffleHistory.length > 0) {
        const prev = shuffleHistory.pop();
        playAt(prev, true);
      }
    } else {
      playAt(queueIndex - 1);
    }
  }

  function setShuffle(on) {
    shuffleOn = on;
    if (npShuffle) npShuffle.classList.toggle("np-shuffle-on", shuffleOn);
    if (shuffleOn) {
      shuffleHistory = [];
      rebuildShuffleOrder();
    }
    updateNavButtons();
  }

  function getCurrent() {
    if (queueIndex === -1 || !queue[queueIndex]) return null;
    return { track: queue[queueIndex], index: queueIndex, queueLength: queue.length };
  }

  function getQueue() {
    return queue.slice();
  }

  function rehydrate(data) {
    // Restores a previously-saved queue (see static/js/player-queue-sync.js)
    // without auto-playing -- avoids autoplay-blocked issues entirely,
    // and avoids surprising audio starting the moment a page loads.
    // The track loads and shows in the bar, paused, ready for the
    // user's own tap to resume.
    //
    // notifyChange(true) marks this as a rehydration, not a genuine
    // new track start -- lastfm-scrobble.js and similar consumers use
    // this to avoid re-sending "now playing"/re-scrobbling a track
    // that was already playing before navigation, which previously
    // caused duplicate now-playing updates and inconsistent-looking
    // scrobbles whenever the admin navigated between Player pages
    // mid-track.
    if (!data || !Array.isArray(data.queue) || data.queue.length === 0) return;
    queue = data.queue.slice();
    const idx = data.current_index;
    queueIndex = (typeof idx === "number" && idx >= 0 && idx < queue.length) ? idx : 0;
    const track = queue[queueIndex];
    audioEl.src = `/stream/${track.rating_key}`;
    renderNowPlaying(track, false);
    updateNavButtons();
    notifyChange(true);
  }

  npPlayPause.addEventListener("click", () => {
    if (audioEl.paused) { audioEl.play(); npPlayPause.classList.add("is-playing"); }
    else { audioEl.pause(); npPlayPause.classList.remove("is-playing"); }
    updateMediaSessionPlaybackState();
    notifyChange();
  });

  npPrev.addEventListener("click", goPrev);
  npNext.addEventListener("click", goNext);
  if (npShuffle) npShuffle.addEventListener("click", () => setShuffle(!shuffleOn));

  if ("mediaSession" in navigator) {
    // Lets CarPlay/lock-screen/Bluetooth car displays' own transport
    // controls actually drive playback here, same as the in-page
    // buttons already do.
    navigator.mediaSession.setActionHandler("play", () => resume());
    navigator.mediaSession.setActionHandler("pause", () => pause());
    navigator.mediaSession.setActionHandler("previoustrack", () => goPrev());
    navigator.mediaSession.setActionHandler("nexttrack", () => goNext());
    navigator.mediaSession.setActionHandler("seekto", (details) => {
      if (typeof details.seekTime === "number") seekTo(details.seekTime);
    });
  }

  npVolume.addEventListener("input", () => { audioEl.volume = npVolume.value / 100; });
  audioEl.volume = npVolume.value / 100;

  audioEl.addEventListener("ended", () => {
    // Internal auto-advance for local-queue usage (Player, Playlists,
    // /linked). Room Mode's "queue" is server-authoritative, not a
    // local array -- attemptAutoplay() always sets a one-track queue,
    // so this is naturally a no-op there (nothing to advance to).
    if (shuffleOn || queueIndex < queue.length - 1) {
      goNext();
    } else {
      npPlayPause.classList.remove("is-playing");
      updateMediaSessionPlaybackState();
      notifyChange();
    }
    // Separate hook for pages that need to react to natural
    // end-of-track regardless of local queue state -- Room Mode uses
    // this to ask the server for the next track.
    endedListeners.forEach(cb => {
      try { cb(); } catch (e) { console.error("MLPlayer onEnded listener error:", e); }
    });
  });

  audioEl.addEventListener("timeupdate", () => {
    const current = getCurrent();
    if ("mediaSession" in navigator && "setPositionState" in navigator.mediaSession) {
      const duration = audioEl.duration;
      if (duration && isFinite(duration) && duration > 0) {
        try {
          navigator.mediaSession.setPositionState({
            duration: duration,
            playbackRate: audioEl.playbackRate || 1,
            position: Math.min(audioEl.currentTime, duration),
          });
        } catch (e) { /* invalid state (e.g. mid-track-swap) -- safe to skip a frame */ }
      }
    }
    timeUpdateListeners.forEach(cb => {
      try {
        cb({
          currentTime: audioEl.currentTime,
          duration: audioEl.duration || 0,
          track: current ? current.track : null,
        });
      } catch (e) { console.error("MLPlayer onTimeUpdate listener error:", e); }
    });
  });

  function pause() { audioEl.pause(); npPlayPause.classList.remove("is-playing"); updateMediaSessionPlaybackState(); notifyChange(); }
  function resume() { audioEl.play().catch(() => {}); npPlayPause.classList.add("is-playing"); updateMediaSessionPlaybackState(); notifyChange(); }
  function isPaused() { return audioEl.paused; }

  function seekTo(seconds) {
    if (!audioEl.duration || isNaN(audioEl.duration)) return;
    audioEl.currentTime = Math.max(0, Math.min(seconds, audioEl.duration));
  }

  function attemptAutoplay(track, onBlocked) {
    // Room Mode's specific need: resuming playback on page load or on
    // a poll-detected track change, without a fresh user gesture.
    // Browsers may block this -- the caller shows a "tap to start"
    // banner if so, same UX the original Room dashboard already had.
    if (getCurrent() && getCurrent().track.rating_key === track.rating_key) {
      // Already the current track (e.g. a poll re-confirming state) --
      // just try to resume if paused, don't reload the source.
      const p = audioEl.play();
      updateMediaSessionPlaybackState();
      if (p !== undefined) p.catch(() => { if (onBlocked) onBlocked(); });
      return;
    }
    queue = [track];
    queueIndex = 0;
    audioEl.src = `/stream/${track.rating_key}`;
    const p = audioEl.play();
    renderNowPlaying(track);
    updateNavButtons();
    notifyChange();
    if (p !== undefined) p.catch(() => { if (onBlocked) onBlocked(); });
  }

  function onChange(callback) {
    changeListeners.push(callback);
  }

  function onEnded(callback) {
    endedListeners.push(callback);
  }

  function onTimeUpdate(callback) {
    timeUpdateListeners.push(callback);
  }

  return {
    playTrack, playQueue, enqueue, pause, resume, isPaused, seekTo,
    getCurrent, getQueue, rehydrate, setShuffle, isShuffleOn: () => shuffleOn,
    jumpTo, removeFromQueue, reorderQueue,
    onChange, onEnded, onTimeUpdate, attemptAutoplay,
  };
})();
