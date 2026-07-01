"""Guardrail: fail if any tracked source file exceeds the line limit.

CLAUDE.md §7 and the v2 refactor ask that every source file stay under 1000
lines so modules remain readable and single-purpose. This runs in CI (see
`.github/workflows/ci.yml`) and via `make linecount`.

Generated/vendored artifacts (lock files, minified bundles, the checked-in
built SPA) are skipped — the rule targets hand-written source.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

MAX_LINES = 1000
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css"}
# Path fragments that mark generated/vendored files we don't author by hand.
SKIP_FRAGMENTS = (
    "package-lock.json",
    ".min.css",
    ".min.js",
    "dashboard/static/agentic/",  # checked-in built SPA bundle
    "frontend/dist/",
)
# Directories scanned when git is unavailable (the common case is git present).
FALLBACK_ROOTS = ("marketimmune", "aegisbench", "frontend/src", "dashboard", "scripts", "tests")


def tracked_files() -> list[Path]:
    """Return git-tracked files, or walk known source roots if git is absent."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [p for root in FALLBACK_ROOTS for p in Path(root).rglob("*") if p.is_file()]
    return [Path(line) for line in out.splitlines() if line]


def is_source(path: Path) -> bool:
    posix = path.as_posix()
    if any(fragment in posix for fragment in SKIP_FRAGMENTS):
        return False
    return path.suffix in SOURCE_SUFFIXES


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def main() -> int:
    violations: list[tuple[Path, int]] = []
    for path in tracked_files():
        if not is_source(path) or not path.exists():
            continue
        count = line_count(path)
        if count > MAX_LINES:
            violations.append((path, count))

    if violations:
        print(f"Files exceeding {MAX_LINES} lines:")
        for path, count in sorted(violations, key=lambda item: item[1], reverse=True):
            print(f"  {count:>6}  {path.as_posix()}")
        print(f"\n{len(violations)} file(s) over the limit. Split them into smaller modules.")
        return 1

    print(f"Line-limit check passed: no source file exceeds {MAX_LINES} lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
