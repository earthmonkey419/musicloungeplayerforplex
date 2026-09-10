/*
 * MusicLounge Player -- shared "Start a Room / Share a Link" popover.
 *
 * One small popover, opened near whatever trigger button was clicked,
 * offering both actions for that specific item. Used by track rows in
 * Browse/Player search/Playlist detail/Album detail, and by playlist
 * rows on the Playlists page and album-level buttons on detail pages.
 *
 * window.openRoomShareMenu(anchorEl, {type, ref, title, artist})
 *   type: "track" | "album" | "playlist"
 *   ref: the item's Plex rating_key (string or number)
 *   title/artist: for display and for Share's content_title/content_artist
 */
(function () {
  let openMenuEl = null;

  function closeMenu() {
    if (openMenuEl) { openMenuEl.remove(); openMenuEl = null; }
  }

  document.addEventListener("click", (e) => {
    if (openMenuEl && !openMenuEl.contains(e.target) && !e.target.closest(".room-share-trigger")) {
      closeMenu();
    }
  });

  function openMenu(anchorEl, item) {
    closeMenu();

    const albumBtn = item.type === "track"
      ? '<button class="room-share-popover-item" data-action="album">💿 Go to Album</button>'
      : "";

    const menu = document.createElement("div");
    menu.className = "room-share-popover";
    menu.innerHTML = `
      <button class="room-share-popover-item" data-action="playnext">⏭ Play Next</button>
      <button class="room-share-popover-item" data-action="room">📡 Start a Room</button>
      <button class="room-share-popover-item" data-action="share">🔗 Share a Link</button>
      ${albumBtn}
      <div class="room-share-popover-status" hidden></div>
    `;
    document.body.appendChild(menu);

    const rect = anchorEl.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.left = `${Math.max(8, rect.right - menu.offsetWidth)}px`;

    openMenuEl = menu;

    const statusEl = menu.querySelector(".room-share-popover-status");
    function showStatus(text, isError) {
      menu.querySelectorAll(".room-share-popover-item").forEach(b => b.hidden = true);
      statusEl.hidden = false;
      statusEl.textContent = text;
      statusEl.style.color = isError ? "var(--pl-red)" : "var(--pl-text)";
    }

    menu.querySelector('[data-action="playnext"]').addEventListener("click", () => {
      if (item.type === "track") {
        // The track's own data is already known -- no backend call
        // needed at all, unlike album/playlist below.
        MLPlayer.playNext([{ rating_key: item.ref, title: item.title, artist: item.artist }]);
        showStatus("Playing next!");
        setTimeout(closeMenu, 900);
        return;
      }
      showStatus("Loading tracks…");
      fetch(`/api/player/content-tracks?type=${item.type}&ref=${item.ref}`)
        .then(r => r.json())
        .then(data => {
          if (!data.tracks || data.tracks.length === 0) {
            showStatus(data.error || "No tracks found.", true);
            return;
          }
          MLPlayer.playNext(data.tracks);
          showStatus("Playing next!");
          setTimeout(closeMenu, 900);
        })
        .catch(() => showStatus("Something went wrong.", true));
    });

    const albumTrigger = menu.querySelector('[data-action="album"]');
    if (albumTrigger) {
      albumTrigger.addEventListener("click", () => {
        showStatus("Loading album…");
        fetch(`/browse/api/album-for-track/${item.ref}`)
          .then(r => r.json())
          .then(data => {
            if (!data.album_rating_key) {
              showStatus(data.error || "Couldn't find that track's album.", true);
              return;
            }
            // A real <a> click, not window.location.href -- this lets
            // spa-nav.js's own click interception pick it up naturally,
            // keeping playback alive across the jump. A direct location
            // change would be a full page reload and stop playback,
            // which is exactly the bug this was built to avoid.
            const link = document.createElement("a");
            link.href = `/browse/album/${data.album_rating_key}`;
            document.body.appendChild(link);
            link.click();
            link.remove();
          })
          .catch(() => showStatus("Something went wrong.", true));
      });
    }

    menu.querySelector('[data-action="room"]').addEventListener("click", () => {
      showStatus("Starting room…");
      fetch("/admin/room/send-content", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ content_type: item.type, content_ref: item.ref, content_title: item.title }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.ok) {
            showStatus("Room started!");
            setTimeout(() => { window.location.href = data.redirect; }, 500);
          } else {
            showStatus(data.error || "Couldn't start a room.", true);
          }
        })
        .catch(() => showStatus("Something went wrong.", true));
    });

    menu.querySelector('[data-action="share"]').addEventListener("click", () => {
      showStatus("Creating link…");
      fetch("/admin/share/create", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          content_type: item.type,
          content_ref: item.ref,
          content_title: item.title,
          content_artist: item.artist || "",
          duration_hours: 24,
        }),
      })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          if (ok && data.ok) {
            navigator.clipboard.writeText(data.share_url).then(() => {
              showStatus("Link copied!");
            }).catch(() => {
              showStatus("Link created (couldn't auto-copy)");
            });
            setTimeout(closeMenu, 1800);
          } else {
            showStatus((data && data.error) || "Couldn't create a link.", true);
          }
        })
        .catch(() => showStatus("Something went wrong.", true));
    });
  }

  window.openRoomShareMenu = openMenu;
})();
