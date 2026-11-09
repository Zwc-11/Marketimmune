"""Source and initial-state evidence needed to reproduce a segmented paper run."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from marketimmune.paper.engine import Engine


def directory_fingerprint(root: Path, suffixes: set[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.suffix in suffixes and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def source_fingerprint() -> str:
    return directory_fingerprint(Path(__file__).resolve().parents[1], {".py", ".json"})


def prepare_run(engine: Engine, out: Path, state_dir: Path | None, source_sha: str) -> None:
    """Pin the state loaded before any live inputs; later checkpoints use atomic replacement."""
    initial = out / "initial_state"
    initial.mkdir(parents=True)
    if state_dir is not None and state_dir.exists():
        for path in state_dir.iterdir():
            if path.is_file() and path.suffix in {".json", ".npz"}:
                try:
                    os.link(path, initial / path.name)
                except OSError:
                    shutil.copy2(path, initial / path.name)
    else:
        engine.save_state(initial)
    manifest = {
        "version": 2,
        "source_sha256": source_sha,
        "initial_state": "initial_state",
        "initial_state_sha256": directory_fingerprint(initial, {".json", ".npz"}),
        "coins": list(engine.coins),
        "settings": engine.summary()["settings"],
        "twins": engine.twins,
        "fees_bps": {"maker": engine.maker_fee * 10000, "taker": engine.taker_fee * 10000},
        "execution_model": "print-bounded-no-cancellation-credit-v2",
        "pnl_basis": "mark_to_mid_after_fees_excluding_funding",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")


def replay_manifest(raw: Path, source_sha: str, verify: bool = False) -> dict[str, Any] | None:
    path = raw.parent / "manifest.json"
    if not path.exists():
        if verify:
            raise ValueError("Legacy recording lacks initial-state/source evidence for exact verification")
        return None
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if verify and manifest.get("source_sha256") != source_sha:
        raise ValueError("Recorded source differs from the running engine")
    if verify and manifest.get("initial_state_sha256") != directory_fingerprint(raw.parent / "initial_state", {".json", ".npz"}):
        raise ValueError("Recorded initial state digest differs")
    return manifest


def verify_results(engine: Engine, run: Path) -> None:
    expected = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    actual = engine.summary()
    keys = ("started_ms", "last_ms", "settings", "settings_fees_bps", "instances", "connection_gaps")
    if any(actual[key] != expected[key] for key in keys):
        raise ValueError("Replay state differs from the recorded run")
    actual_counts = {k: v for k, v in actual["counts"].items() if k != "slow_ticks"}
    expected_counts = {k: v for k, v in expected["counts"].items() if k != "slow_ticks"}
    if actual_counts != expected_counts:
        raise ValueError("Replay event counts differ from the recorded run")
    fills = [
        {"coin": coin, "strategy": instance.name, "t_ms": t, "side": side, "px": px, "qty": qty, "fee_rate": fee}
        for coin, instance in engine.instances()
        for t, side, px, qty, fee in instance.account.log
    ]
    recorded = [json.loads(line) for line in (run / "fills.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if fills != recorded:
        raise ValueError("Replay fills differ from the recorded run")
