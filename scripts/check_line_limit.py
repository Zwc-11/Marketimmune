"""Fail if a tracked hand-written source file exceeds 1000 lines (CI and ``make lint``)."""

from __future__ import annotations

import subprocess
from pathlib import Path

MAX_LINES = 1000
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css"}
GENERATED = ("server/api/static/", "frontend/dist/")  # built bundles checked into git


def main() -> int:
    tracked = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True).stdout.splitlines()
    sources = [Path(f) for f in tracked if Path(f).suffix in SOURCE_SUFFIXES and not f.startswith(GENERATED) and Path(f).exists()]
    too_long = sorted(
        ((n, p) for p in sources if (n := len(p.read_text(encoding="utf-8", errors="replace").splitlines())) > MAX_LINES), reverse=True
    )
    for n, path in too_long:
        print(f"{n:>6}  {path.as_posix()}")
    print(f"{len(too_long)} file(s) over {MAX_LINES} lines" if too_long else f"no source file exceeds {MAX_LINES} lines")
    return 1 if too_long else 0


if __name__ == "__main__":
    raise SystemExit(main())
