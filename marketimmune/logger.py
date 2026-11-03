"""One stderr handler for the whole package; every module calls ``init_logger(__name__)``."""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def init_logger(name: str) -> logging.Logger:
    """``name`` is the module's ``__name__``; a module run with ``python -m`` reports
    ``__main__``, which is renamed into the package so its records still print."""
    root = logging.getLogger("marketimmune")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logging.getLogger(name if name.startswith("marketimmune") else f"marketimmune.{name}")
