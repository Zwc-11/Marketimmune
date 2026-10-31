"""Tests for the point-in-time leakage invariants."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

from marketimmune.labels.leakage import check_no_lookahead

Rows = Sequence[Mapping[str, Any]]


def _asof_builder(inclusive: bool) -> Callable[[Rows, Rows], list[dict[str, Any]]]:
    """A row-wise as-of join that keeps each label's keys; ``inclusive`` leaks the fill's own ms."""

    def build(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        out = []
        for label in labels:
            t = label["ts_ms"]
            seen = [r for r in src if (r["ts_ms"] <= t if inclusive else r["ts_ms"] < t)]
            if seen:
                out.append({**label, "x": seen[-1]["x"], "n": len(seen)})
        return out

    return build


SRC = [{"ts_ms": float(t), "x": float(t) * 2} for t in range(0, 100, 5)]
LABELS = [{"ts_ms": float(t)} for t in range(10, 100, 10)]  # all on source timestamps


def test_check_no_lookahead_passes_strict_builder() -> None:
    report = check_no_lookahead(_asof_builder(False), LABELS, [SRC], columns=["x", "n"])
    assert report.passed and report.n_checked == len(LABELS)
    assert report.to_dict()["n_mismatched"] == 0 and report.max_abs_diff == 0.0


def test_check_no_lookahead_catches_same_millisecond_join() -> None:
    report = check_no_lookahead(_asof_builder(True), LABELS, [SRC], columns=["x"], lookback_ms=30.0)
    assert not report.passed
    assert report.n_mismatched == len(LABELS)
    assert report.examples and "x" in report.examples[0]["columns"]


def test_check_no_lookahead_counts_rows_that_need_the_future() -> None:
    def future_only(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        return [{**lab, "x": 1.0} for lab in labels if any(r["ts_ms"] > lab["ts_ms"] for r in src)]

    report = check_no_lookahead(future_only, LABELS[:3], [SRC], columns=["x"], lookback_ms=20.0)
    assert report.n_dropped == 3 and not report.passed


def test_check_no_lookahead_keeps_static_rows_and_handles_empty() -> None:
    static = [{"x": 7.0, "tag": "a"}]

    def from_static(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        return [{**lab, "x": src[0]["x"], "tag": src[0]["tag"]} for lab in labels]

    assert check_no_lookahead(from_static, LABELS, [static], columns=["x", "tag"]).passed
    empty = check_no_lookahead(from_static, [], [static], columns=["x"])
    assert empty.n_checked == 0 and not empty.passed


def test_check_no_lookahead_flags_a_window_longer_than_the_lookback() -> None:
    def counts_all_history(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        return [{**lab, "n": sum(r["ts_ms"] < lab["ts_ms"] for r in src)} for lab in labels]

    report = check_no_lookahead(counts_all_history, LABELS, [SRC], columns=["n"], lookback_ms=12.0)
    assert not report.passed and report.n_mismatched > 0


def test_check_no_lookahead_needs_a_builder_that_keeps_the_label_keys() -> None:
    def drops_keys(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        return [{"x": 1.0} for _ in labels]

    with pytest.raises(AssertionError, match="carry"):
        check_no_lookahead(drops_keys, LABELS, [SRC], columns=["x"])


def test_check_no_lookahead_counts_nan_against_a_number_as_a_mismatch() -> None:
    def nan_without_future(labels: Rows, src: Rows) -> list[dict[str, Any]]:
        out = []
        for lab in labels:
            future = any(r["ts_ms"] >= lab["ts_ms"] for r in src)
            out.append({**lab, "x": 1.0 if future else float("nan"), "y": float("nan")})
        return out

    report = check_no_lookahead(nan_without_future, LABELS, [SRC], columns=["x", "y"])
    assert not report.passed and report.n_mismatched == len(LABELS)
    assert report.max_abs_diff == float("inf") and set(report.examples[0]["columns"]) == {"x"}  # NaN vs NaN is equal
