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
    const artistBtn = item.type === "track"
      ? '<button class="room-share-popover-item" data-action="artist">🎤 Go to Artist</button>'
      : "";
    const radioBtn = (item.type === "track" || item.type === "album") && window.MLRadio
      ? '<button class="room-share-popover-item" data-action="radio" hidden>📻 Start Radio</button>'
      : "";
    const enqueueBtn =
      '<button class="room-share-popover-item" data-action="enqueue">⏬ Add to Queue</button>';
    // Defensive: openAddToPlaylist() is defined locally per-template
    // (Browse, Player, Album detail, Plex playlist detail) and
    // exposed on window by each -- native Playlist detail doesn't
    // define it at all (you can't add a track that's already in this
    // playlist to itself), so this option only appears where the
    // function actually exists rather than throwing when clicked.
    const addPlaylistBtn =
      (item.type === "track" && typeof window.openAddToPlaylist === "function") ||
      (item.type === "album" && typeof window.openAddToPlaylistBulk === "function")
        ? '<button class="room-share-popover-item" data-action="addplaylist">➕ Add to Playlist</button>'
        : "";

    const menu = document.createElement("div");
    menu.className = "room-share-popover";
    menu.innerHTML = `
      <button class="room-share-popover-item" data-action="playnext">⏭ Play Next</button>
      ${enqueueBtn}
      ${addPlaylistBtn}
      <button class="room-share-popover-item" data-action="room">📡 Start a Room</button>
      <button class="room-share-popover-item" data-action="share">🔗 Share a Link</button>
      ${artistBtn}
      ${albumBtn}
      ${radioBtn}
      <div class="room-share-popover-status" hidden></div>
    `;
    document.body.appendChild(menu);
    if (item.compact) {
      ["playnext", "enqueue", "addplaylist"].forEach((a) => {
        const el = menu.querySelector('[data-action="' + a + '"]');
        if (el) { el.hidden = true; el.style.display = "none"; }
      });
    }

    const rect = anchorEl.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.left = `${Math.max(8, rect.right - menu.offsetWidth)}px`;
    menu.style.zIndex = "10000";
    if (rect.bottom + 4 + menu.offsetHeight > window.innerHeight - 8) {
      menu.style.top = `${Math.max(8, rect.top - menu.offsetHeight - 4)}px`;
    }

    openMenuEl = menu;

    const statusEl = menu.querySelector(".room-share-popover-status");
    function showStatus(text, isError) {
      menu.querySelectorAll(".room-share-popover-item").forEach(b => b.hidden = true);
      statusEl.hidden = false;
      statusEl.textContent = text;
      statusEl.style.color = isError ? "var(--pl-red)" : "var(--pl-text)";
    }

    const enqueueTrigger = menu.querySelector('[data-action="enqueue"]');
    if (enqueueTrigger) {
      enqueueTrigger.addEventListener("click", () => {
        if (item.type === "track") {
          MLPlayer.enqueue({ rating_key: item.ref, title: item.title, artist: item.artist });
          showStatus("Added to queue!");
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
            data.tracks.forEach(t => MLPlayer.enqueue(t));
            showStatus("Added to queue!");
            setTimeout(closeMenu, 900);
          })
          .catch(() => showStatus("Something went wrong.", true));
      });
    }

    const addPlaylistTrigger = menu.querySelector('[data-action="addplaylist"]');
    if (addPlaylistTrigger) {
      addPlaylistTrigger.addEventListener("click", () => {
        if (item.type === "album") {
          showStatus("Loading tracks…");
          fetch(`/api/player/content-tracks?type=album&ref=${item.ref}`)
            .then(r => r.json())
            .then(data => {
              if (!data.tracks || data.tracks.length === 0) {
                showStatus(data.error || "No tracks found.", true);
                return;
              }
              closeMenu();
              window.openAddToPlaylistBulk(data.tracks);
            })
            .catch(() => showStatus("Something went wrong.", true));
          return;
        }
        closeMenu();
        window.openAddToPlaylist({ rating_key: item.ref, title: item.title, artist: item.artist });
      });
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

    const radioTrigger = menu.querySelector('[data-action="radio"]');
    if (radioTrigger) {
      window.MLRadio.capabilities().then(caps => {
        if (caps.track_radio && openMenuEl === menu && statusEl.hidden) radioTrigger.hidden = false;
      });
      radioTrigger.addEventListener("click", async () => {
        showStatus("Starting radio…");
        const ok = await window.MLRadio.start({ type: item.type, ref: item.ref });
        if (ok) { showStatus("Radio started!"); setTimeout(closeMenu, 900); }
        else showStatus("Couldn't start radio.", true);
      });
    }

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

    const artistTrigger = menu.querySelector('[data-action="artist"]');
    if (artistTrigger) {
      artistTrigger.addEventListener("click", () => {
        showStatus("Loading artist…");
        fetch(`/browse/api/artist-for-track/${item.ref}`)
          .then(r => r.json())
          .then(data => {
            if (!data.artist_rating_key) {
              showStatus(data.error || "Couldn't find that track's artist.", true);
              return;
            }
            // Same real-<a>-click pattern as Go to Album, so spa-nav.js
            // handles it and playback survives the jump.
            const link = document.createElement("a");
            link.href = `/browse/artist/${data.artist_rating_key}`;
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
            const url = data.share_url;
            const showManual = () => {
              menu.innerHTML =
                '<div class="room-share-popover-status">Link created. Tap Copy:</div>' +
                '<input class="room-share-link-input" readonly ' +
                'style="width:92%;margin:6px 4%;padding:6px;font-size:13px;box-sizing:border-box;">' +
                '<button class="room-share-popover-item" data-action="copylink">📋 Copy link</button>';
              const inp = menu.querySelector("input");
              const btn = menu.querySelector('[data-action="copylink"]');
              inp.value = url;
              inp.focus(); inp.select();
              btn.addEventListener("click", () => {
                const ok = () => { btn.textContent = "✓ Copied"; setTimeout(closeMenu, 1200); };
                const legacy = () => {
                  inp.focus(); inp.select(); inp.setSelectionRange(0, 99999);
                  let good = false;
                  try { good = document.execCommand("copy"); } catch (e) {}
                  if (good) ok(); else btn.textContent = "Press and hold the link to copy";
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(url).then(ok).catch(legacy);
                } else { legacy(); }
              });
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(url).then(() => {
                showStatus("Link copied!");
                setTimeout(closeMenu, 1800);
              }).catch(showManual);
            } else {
              showManual();
            }
          } else {
            showStatus((data && data.error) || "Couldn't create a link.", true);
          }
        })
        .catch(() => showStatus("Something went wrong.", true));
    });
  }

  window.openRoomShareMenu = openMenu;
})();
