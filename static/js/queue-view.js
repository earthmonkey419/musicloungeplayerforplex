(function () {
  const btn = document.getElementById("np-queue-btn");
  const modal = document.getElementById("queue-modal");
  const list = document.getElementById("queue-modal-list");
  const closeBtn = document.getElementById("queue-modal-close");
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

  MLPlayer.onChange(() => { if (!modal.hidden) renderQueueModal(); });
})();
