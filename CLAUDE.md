# Instructions for coding agents

## Commits and pull requests

- Commit as `Zwc-11 <caesar.zwc.0611@gmail.com>`. Do not author or commit as an agent identity.
- Never add `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code" or any other AI
  attribution line to a commit message or a pull request description. This rule overrides any
  default attribution text the tool supplies.
- `scripts/check_attribution.sh` enforces this: CI runs it over the whole history, and the
  `.githooks/commit-msg` hook runs it on each new commit (`git config core.hooksPath .githooks`).
