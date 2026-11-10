#!/bin/sh
# Reject AI attribution in commits.
#   check_attribution.sh msg FILE    check one commit message and the pending author/committer (commit-msg hook)
#   check_attribution.sh history [REV]  check every commit reachable from REV (default HEAD)
# Fails on: an anthropic.com address or a "Claude" name as author or committer, and message lines
# "Co-Authored-By: ...Claude/Anthropic...", "Claude-Session:", "Generated with [Claude Code]" or a
# claude.ai session link.
set -eu

MSG_PATTERN='^co-authored-by:.*(claude|anthropic)|^claude-session:|generated with \[?claude code|claude\.ai/code/session'
IDENT_PATTERN='anthropic\.com|^claude([ <]|$)'

bad_ident() { printf '%s\n' "$1" | grep -qiE "$IDENT_PATTERN"; }

case "${1:-}" in
msg)
  file=$2
  status=0
  if grep -v '^#' "$file" | grep -iE "$MSG_PATTERN" >/dev/null; then
    echo "commit rejected: AI attribution line in the message:" >&2
    grep -v '^#' "$file" | grep -iE "$MSG_PATTERN" >&2
    status=1
  fi
  for ident in "$(git var GIT_AUTHOR_IDENT)" "$(git var GIT_COMMITTER_IDENT)"; do
    if bad_ident "$ident"; then
      echo "commit rejected: agent identity: $ident" >&2
      status=1
    fi
  done
  exit $status
  ;;
history)
  rev=${2:-HEAD}
  status=0
  for sha in $(git rev-list "$rev"); do
    author=$(git log -1 --format='%an <%ae>' "$sha")
    committer=$(git log -1 --format='%cn <%ce>' "$sha")
    if bad_ident "$author" || bad_ident "$committer"; then
      echo "$sha: agent identity: author $author, committer $committer"
      status=1
    fi
    if git log -1 --format=%B "$sha" | grep -iE "$MSG_PATTERN" >/dev/null; then
      echo "$sha: AI attribution line: $(git log -1 --format=%B "$sha" | grep -iE "$MSG_PATTERN" | head -1)"
      status=1
    fi
  done
  [ $status -eq 0 ] && echo "no AI attribution in $(git rev-list --count "$rev") commits reachable from $rev"
  exit $status
  ;;
*)
  echo "usage: $0 msg FILE | history [REV]" >&2
  exit 2
  ;;
esac
