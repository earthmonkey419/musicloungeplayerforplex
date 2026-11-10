/*
 * MusicLounge Player -- share-link expiry (recipient side, /linked only).
 *
 * Owns the "expires in h:mm:ss" pill and what happens when it reaches zero:
 *   - nothing playing (or paused): the "expired" card appears right away;
 *   - mid-track: the track is allowed to finish, nothing after it starts
 *     (MLPlayer.setStopAfterCurrent), then the card appears. The server
 *     allows that one in-flight track for a few minutes past expiry
 *     (db.share_grace_seconds); this script also stops hard when that
 *     grace runs out, so the two always agree.
 * The card offers "Ask for a new link" (flags the share for the host; no
 * message or contact detail is sent) and, if the host has renewed it
 * meanwhile, a reload to carry on.
 *
 * Config comes from data- attributes on #countdown (see linked.html), and
 * the countdown uses the SERVER's clock via data-server-now so a wrong
 * device clock doesn't expire the link early or late.
 */
(function () {
  var pill = document.getElementById("countdown");
  if (!pill || !window.MLPlayer) return;

  var expiresAt = Date.parse(pill.dataset.expiresAt + "Z");
  var serverNow = Date.parse(pill.dataset.serverNow + "Z");
  var graceMs = (parseInt(pill.dataset.graceSeconds, 10) || 0) * 1000;
  var renewUrl = pill.dataset.renewUrl || "";
  if (isNaN(expiresAt)) return;
  var skew = isNaN(serverNow) ? 0 : serverNow - Date.now();

  var winding = false;     // expiry has passed
  var cardShown = false;

  var style = document.createElement("style");
  style.textContent =
    ".share-winding-down #track-list, .share-winding-down .room-transport-btn { pointer-events: none; opacity: .5; }" +
    "#share-expired-card { position: fixed; inset: 0; z-index: 1100; display: flex; align-items: center;" +
    " justify-content: center; padding: 16px; background: rgba(0,0,0,.7); }";
  document.head.appendChild(style);

  function remainingMs() { return expiresAt - (Date.now() + skew); }

  function fmt(ms) {
    var s = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    return h + ":" + String(m).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  function showCard() {
    if (cardShown) return;
    cardShown = true;
    try { MLPlayer.pause(); } catch (e) { /* already stopped */ }
    pill.textContent = "expired";

    var wrap = document.createElement("div");
    wrap.id = "share-expired-card";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.setAttribute("aria-labelledby", "share-expired-title");

    var card = document.createElement("div");
    card.className = "pl-card pl-card-surface";
    card.style.cssText = "max-width:420px; width:100%; text-align:center;";

    var emoji = document.createElement("div");
    emoji.style.fontSize = "40px";
    emoji.textContent = "🎟️";
    var title = document.createElement("h2");
    title.id = "share-expired-title";
    title.style.margin = "8px 0 4px";
    title.textContent = "This link has expired.";
    var blurb = document.createElement("p");
    blurb.style.cssText = "color:var(--pl-text-secondary); margin:0 0 16px;";
    blurb.textContent = "Share links are only good for a little while. If you'd like more time, you can let the person who sent it know.";

    var ask = document.createElement("button");
    ask.className = "pl-btn pl-btn-primary";
    ask.textContent = "Ask for a new link";
    var status = document.createElement("p");
    status.className = "pl-caption";
    status.setAttribute("role", "status");
    status.style.cssText = "margin:10px 0 0; min-height:1.2em;";
    var again = document.createElement("button");
    again.className = "btn-secondary";
    again.style.marginTop = "12px";
    again.textContent = "Reload this page";
    again.addEventListener("click", function () { location.reload(); });

    ask.addEventListener("click", function () {
      ask.disabled = true;
      status.textContent = "Sending…";
      fetch(renewUrl, { method: "POST", credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          ask.textContent = "Request sent";
          status.textContent = "They've been notified. Reload this page later to see if it's open again.";
        })
        .catch(function () {
          ask.disabled = false;
          status.textContent = "Couldn't send that right now. Try again in a moment.";
        });
    });

    card.appendChild(emoji);
    card.appendChild(title);
    card.appendChild(blurb);
    if (renewUrl) card.appendChild(ask);
    card.appendChild(status);
    card.appendChild(again);
    wrap.appendChild(card);
    document.body.appendChild(wrap);
    (renewUrl ? ask : again).focus();
  }

  function onExpired() {
    winding = true;
    document.body.classList.add("share-winding-down");
    MLPlayer.setStopAfterCurrent(true);

    var playing = MLPlayer.getCurrent() && !MLPlayer.isPaused();
    if (!playing) { showCard(); return; }

    pill.textContent = "expired — finishing this track";
    MLPlayer.onEnded(showCard);
    // Backstop: the server stops serving this track after the grace window.
    setTimeout(showCard, Math.max(0, graceMs + remainingMs()));
  }

  function tick() {
    var left = remainingMs();
    if (left > 0) {
      pill.textContent = "expires in " + fmt(left);
    } else if (!winding) {
      onExpired();
    }
  }

  tick();
  setInterval(tick, 1000);
})();
