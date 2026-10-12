/*
 * MusicLounge Player -- Expanded "Now Playing" view.
 *
 * Opens when tapping the mini-bar's art/info area (not its individual
 * control buttons -- those still work independently). Shows large
 * album art, a real progress/scrub bar, and full transport controls.
 *
 * Reuses MLPlayer's existing public API for everything except prev/
 * next/queue, which forward-click the mini-bar's own hidden buttons
 * instead of duplicating that logic -- the same pattern already used
 * by /linked's own transport controls (see linked.html's prevTrack()/
 * nextTrack()), so this isn't a new pattern, just reapplied here.
 */
(function () {
  const overlay = document.getElementById("npx-overlay");
  const trigger = document.getElementById("np-expand-trigger");
  if (!overlay || !trigger) return;

  const art = document.getElementById("npx-art");
  const title = document.getElementById("npx-title");
  const artist = document.getElementById("npx-artist");
  const progress = document.getElementById("npx-progress");
  const elapsedEl = document.getElementById("npx-elapsed");
  const durationEl = document.getElementById("npx-duration");
  const shuffleBtn = document.getElementById("npx-shuffle");
  const prevBtn = document.getElementById("npx-prev");
  const playPauseBtn = document.getElementById("npx-playpause");
  const nextBtn = document.getElementById("npx-next");
  const queueBtn = document.getElementById("npx-queue");

  let isScrubbing = false;

  function formatTime(seconds) {
    if (!seconds || isNaN(seconds) || seconds < 0) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function renderTrack(track) {
    if (!track) return;
    title.textContent = track.title;
    artist.textContent = track.artist;
    art.src = `/art/${track.rating_key}`;
  }

  function open() {
    const current = MLPlayer.getCurrent();
    if (!current) return;
    renderTrack(current.track);
    playPauseBtn.classList.toggle("is-playing", !MLPlayer.isPaused());
    shuffleBtn.classList.toggle("np-shuffle-on", MLPlayer.isShuffleOn());
    overlay.hidden = false;
  }

  function close() {
    overlay.hidden = true;
  }

  trigger.addEventListener("click", open);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  MLPlayer.onChange(({ track, isPaused }) => {
    if (overlay.hidden) return;
    if (track) renderTrack(track);
    playPauseBtn.classList.toggle("is-playing", !isPaused);
    shuffleBtn.classList.toggle("np-shuffle-on", MLPlayer.isShuffleOn());
  });

  MLPlayer.onTimeUpdate(({ currentTime, duration }) => {
    if (overlay.hidden || isScrubbing) return;
    progress.max = duration || 0;
    progress.value = currentTime || 0;
    elapsedEl.textContent = formatTime(currentTime);
    durationEl.textContent = formatTime(duration);
  });

  progress.addEventListener("input", () => {
    isScrubbing = true;
    elapsedEl.textContent = formatTime(parseFloat(progress.value));
  });
  progress.addEventListener("change", () => {
    MLPlayer.seekTo(parseFloat(progress.value));
    isScrubbing = false;
  });

  playPauseBtn.addEventListener("click", () => {
    if (MLPlayer.isPaused()) MLPlayer.resume(); else MLPlayer.pause();
  });
  shuffleBtn.addEventListener("click", () => {
    MLPlayer.setShuffle(!MLPlayer.isShuffleOn());
    shuffleBtn.classList.toggle("np-shuffle-on", MLPlayer.isShuffleOn());
  });
  prevBtn.addEventListener("click", () => document.getElementById("np-prev").click());
  nextBtn.addEventListener("click", () => document.getElementById("np-next").click());
  queueBtn.addEventListener("click", () => {
    close();
    document.getElementById("np-queue-btn").click();
  });

  // --- More menu: reuses the shared track popover (room-share-menu.js) ---
  const shareBtn = document.getElementById("npx-share");
  if (shareBtn) {
    shareBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const cur = MLPlayer.getCurrent();
      if (!cur || !cur.track || typeof window.openRoomShareMenu !== "function") return;
      window.openRoomShareMenu(shareBtn, {
        type: "track",
        ref: cur.track.rating_key,
        title: cur.track.title,
        artist: cur.track.artist,
        compact: true
      });
    });
    // Items that navigate or open a modal need the overlay out of the way.
    document.addEventListener("click", (e) => {
      const it = e.target.closest(".room-share-popover-item");
      if (!it || overlay.hidden) return;
      if (["album", "artist", "addplaylist", "room", "share"].indexOf(it.dataset.action) !== -1) close();
    }, true);
  }
})();
