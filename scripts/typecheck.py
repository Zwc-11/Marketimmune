"""mypy --strict on the package, with the settings in pyproject.toml."""

from __future__ import annotations

import subprocess
import sys

if __name__ == "__main__":
    raise SystemExit(
        subprocess.run([sys.executable, "-m", "mypy", "--config-file", "pyproject.toml", "marketimmune"], check=False).returncode
    )
