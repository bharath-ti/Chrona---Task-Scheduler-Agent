"""
Re-run the unittest suite on an interval (local continuous testing).

Usage (from repo root):
    python scripts/continuous_unittest.py
    python scripts/continuous_unittest.py --interval 45

Env:
    CHRONA_TEST_LOOP_SECONDS  default 60
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser(description="Run unittest discover in a loop")
    p.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Seconds between runs (overrides CHRONA_TEST_LOOP_SECONDS)",
    )
    args = p.parse_args()
    root = _root()
    interval = args.interval
    if interval is None:
        interval = float(os.getenv("CHRONA_TEST_LOOP_SECONDS", "60"))
    exe = sys.executable
    cmd = [exe, "-m", "unittest", "discover", "-s", "tests", "-v"]
    print(f"[continuous_unittest] cwd={root} interval={interval}s cmd={cmd}")
    n = 0
    while True:
        n += 1
        print(f"\n{'=' * 60}\n[continuous_unittest] run #{n}\n{'=' * 60}")
        r = subprocess.run(cmd, cwd=str(root))
        if r.returncode != 0:
            print(f"[continuous_unittest] exit code {r.returncode} (continuing)")
        time.sleep(interval)


if __name__ == "__main__":
    main()
