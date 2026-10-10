#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export BOT_INITIAL_SOURCE="${BOT_INITIAL_SOURCE:-kraken}"
exec .venv/bin/python -m uvicorn bot.app:app --host 127.0.0.1 --port "${BOT_PORT:-8000}"
