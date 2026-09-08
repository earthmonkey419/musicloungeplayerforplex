#!/bin/sh
# init_db.py creates any missing tables (CREATE TABLE IF NOT EXISTS —
# safe every start). migrate_room_columns.py / migrate_shares_check.py
# handle existing tables missing newer columns (also safe every start).

python init_db.py
python migrate_room_columns.py
python migrate_shares_check.py

# -w 1: result_cache.py's in-process cache is a plain dict, not
# shared across processes -- 2 workers silently split it in two. See
# ecosystem.config.cjs for the full explanation; same fix here so
# Docker deployments don't inherit the same problem.
exec gunicorn --bind 0.0.0.0:8680 --workers 1 --threads 4 --worker-class gthread app:app
