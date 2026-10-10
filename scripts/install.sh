#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --cache-dir /workspace/.cache/pip --requirement requirements.lock
.venv/bin/python -m unittest discover -s tests -v
