#!/bin/sh
# Several users at the same time: DTC_ADMIN_PASSWORD=... ./start_server.sh   (first start creates the user "admin")
cd "$(dirname "$0")" && . .venv/bin/activate && DTC_MODE=server python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
