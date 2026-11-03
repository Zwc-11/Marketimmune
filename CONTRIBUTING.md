# Contributing

Run all commands from the repository root. Windows: `.\make.ps1 <target>` runs the same targets.

## Code formatting

Python follows the conventions of [deepseek-ai/DeepInfer](https://github.com/deepseek-ai/DeepInfer). Ruff is configured in
[pyproject.toml](pyproject.toml) with the same rule set (line length 140).

```bash
ruff check --fix && ruff format                          # Format
ruff check --no-cache && ruff format --check --no-cache  # Check
```

Rust: `cargo fmt --all` and `cargo clippy --workspace --all-targets -- -D warnings`. TypeScript: `npm --prefix frontend run typecheck`.

## Writing code

- One way to do each thing. No fallback paths, compatibility branches or options kept "just in case".
- Invariants are `assert cond, f"{x=}"`; bad input fails loudly.
- Typed signatures everywhere (`mypy --strict` on the package). Docstrings only where the code does not say it: units, invariants,
  data quirks.
- Progress goes through `marketimmune.logger.init_logger(__name__)`; a command prints only its final result.
- Per-row work is vectorised; files are read column-selectively; expensive objects are built once and reused.

## Testing

- `tests/`: pytest, discovered by default. Every kept behaviour has a test; tests of deleted code are deleted.
- A refactor must reproduce the previous outputs on real data, not only pass unit tests.

```bash
python -m pytest            # all tests
python -m coverage run -m pytest && python -m coverage report
```
