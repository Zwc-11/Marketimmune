"""A verified replay must pin its inputs, configuration, source and initial state."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from marketimmune.cli import paper_trade
from marketimmune.paper.engine import Engine
from marketimmune.paper.events import parse_hl
from marketimmune.paper.live import RawWriter, verified_lines
from marketimmune.paper.provenance import prepare_run, replay_manifest


def test_initial_state_is_not_changed_by_later_checkpoints(tmp_path: Path) -> None:
    state = tmp_path / "state"
    engine = Engine(("io:X",), strategies=("touch",))
    engine.wallets.add("wallet", 1)
    engine.save_state(state)
    run = tmp_path / "run"
    prepare_run(engine, run, state, "source")
    before = (run / "initial_state/wallets.json").read_bytes()
    engine.wallets.add("wallet", 100)
    engine.save_state(state)
    assert (run / "initial_state/wallets.json").read_bytes() == before
    assert (state / "wallets.json").read_bytes() != before
    assert replay_manifest(run / "raw", "source", verify=True) is not None
    with pytest.raises(ValueError, match="source differs"):
        replay_manifest(run / "raw", "wrong", verify=True)
    (run / "initial_state/wallets.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="state digest"):
        replay_manifest(run / "raw", "source", verify=True)


def test_verified_input_digest_rejects_a_valid_gzip_with_changed_inputs(tmp_path: Path) -> None:
    writer = RawWriter(tmp_path)
    writer.write("tick", 1_000_000_000, b"1000 0")
    writer.close()
    assert len(list(verified_lines(tmp_path))) == 1
    path = next(tmp_path.glob("tick-*.log.gz"))
    with gzip.open(path, "wb") as handle:
        handle.write(b"1000000000\t1001 0\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        list(verified_lines(tmp_path))
    with pytest.raises(FileExistsError):
        RawWriter(tmp_path)


def test_legacy_recording_cannot_claim_exact_verification(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Legacy recording"):
        replay_manifest(tmp_path / "raw", "source", verify=True)
    with pytest.raises(ValueError, match="completed input digest"):
        list(verified_lines(tmp_path))


def test_verified_cli_reproduces_nondefault_hip3_settings_and_gaps(tmp_path: Path) -> None:
    run = tmp_path / "run"
    strategy = "hush@d=8/quiet=0/tol=0.3"
    engine = Engine(
        ("io:X",),
        strategies=(strategy,),
        quote_usd=100,
        max_quotes=4,
        budget_usd=1000,
        maker_fee_bps=0.3,
        taker_fee_bps=0.9,
        sz_decimals={"io:X": 2},
    )
    prepare_run(engine, run, None, paper_trade.SOURCE_SHA256)
    (run / "meta.json").write_text('{"io:X":2}', encoding="utf-8")
    writer = RawWriter(run / "raw")
    frames = [
        (1000, {"channel": "activeAssetCtx", "data": {"coin": "io:X", "ctx": {"oraclePx": "100"}}}),
        (
            1001,
            {"channel": "bbo", "data": {"coin": "io:X", "time": 1001, "bbo": [{"px": "99.99", "sz": "10"}, {"px": "100.01", "sz": "10"}]}},
        ),
        (
            1500,
            {"channel": "bbo", "data": {"coin": "io:X", "time": 1500, "bbo": [{"px": "99.99", "sz": "10"}, {"px": "100.01", "sz": "10"}]}},
        ),
        (
            1600,
            {
                "channel": "trades",
                "data": [{"coin": "io:X", "time": 1600, "tid": 7, "px": "99.5", "sz": "0.25", "side": "A", "users": ["buyer", "seller"]}],
            },
        ),
    ]
    for stamp, frame in frames:
        writer.write("hl", stamp * 1_000_000, json.dumps(frame))
        for event in parse_hl(frame, stamp):
            engine.handle(event, stamp)
    gap = {"venue": "hl", "error": "test disconnect"}
    writer.write("gap", 1700 * 1_000_000, json.dumps(gap))
    engine.feed_gap("hl", 1700, gap["error"])
    writer.write("tick", 2000 * 1_000_000, b"2000 0")
    engine.tick(2000)
    writer.close()
    engine.write(run, final=True)
    assert paper_trade.main(["--replay", str(run / "raw"), "--out", str(tmp_path / "replay"), "--verify-recording"]) == 0


@pytest.mark.parametrize("settings", [{"latency_ms": -1}, {"quote_usd": float("nan")}, {"budget_usd": float("inf")}, {"taker_fee_bps": -1}])
def test_invalid_engine_settings_fail_before_market_inputs(settings: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Engine(("io:X",), **settings)  # type: ignore[arg-type]
