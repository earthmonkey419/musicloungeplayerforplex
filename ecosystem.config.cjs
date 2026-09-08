module.exports = {
  // -w 1: result_cache.py's in-process TTL cache (search results,
  // mood buckets) is a plain Python dict, not shared across
  // processes. Running 2 workers (the previous setting) silently
  // split that cache in two -- roughly half of all repeat searches
  // landed on the "cold" worker and paid the full rebuild cost again,
  // even for a query that had JUST been cached moments earlier.
  // --threads 4 already gives real concurrency within one process
  // (gthread uses a thread pool), which is plenty for a single-admin
  // tool -- this trades a parallelism ceiling nobody here needs for
  // the caching layer actually working as designed.
  apps: [
    {
      name: "mlplayer",
      script: "/volume1/web/MusicLoungePlayer/.venv/bin/gunicorn",
      args: "-w 1 --threads 4 --worker-class gthread -b 0.0.0.0:8680 app:app",
      cwd: "/volume1/web/MusicLoungePlayer",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
