/*
 * MusicLounge Player -- Radio (continuous "based on" station).
 * Depends only on window.MLPlayer. Must load AFTER player-bar.js.
 *
 * Server contract (blueprints/player.py):
 *   GET  /api/player/radio/capabilities -> {track_radio, random_radio, engine}
 *   POST /api/player/radio/start  {type: "track"|"album"|"random", ref?}
 *        -> {tracks, seeds, label, ctx}
 *   POST /api/player/radio/next   {seeds, exclude, limit, ctx}
 *        -> {tracks}   (empty list = neighbourhood exhausted)
 * Errors are 422 + JSON (never 502 -- Cloudflare replaces 502 bodies).
 */
(function () {
  if (window.MLRadio || !window.MLPlayer) return;

  const API = "/api/player/radio";
  const STORE = "mlplayer.radio.v1";
  const LOW_WATER = 5;       // refill when this few tracks remain after the current one
  const BATCH = 10;
  const ANCHOR_EVERY = 3;    // every 3rd refill re-seeds from the ORIGINAL seed(s)
  const MAX_EXCLUDE = 300;
  const MAX_AGE_MS = 12 * 3600 * 1000;

  let state = load();        // {seeds, label, ctx, known: [keys], refills, ts} | null
  let busy = false;
  let starting = false;
  let capsPromise = null;
  let chip = null;

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || "null");
      if (s && Date.now() - s.ts < MAX_AGE_MS) return s;
    } catch (e) {}
    return null;
  }
  function save() {
    try {
      if (state) { state.ts = Date.now(); localStorage.setItem(STORE, JSON.stringify(state)); }
      else localStorage.removeItem(STORE);
    } catch (e) {}
  }

  async function post(path, body) {
    const r = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    return data;
  }

  function capabilities() {
    if (!capsPromise) {
      capsPromise = fetch(API + "/capabilities")
        .then(r => r.json())
        .catch(() => ({ track_radio: false, random_radio: false }));
    }
    return capsPromise;
  }

  // --- status chip -------------------------------------------------------
  const style = document.createElement("style");
  style.textContent =
    ".radio-chip{position:fixed;left:12px;bottom:92px;z-index:900;display:flex;" +
    "align-items:center;gap:8px;max-width:calc(100vw - 24px);padding:6px 10px 6px 12px;" +
    "border-radius:999px;background:#123331;color:#fbf1de;" +
    "border:1px solid var(--pl-gold, #d9a441);font:600 13px/1.2 'Work Sans',sans-serif;" +
    "box-shadow:0 2px 8px rgba(0,0,0,.35)}" +
    ".radio-chip[hidden]{display:none}" +
    ".radio-chip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".radio-chip button{background:none;border:0;color:inherit;cursor:pointer;" +
    "font-size:14px;padding:0 2px}";
  document.head.appendChild(style);

  function showChip(text, withStop) {
    // spa-nav may have swapped the body; re-attach if our node got detached.
    if (!chip || !document.body.contains(chip)) {
      chip = document.createElement("div");
      chip.className = "radio-chip";
      document.body.appendChild(chip);
    }
    chip.textContent = "";
    const span = document.createElement("span");
    span.textContent = text;
    chip.appendChild(span);
    if (withStop) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "\u2715";
      b.title = "Stop radio";
      b.addEventListener("click", stop);
      chip.appendChild(b);
    }
    chip.hidden = false;
  }
  function hideChip() { if (chip) chip.hidden = true; }
  function flash(text) {
    showChip(text, false);
    setTimeout(() => { if (state) showChip("\uD83D\uDCFB " + state.label, true); else hideChip(); }, 4000);
  }

  // --- lifecycle ---------------------------------------------------------
  const origPlayQueue = MLPlayer.playQueue;
  const origPlayTrack = MLPlayer.playTrack;

  async function start(req) {
    try {
      const data = await post("/start", req);
      if (!data.tracks || !data.tracks.length) {
        flash("Couldn't build a station from that");
        return false;
      }
      state = {
        seeds: (data.seeds || []).map(String),
        label: data.label || "Radio",
        ctx: data.ctx || { mode: "sim" },
        known: data.tracks.map(t => String(t.rating_key)),
        refills: 0,
      };
      save();
      starting = true;
      try {
        if (MLPlayer.isShuffleOn()) MLPlayer.setShuffle(false);  // shuffle would scatter refills
        origPlayQueue(data.tracks, 0);
      } finally { starting = false; }
      showChip("\uD83D\uDCFB " + state.label, true);
      return true;
    } catch (e) {
      flash("Radio unavailable: " + e.message);
      return false;
    }
  }

  function stop() {
    state = null;
    save();
    hideChip();
  }

  async function refillIfNeeded() {
    if (!state || busy) return;
    const cur = MLPlayer.getCurrent();
    if (!cur) return;
    if (cur.queueLength - cur.index - 1 > LOW_WATER) return;

    busy = true;
    try {
      state.refills += 1;
      const anchored = state.refills % ANCHOR_EVERY === 0;
      const last = state.known[state.known.length - 1];
      const exclude = state.known.slice(-MAX_EXCLUDE);
      const body = (seeds) => ({ seeds: seeds, exclude: exclude, limit: BATCH, ctx: state.ctx });

      let data = await post("/next", body(anchored ? state.seeds : [last]));
      if (!data.tracks.length && !anchored && state.seeds.length) {
        // dead end from the last track: fall back to the original seed(s)
        data = await post("/next", body(state.seeds));
      }
      if (!state) return;                       // stopped while the request was in flight
      if (!data.tracks.length) {
        flash("Radio ran out of similar tracks");
        stop();
        return;
      }
      data.tracks.forEach(t => {
        state.known.push(String(t.rating_key));
        MLPlayer.enqueue(t);
      });
      save();
    } catch (e) {
      // transient failure: leave state alone, the next track change retries
    } finally { busy = false; }
  }

  // Anything else replacing the queue ends the station. Add-to-queue and
  // Play Next don't replace it, so they leave radio running.
  MLPlayer.playQueue = function () {
    if (!starting) stop();
    return origPlayQueue.apply(this, arguments);
  };
  MLPlayer.playTrack = function () {
    if (!starting) stop();
    return origPlayTrack.apply(this, arguments);
  };

  MLPlayer.onChange(refillIfNeeded);
  if (state) showChip("\uD83D\uDCFB " + state.label, true);

  // "Random Radio" button on the Player search page. Delegated, so it
  // survives spa-nav swapping the page content.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("#random-radio-btn");
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    try { await start({ type: "random" }); } finally { btn.disabled = false; }
  });

  window.MLRadio = { start, stop, capabilities, isActive: () => !!state };
})();
