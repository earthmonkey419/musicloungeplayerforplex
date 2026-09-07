/*
 * MusicLounge Player -- personal queue persistence.
 *
 * Deliberately separate from player-bar.js, same reasoning as
 * play-history.js: the engine stays agnostic of this kind of
 * business logic. This script:
 *   1. On page load, fetches the last-saved queue and rehydrates
 *      MLPlayer with it (paused, not auto-playing).
 *   2. On every queue/track change, debounces a save back to the
 *      server so a refresh never loses your place again.
 *
 * Only included on Player's own pages (home, playlist detail) --
 * deliberately NOT on Room Mode (its queue is server-authoritative
 * and shared across devices already -- a completely different, and
 * already-correct, design) or /linked (a share recipient's own
 * temporary session, not the admin's personal queue to overwrite).
 */
(function () {
  let saveTimer = null;

  function saveQueueDebounced() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const current = MLPlayer.getCurrent();
      fetch("/api/player/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          queue: MLPlayer.getQueue(),
          current_index: current ? current.index : -1,
        }),
      }).catch(() => {});
    }, 800);
  }

  MLPlayer.onChange(() => saveQueueDebounced());

  fetch("/api/player/queue")
    .then(r => r.json())
    .then(data => {
      if (data && Array.isArray(data.queue) && data.queue.length > 0) {
        MLPlayer.rehydrate(data);
      }
    })
    .catch(() => {});
})();
