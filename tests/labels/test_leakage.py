"""Tests for the point-in-time leakage invariant — 100% coverage."""

import pytest

from marketimmune.labels.leakage import (
    LeakageError,
    assert_as_of,
    assert_strictly_before,
    check_no_lookahead,
    is_point_in_time,
    is_strictly_before,
)


def test_point_in_time_true_when_all_before() -> None:
    assert is_point_in_time([1.0, 2.0, 3.0], 3.0)


def test_point_in_time_false_when_any_after() -> None:
    assert not is_point_in_time([1.0, 4.0], 3.0)


def test_point_in_time_empty_is_true() -> None:
    assert is_point_in_time([], 3.0)


def test_assert_as_of_passes_when_valid() -> None:
    assert assert_as_of([1.0, 2.0], 2.0) is None


def test_assert_as_of_raises_on_lookahead() -> None:
    with pytest.raises(LeakageError, match="look-ahead"):
        assert_as_of([1.0, 5.0], 3.0)



# --- fix L1 / B3 --------------------------------------------------------------------


def test_strictly_before_rejects_same_timestamp() -> None:
    assert is_strictly_before([1.0, 2.9], 3.0)
    assert not is_strictly_before([3.0], 3.0)
    with pytest.raises(LeakageError, match=">="):
        assert_strictly_before([3.0], 3.0)


def _asof_builder(inclusive: bool):  # type: ignore[no-untyped-def]
    def build(labels, src):  # type: ignore[no-untyped-def]
        out = []
        for label in labels:
            t = label["ts_ms"]
            seen = [r for r in src if (r["ts_ms"] <= t if inclusive else r["ts_ms"] < t)]
            if seen:
                out.append({"x": seen[-1]["x"], "n": len(seen)})
        return out
    return build


SRC = [{"ts_ms": float(t), "x": float(t) * 2} for t in range(0, 100, 5)]
LABELS = [{"ts_ms": float(t)} for t in range(10, 100, 10)]  # all on source timestamps


def test_check_no_lookahead_passes_strict_builder() -> None:
    report = check_no_lookahead(_asof_builder(False), LABELS, [SRC], columns=["x", "n"])
    assert report.passed and report.n_checked == len(LABELS)
    assert report.to_dict()["n_mismatched"] == 0


def test_check_no_lookahead_catches_same_millisecond_join() -> None:
    report = check_no_lookahead(_asof_builder(True), LABELS, [SRC], columns=["x"])
    assert not report.passed
    assert report.n_mismatched == len(LABELS)
    assert report.examples and "x" in report.examples[0]["columns"]


def test_check_no_lookahead_counts_rows_that_need_the_future() -> None:
    def future_only(labels, src):  # type: ignore[no-untyped-def]
        return [{"x": 1.0} for lab in labels if any(r["ts_ms"] > lab["ts_ms"] for r in src)]

    report = check_no_lookahead(future_only, LABELS[:3], [SRC], columns=["x"], lookback_ms=20.0)
    assert report.n_dropped == 3 and not report.passed


def test_check_no_lookahead_keeps_static_rows_and_handles_empty() -> None:
    static = [{"x": 7.0}]

    def from_static(labels, src):  # type: ignore[no-untyped-def]
        return [{"x": src[0]["x"]} for _ in labels]

    assert check_no_lookahead(from_static, LABELS, [static], columns=["x"]).passed
    empty = check_no_lookahead(from_static, [], [static], columns=["x"])
    assert empty.n_checked == 0 and not empty.passed


def _carrying(build):  # type: ignore[no-untyped-def]
    """Wrap a builder so each output keeps its label's fields (a row-wise join)."""
    def wrapped(labels, src):  # type: ignore[no-untyped-def]
        out = []
        for label in labels:
            rows = build([label], src)
            out.extend({**label, **row} for row in rows)
        return out
    return wrapped


@pytest.mark.parametrize("inclusive", [False, True])
def test_batched_uncut_run_gives_the_same_verdict(inclusive: bool) -> None:
    build = _carrying(_asof_builder(inclusive))
    batched = check_no_lookahead(build, LABELS, [SRC], columns=["x"], lookback_ms=30.0)
    single = check_no_lookahead(
        build, LABELS, [SRC], columns=["x"], lookback_ms=30.0, batch_full=False
    )
    assert batched.passed is single.passed is (not inclusive)
    assert batched.n_checked == single.n_checked == len(LABELS)


def test_batched_run_flags_a_window_longer_than_the_lookback() -> None:
    # One call per label cuts both runs at the same lookback, so this passed there.
    def counts_all_history(labels, src):  # type: ignore[no-untyped-def]
        return [{**lab, "n": sum(r["ts_ms"] < lab["ts_ms"] for r in src)} for lab in labels]

    report = check_no_lookahead(counts_all_history, LABELS, [SRC], columns=["n"], lookback_ms=12.0)
    assert not report.passed and report.n_mismatched > 0
