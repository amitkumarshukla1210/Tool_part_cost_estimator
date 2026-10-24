# Releases

One folder per version: `V0/`, `V1/` …, each with `DesignToCost-Vn.zip`, `SHA256.txt` and `RELEASE_NOTES.md`. `LATEST` holds the newest version name.

To upgrade your installation: download the ZIP of the newest version (this folder on GitHub, or Code → Download ZIP), put it in the folder `upgrades` of your installation,
close the tool and double-click `Upgrade_Tool.bat`. Your data is kept. See the README, section "Versions, upgrade by ZIP, backup and restore".

To publish a new version: change `VERSION`, write `releases/Vn/RELEASE_NOTES.md`, commit, run `python scripts/make_release.py`, commit `releases/` and push.
