from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


def load_path(name: str, rel: str) -> ModuleType:
    """Import a file that is not a package module (scripts/, recorder/)."""
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("MARKETIMMUNE_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set MARKETIMMUNE_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def block_line(
    height: int, time: str, bundles: list[list[dict[str, Any]]], resps: list[list[dict[str, Any]]] | None
) -> str:
    """One synthetic replica_cmds line in the documented shape."""
    rec: dict[str, Any] = {
        "abci_block": {
            "time": time,
            "round": height * 2,
            "parent_round": height * 2 - 1,
            "proposer": "0xprop",
            "hardfork": {"version": 1, "round": 1},
            "signed_action_bundles": [
                [
                    f"0xbundle{height}_{i}",
                    {"broadcaster": "0xb", "broadcaster_nonce": 0, "signed_actions": sas},
                ]
                for i, sas in enumerate(bundles)
            ],
        },
        "height": height,
    }
    if resps is not None:
        rec["resps"] = {"Full": [[f"0xbundle{height}_{i}", r] for i, r in enumerate(resps)]}
    return json.dumps(rec)
