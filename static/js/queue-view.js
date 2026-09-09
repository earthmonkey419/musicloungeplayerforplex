/*
 * MusicLounge Player -- queue view.
 *
 * Wires up the Queue button/modal markup from
 * partials/_now_playing_bar.html. Kept as its own file (not inline in
 * that partial) because the partial is included BEFORE player-bar.js
 * loads (it has to be -- player-bar.js's own script needs the
 * <audio id="audio-el"> element to already exist in the DOM when it
 * runs). Putting MLPlayer-dependent logic inline in the partial would
 * reference MLPlayer before it exists. This file loads after
 * player-bar.js instead, same as play-history.js and
 * player-queue-sync.js.
 */
(function () {
  const btn = document.getElementById("np-queue-btn");
  const modal = document.getElementById("queue-modal");
  const list = document.getElementById("queue-modal-list");
  const closeBtn = document.getElementById("queue-modal-close");
  const clearBtn = document.getElementById("queue-modal-clear");
  const sendToRoomBtn = document.getElementById("queue-send-to-room");
  if (!btn || !modal || typeof MLPlayer === "undefined") return;

  function renderQueueModal() {
    const queue = MLPlayer.getQueue();
    const current = MLPlayer.getCurrent();
    const currentIndex = current ? current.index : -1;
    list.innerHTML = "";

    if (queue.length === 0) {
      list.innerHTML = '<li class="empty">Queue is empty.</li>';
      return;
    }

    queue.forEach((t, i) => {
      const li = document.createElement("li");
      li.className = "track-row" + (i === currentIndex ? " queue-modal-current" : "");
      li.draggable = true;
      li.dataset.index = i;
      li.innerHTML = `
        <span class="track-drag-handle" title="Drag to reorder">⋮⋮</span>
        <img class="track-art" src="/art/${t.rating_key}" alt="">
        <div class="track-meta">
          <div class="track-title">${i === currentIndex ? "▶ " : ""}${t.title}</div>
          <div class="track-artist">${t.artist}</div>
        </div>
        <button class="track-remove" title="Remove from queue">✕</button>
      `;
      li.addEventListener("click", (e) => {
        if (e.target.closest(".track-remove") || e.target.closest(".track-drag-handle")) return;
        MLPlayer.jumpTo(i);
        renderQueueModal();
      });
      li.querySelector(".track-remove").addEventListener("click", (e) => {
        e.stopPropagation();
        MLPlayer.removeFromQueue(i);
        renderQueueModal();
      });
      list.appendChild(li);
    });

    wireDragReorder();
  }

  function wireDragReorder() {
    let draggedIndex = null;
    list.querySelectorAll(".track-row").forEach(row => {
      row.addEventListener("dragstart", () => {
        draggedIndex = parseInt(row.dataset.index, 10);
        row.classList.add("dragging");
      });
      row.addEventListener("dragend", () => row.classList.remove("dragging"));
      row.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (draggedIndex === null) return;
        const targetIndex = parseInt(row.dataset.index, 10);
        if (targetIndex === draggedIndex) return;
        MLPlayer.reorderQueue(draggedIndex, targetIndex);
        draggedIndex = targetIndex;
        renderQueueModal();
      });
    });
  }

  btn.addEventListener("click", () => {
    renderQueueModal();
    modal.hidden = false;
  });
  closeBtn.addEventListener("click", () => { modal.hidden = true; });
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.hidden = true; });
  clearBtn.addEventListener("click", () => {
    if (MLPlayer.getQueue().length === 0) return;
    if (!confirm("Clear the entire queue? This stops playback too.")) return;
    MLPlayer.clearQueue();
    renderQueueModal();
  });

  if (sendToRoomBtn) {
    sendToRoomBtn.addEventListener("click", () => {
      const queue = MLPlayer.getQueue();
      if (queue.length === 0) return;
      sendToRoomBtn.disabled = true;
      sendToRoomBtn.textContent = "Sending…";
      fetch("/admin/room/send-queue", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ tracks: queue }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.ok) {
            window.location.href = data.redirect;
          } else {
            alert(data.error || "Couldn't send the queue to a Room.");
            sendToRoomBtn.disabled = false;
            sendToRoomBtn.textContent = "📡 Room";
          }
        })
        .catch(() => {
          alert("Something went wrong sending the queue to a Room.");
          sendToRoomBtn.disabled = false;
          sendToRoomBtn.textContent = "📡 Room";
        });
    });
  }

  MLPlayer.onChange(() => { if (!modal.hidden) renderQueueModal(); });
})();
