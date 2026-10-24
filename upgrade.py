"""Upgrade from a downloaded ZIP of a newer version: backup, new code, your data kept, new rows added, undo on failure. See the README."""
import sys

from backend.app.backup_tools import main

if __name__ == "__main__":
    sys.exit(main(prog="upgrade"))
