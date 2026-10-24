#!/bin/sh
# Install Design to Cost (Linux / macOS): python3 -m venv .venv && pip install -r requirements.txt
cd "$(dirname "$0")"
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && mkdir -p upgrades && python -m backend.app.migrate
echo "Installed. Start with ./start_tool.sh  (http://127.0.0.1:8000/)"
