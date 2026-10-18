"""Backup / restore of master_data/, data/ and the CAD storage folder. See backend/app/backup_tools.py or the README."""
import sys

from backend.app.backup_tools import main

if __name__ == "__main__":
    sys.exit(main(prog="backup"))
