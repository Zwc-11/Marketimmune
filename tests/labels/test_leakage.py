"""Tests for the point-in-time leakage invariant — 100% coverage."""

import pytest

from marketimmune.labels.leakage import LeakageError, assert_as_of, is_point_in_time


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
