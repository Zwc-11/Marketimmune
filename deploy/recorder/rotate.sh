#!/usr/bin/env bash
# Compress closed hourly recorder files with zstd and verify them.
# A file is closed once its hour has ended; the current hour is never touched.
# Run every 10 minutes from systemd/recorder-rotate.timer.
set -euo pipefail

ROOT="${1:-/var/lib/pop/recorder}"
LEVEL="${ZSTD_LEVEL:-19}"
current="$(date -u +%Y%m%d)/$(date -u +%H).log"

find "$ROOT" -type f -name '*.log' -print0 | sort -z | while IFS= read -r -d '' f; do
  rel="${f#"$ROOT"/*/}"                      # <YYYYMMDD>/<HH>.log
  [[ "$rel" == "$current" ]] && continue
  # Skip files written to in the last 2 minutes (hour just rolled over).
  if [[ $(( $(date +%s) - $(stat -c %Y "$f") )) -lt 120 ]]; then continue; fi
  zstd -q -T0 -"$LEVEL" "$f" -o "$f.zst.tmp"
  zstd -q -t "$f.zst.tmp"
  mv "$f.zst.tmp" "$f.zst"
  rm -- "$f"
  echo "$(date -u +%FT%TZ) compressed $f"
done
