"""Safe update: backup, then git pull; master_data/ you edited is never overwritten silently. See the README."""
import sys

from backend.app.backup_tools import main

if __name__ == "__main__":
    sys.exit(main(prog="update"))
