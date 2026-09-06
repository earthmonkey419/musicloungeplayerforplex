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

  let queue = [];
  let queueIndex = -1;

  function updateNavButtons() {
    npPrev.disabled = queueIndex <= 0;
    npNext.disabled = queueIndex >= queue.length - 1;
  }

  function renderNowPlaying(track) {
    nowPlayingBar.hidden = false;
    npTitle.textContent = track.title;
    npArtist.textContent = track.artist;
    npArt.src = `/art/${track.rating_key}`;
    npPlayPause.textContent = "⏸";
  }

  function playAt(index) {
    if (index < 0 || index >= queue.length) return;
    queueIndex = index;
    const track = queue[queueIndex];
    audioEl.src = `/stream/${track.rating_key}`;
    audioEl.play();
    renderNowPlaying(track);
    updateNavButtons();
  }

  function playQueue(tracks, startIndex) {
    queue = tracks.slice();
    playAt(startIndex || 0);
  }

  function playTrack(track) {
    playQueue([track], 0);
  }

  npPlayPause.addEventListener("click", () => {
    if (audioEl.paused) {
      audioEl.play();
      npPlayPause.textContent = "⏸";
    } else {
      audioEl.pause();
      npPlayPause.textContent = "▶";
    }
  });

  npPrev.addEventListener("click", () => playAt(queueIndex - 1));
  npNext.addEventListener("click", () => playAt(queueIndex + 1));

  npVolume.addEventListener("input", () => { audioEl.volume = npVolume.value / 100; });
  audioEl.volume = npVolume.value / 100;

  audioEl.addEventListener("ended", () => {
    if (queueIndex < queue.length - 1) {
      playAt(queueIndex + 1);
    } else {
      npPlayPause.textContent = "▶";
    }
  });

  return { playTrack, playQueue };
})();
