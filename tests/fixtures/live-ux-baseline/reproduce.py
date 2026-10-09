"""Reproduce the preserved proof on an isolated exact source baseline.

Run with /var/tmp/control-web-test-venv/bin/python reproduce.py [output.json].
CONTROL_UX_GIT_REPO selects a local repository containing the exact source SHA.
This adapter executes the preserved project fixture; runtime files are not read.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE = "0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde"
HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("CONTROL_UX_GIT_REPO", str(HERE.parents[2])))


def main():
    with tempfile.TemporaryDirectory(prefix="ux-baseline-proof-", dir="/var/tmp") as temporary:
        checkout = Path(temporary) / "source"
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(checkout), SOURCE],
                       check=True, stdout=subprocess.DEVNULL)
        try:
            env = dict(os.environ, CONTROL_UX_BASELINE_REPO=str(checkout), PYTHONDONTWRITEBYTECODE="1")
            browser_lib = "/var/tmp/control-web-browser-venv/lib/python3.12/site-packages"
            env["PYTHONPATH"] = str(checkout / "tests") + os.pathsep + browser_lib
            output = subprocess.check_output([sys.executable, str(HERE / "control-live-ux-bottom-baseline.py")], env=env)
            doc = json.loads(output)
            assert doc["source_sha"] == SOURCE
            assert doc["environment"]["chromium"]
            assert all(row["followingModeEvidence"]["atDocumentEnd"] for row in doc["rows"] + doc["dated_rows"])
            target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(temporary) / "proof.json"
            target.write_bytes(output)
            if len(sys.argv) == 1:
                print(json.dumps({"source_sha": SOURCE, "environment": doc["environment"],
                    "measurements": [{"width": row["width"], "B": row["formBand"], "C": row["fullLowerBand"]}
                                     for row in doc["rows"]]}, ensure_ascii=False, indent=2))
            else:
                print(str(target.resolve()))
        finally:
            subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(checkout)], check=True)


if __name__ == "__main__":
    main()
