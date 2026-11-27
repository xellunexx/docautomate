#!/usr/bin/env sh
# Linux / macOS start script
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt || exit 1
[ -f .venv/ocr-done ] || { .venv/bin/python -m pip install -q -r requirements-ocr.txt && touch .venv/ocr-done; }
exec .venv/bin/python -m docautomate "$@"
