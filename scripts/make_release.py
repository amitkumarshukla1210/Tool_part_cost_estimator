"""Build the ZIP of a numbered version for GitHub: releases/<VERSION>/DesignToCost-<VERSION>.zip.

    python scripts/make_release.py            # version = the VERSION file
Contains every file git tracks except releases/ (data/, storage/ and backups/ are never in git). Upgrade a hosted or local installation with:
    python upgrade.py path/to/DesignToCost-V1.zip         (or Upgrade_Tool.bat: it takes the newest ZIP from the folder 'upgrades' or Downloads)
"""

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = (ROOT / "VERSION").read_text().strip()
    out_dir = ROOT / "releases" / version
    out_dir.mkdir(parents=True, exist_ok=True)
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
    target = out_dir / f"DesignToCost-{version}.zip"
    top = f"DesignToCost-{version}/"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            if rel.startswith("releases/") or not (ROOT / rel).is_file():
                continue
            z.write(ROOT / rel, top + rel)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    (out_dir / "SHA256.txt").write_text(f"{sha}  {target.name}\n")
    (ROOT / "releases" / "LATEST").write_text(f"{version}\n")
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  sha256 {sha[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
