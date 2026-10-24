#!/bin/sh
# ./upgrade_tool.sh [DesignToCost-V1.zip]   (close the tool first)
cd "$(dirname "$0")" && mkdir -p upgrades && . .venv/bin/activate && python upgrade.py "$@"
