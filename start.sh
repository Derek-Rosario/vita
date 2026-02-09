#!/bin/sh
set -e

echo "Starting migrations..."
python /code/manage.py migrate --noinput

echo "Starting supercronic..."
supercronic /code/crontab &
CRONIC_PID=$!

echo "Starting db_worker..."
python /code/manage.py db_worker &
WORKER_PID=$!

cleanup() {
    echo "Shutting down..."
    kill "$CRONIC_PID" "$WORKER_PID" 2>/dev/null || true
    wait "$CRONIC_PID" "$WORKER_PID" 2>/dev/null || true
    exit 0
}

trap cleanup TERM INT

echo "Starting Daphne..."
python -m daphne vita.asgi:application -b 0.0.0.0 -p 8000 &
DAPHNE_PID=$!

wait "$DAPHNE_PID"
