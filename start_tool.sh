#!/bin/sh
cd "$(dirname "$0")" && . .venv/bin/activate && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
