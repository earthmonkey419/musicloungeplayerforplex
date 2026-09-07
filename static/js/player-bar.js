/*
 * MusicLounge Player -- shared playback engine.
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
  let shuffleOrder = [];
  let shuffleHistory = [];
  let changeListeners = [];
  let endedListeners = [];
  let timeUpdateListeners = [];

  function notifyChange() {
    const current = getCurrent();
    changeListeners.forEach(cb => {
      try { cb({ track: current ? current.track : null, index: queueIndex, isPaused: audioEl.paused }); }
      catch (e) { console.error("MLPlayer onChange listener error:", e); }
    });
  }

  function updateNavButtons() {
    if (shuffleOn) {
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
    npPlayPause.textContent = (isPlayingIcon === false) ? "▶" : "⏸";
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
    playAt(index);
  }

  function removeFromQueue(index) {
    if (index < 0 || index >= queue.length) return;
    const wasCurrent = index === queueIndex;

    queue.splice(index, 1);
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
    if (!data || !Array.isArray(data.queue) || data.queue.length === 0) return;
    queue = data.queue.slice();
    const idx = data.current_index;
    queueIndex = (typeof idx === "number" && idx >= 0 && idx < queue.length) ? idx : 0;
    const track = queue[queueIndex];
    audioEl.src = `/stream/${track.rating_key}`;
    renderNowPlaying(track, false);
    updateNavButtons();
    notifyChange();
  }

  npPlayPause.addEventListener("click", () => {
    if (audioEl.paused) { audioEl.play(); npPlayPause.textContent = "⏸"; }
    else { audioEl.pause(); npPlayPause.textContent = "▶"; }
    notifyChange();
  });

  npPrev.addEventListener("click", goPrev);
  npNext.addEventListener("click", goNext);
  if (npShuffle) npShuffle.addEventListener("click", () => setShuffle(!shuffleOn));

  npVolume.addEventListener("input", () => { audioEl.volume = npVolume.value / 100; });
  audioEl.volume = npVolume.value / 100;

  audioEl.addEventListener("ended", () => {
    if (shuffleOn || queueIndex < queue.length - 1) {
      goNext();
    } else {
      npPlayPause.textContent = "▶";
      notifyChange();
    }
    endedListeners.forEach(cb => {
      try { cb(); } catch (e) { console.error("MLPlayer onEnded listener error:", e); }
    });
  });

  audioEl.addEventListener("timeupdate", () => {
    const current = getCurrent();
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

  function pause() { audioEl.pause(); npPlayPause.textContent = "▶"; notifyChange(); }
  function resume() { audioEl.play().catch(() => {}); npPlayPause.textContent = "⏸"; notifyChange(); }
  function isPaused() { return audioEl.paused; }

  function attemptAutoplay(track, onBlocked) {
    if (getCurrent() && getCurrent().track.rating_key === track.rating_key) {
      const p = audioEl.play();
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
    playTrack, playQueue, enqueue, pause, resume, isPaused,
    getCurrent, getQueue, rehydrate, setShuffle, isShuffleOn: () => shuffleOn,
    jumpTo, removeFromQueue, reorderQueue,
    onChange, onEnded, onTimeUpdate, attemptAutoplay,
  };
})();
