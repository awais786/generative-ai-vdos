#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/generative-ai-vdos"
cd "$APP_DIR"

# Default: gunicorn's CPU * 2 + 1 heuristic. Override via GUNICORN_WORKERS in .env.
WORKERS="${GUNICORN_WORKERS:-$(( $(nproc) * 2 + 1 ))}"

exec .venv/bin/gunicorn config.wsgi:application \
  --chdir backend \
  --bind 127.0.0.1:8000 \
  --workers "$WORKERS" \
  --timeout 120
