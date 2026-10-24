"""Check from any computer that every library of requirements.txt (with its dependencies) has a ready-made Windows 64-bit package for a Python version,
so that Install_Tool.bat will not need a compiler. Nothing is installed; the packages are only downloaded to a temporary folder.

    python scripts/check_windows_wheels.py            # Python 3.11, 3.12 and 3.13
    python scripts/check_windows_wheels.py 3.13
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(versions) -> int:
    bad = 0
    for v in versions:
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-m", "pip", "download", "-r", str(ROOT / "requirements.txt"), "-d", d, "--platform", "win_amd64",
                                "--python-version", v, "--only-binary=:all:", "-q"], capture_output=True, text=True)
            n = len(list(Path(d).iterdir()))
        ok = r.returncode == 0
        bad += not ok
        print(f"Python {v} on Windows 64-bit: {'OK, ' + str(n) + ' packages have wheels' if ok else 'PROBLEM: ' + (r.stderr or r.stdout)[-300:]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["3.11", "3.12", "3.13"]))
