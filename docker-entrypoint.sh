#!/bin/sh
# init_db.py creates any missing tables (CREATE TABLE IF NOT EXISTS —
# safe every start). migrate_room_columns.py / migrate_shares_check.py
# handle existing tables missing newer columns (also safe every start).

python init_db.py
python migrate_room_columns.py
python migrate_shares_check.py

exec gunicorn --bind 0.0.0.0:8680 --workers 2 --threads 4 --worker-class gthread app:app
