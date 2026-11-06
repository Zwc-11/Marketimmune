"""JSON for the live feeds: ``orjson`` when it is installed, the standard library otherwise (``orjson``
may have no wheel yet for a new Python, such as 3.14 on Windows). Both give the same objects."""

from __future__ import annotations

import importlib
import json
from types import ModuleType
from typing import Any


def _orjson() -> ModuleType | None:
    try:
        return importlib.import_module("orjson")
    except ImportError:
        return None


orjson = _orjson()


def loads(raw: str | bytes) -> Any:
    return orjson.loads(raw) if orjson is not None else json.loads(raw)


def dumps(obj: Any) -> bytes:
    out: bytes = orjson.dumps(obj) if orjson is not None else json.dumps(obj, separators=(",", ":")).encode()
    return out
