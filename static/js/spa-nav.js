/*
 * MusicLounge Player -- SPA-style navigation for the Player/Playlists/
 * Browse zone (the "player_family" pages, see base.html).
 *
 * The actual fix for "audio stops when you navigate": internal link
 * clicks are intercepted, the target page's content is fetched and
 * swapped into #spa-content, and the URL is updated via History API
 * -- the persistent shell (nav, <audio> element, MLPlayer engine)
 * outside #spa-content is never touched, so playback never stops.
 *
 * Deliberately scoped: only loaded on player_family pages (see
 * base.html), so Room Mode/Share/Settings/auth links are simply never
 * intercepted from here. Links TO those pages are additionally marked
 * with data-full-reload in the nav partial as a second, explicit
 * safeguard -- entering/leaving the zone is always a real navigation.
 */
(function () {
  const contentEl = document.getElementById("spa-content");
  if (!contentEl) return;

  function isSpaLink(link) {
    if (!link || link.tagName !== "A") return false;
    if (link.hasAttribute("data-full-reload")) return false;
    if (link.hasAttribute("download")) return false;
    if (link.target && link.target !== "" && link.target !== "_self") return false;
    if (!link.href) return false;

    let url;
    try { url = new URL(link.href, window.location.origin); }
    catch (e) { return false; }

    if (url.origin !== window.location.origin) return false;
    if (url.pathname === window.location.pathname && url.hash) return false;

    return true;
  }

  function focusOrScrollHash(hash) {
    if (!hash) return;
    const id = hash.replace(/^#/, "");
    const el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      el.focus();
    } else {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }

  function reExecuteScripts(container) {
    container.querySelectorAll("script").forEach(oldScript => {
      const newScript = document.createElement("script");
      Array.from(oldScript.attributes).forEach(attr => newScript.setAttribute(attr.name, attr.value));
      newScript.textContent = oldScript.textContent;
      oldScript.replaceWith(newScript);
    });
  }

  function updateActiveNavLink(pathname) {
    document.querySelectorAll(".pl-topnav-link, .pl-mobile-menu-link").forEach(link => {
      try {
        const linkPath = new URL(link.href, window.location.origin).pathname;
        link.classList.toggle("pl-topnav-link-active", linkPath === pathname);
      } catch (e) {}
    });
  }

  async function navigateTo(url, pushState) {
    const target = new URL(url, window.location.origin);
    let res, html;
    try {
      res = await fetch(target.href, { headers: { "X-Spa-Nav": "1" } });
      html = await res.text();
    } catch (e) {
      window.location.href = url;
      return;
    }

    if (res.redirected && !res.url.startsWith(target.origin + target.pathname)) {
      window.location.href = res.url;
      return;
    }

    const doc = new DOMParser().parseFromString(html, "text/html");
    const newContent = doc.getElementById("spa-content");
    if (!newContent) {
      window.location.href = url;
      return;
    }

    // Some pages render differently depending on server-side state --
    // Room's dashboard is player_family (SPA-eligible) only when no
    // room is active yet; the moment a room exists, it renders as a
    // real, separate page instead (its own richer Now Playing UI,
    // server-authoritative audio). #spa-content always exists either
    // way, so that alone can't distinguish the two -- this data
    // attribute is the explicit signal. Falling back to a real
    // navigation here, rather than soft-swapping in a page that
    // wasn't actually meant for this zone, matches the same safety
    // principle as the redirected-to-login check above.
    if (newContent.dataset.playerFamily !== "true") {
      window.location.href = url;
      return;
    }

    if (typeof window.__spaTeardown === "function") {
      try { window.__spaTeardown(); } catch (e) { console.error("SPA teardown error:", e); }
      window.__spaTeardown = null;
    }

    // pushState BEFORE swapping content/re-executing scripts: some
    // pages (browse_index.html) call history.replaceState() as part
    // of their own top-level script to add query params (?type=&sort=).
    // If pushState happened AFTER that, it would overwrite the page's
    // own replaceState with the plain clicked URL, silently dropping
    // those params from the address bar.
    if (pushState) history.pushState({ spa: true }, "", url);

    contentEl.innerHTML = newContent.innerHTML;
    document.title = doc.title;
    reExecuteScripts(contentEl);

    updateActiveNavLink(target.pathname);

    if (target.hash) {
      focusOrScrollHash(target.hash);
    } else {
      window.scrollTo(0, 0);
    }
  }

  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const link = e.target.closest("a");
    if (!isSpaLink(link)) return;
    e.preventDefault();
    navigateTo(link.href, true);
  });

  window.addEventListener("popstate", () => {
    navigateTo(window.location.href, false);
  });

  updateActiveNavLink(window.location.pathname);
})();
