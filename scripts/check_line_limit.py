"""Fail if a tracked hand-written source file exceeds 1000 lines (CI and ``make lint``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

MAX_LINES = 1000
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css"}
GENERATED = ("server/api/static/", "frontend/dist/")  # built bundles checked into git
EXCLUDED = {"node_modules", ".venv", ".audit-venv", "__pycache__", "target", "data", "output"}


def unpacked_sources() -> list[Path]:
    paths = []
    for folder, dirs, files in os.walk(".", followlinks=False):
        dirs[:] = [name for name in dirs if name not in EXCLUDED
                   and not (Path(folder) / name).is_junction() and not (Path(folder) / name).is_symlink()]
        paths.extend(Path(folder) / name for name in files)
    return paths


def main() -> int:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], check=False, capture_output=True, text=True)
    paths = [Path(f) for f in result.stdout.splitlines()] if result.returncode == 0 else unpacked_sources()
    sources = [p for p in paths if p.suffix in SOURCE_SUFFIXES and not EXCLUDED.intersection(p.parts)
               and not p.as_posix().startswith(GENERATED) and p.is_file()]
    too_long = sorted(
        ((n, p) for p in sources if (n := len(p.read_text(encoding="utf-8", errors="replace").splitlines())) > MAX_LINES), reverse=True
    )
    for n, path in too_long:
        print(f"{n:>6}  {path.as_posix()}")
    print(f"{len(too_long)} file(s) over {MAX_LINES} lines" if too_long else f"no source file exceeds {MAX_LINES} lines")
    return 1 if too_long else 0


if __name__ == "__main__":
    raise SystemExit(main())
