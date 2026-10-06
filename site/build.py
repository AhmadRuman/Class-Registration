"""Bundle the class_registration source into site/app-source.json.

The playground page loads this file and runs the package with Pyodide, so the
website always runs the same code as the repository.

    python site/build.py
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "class_registration"
OUTPUT = Path(__file__).resolve().parent / "app-source.json"


def current_commit():
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:7]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def main():
    files = {path.name: path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py"))}
    OUTPUT.write_text(json.dumps({"commit": current_commit(), "files": files}), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(files)} files")


if __name__ == "__main__":
    main()
