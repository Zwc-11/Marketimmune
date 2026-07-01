"""Tests for purged / embargoed walk-forward splits."""

from __future__ import annotations

import pytest

from marketimmune.models.walk_forward import TemporalFold, purged_walk_forward_splits


def test_walk_forward_returns_contiguous_temporal_test_folds() -> None:
    folds = purged_walk_forward_splits([0, 1, 2, 3, 4, 5], n_splits=3)
    assert all(isinstance(fold, TemporalFold) for fold in folds)
    assert [fold.test_indices for fold in folds] == [(0, 1), (2, 3), (4, 5)]
    assert folds[0].train_indices == (2, 3, 4, 5)
    assert folds[1].train_indices == (0, 1, 4, 5)
    assert folds[2].train_indices == (0, 1, 2, 3)


def test_walk_forward_preserves_original_indices_after_sorting() -> None:
    folds = purged_walk_forward_splits([30, 10, 20, 40], n_splits=2)
    assert folds[0].test_indices == (1, 2)
    assert folds[1].test_indices == (0, 3)


def test_purge_and_embargo_remove_rows_around_test_window() -> None:
    folds = purged_walk_forward_splits(
        [0, 10, 20, 30, 40, 50],
        n_splits=3,
        purge_ms=10,
        embargo_ms=10,
    )
    middle = folds[1]
    assert middle.test_indices == (2, 3)
    assert middle.purge_start_ms == pytest.approx(10.0)
    assert middle.embargo_end_ms == pytest.approx(40.0)
    assert middle.train_indices == (0, 5)


def test_fold_sizes_distribute_remainder_to_early_folds() -> None:
    folds = purged_walk_forward_splits([0, 1, 2, 3, 4], n_splits=2)
    assert [len(fold.test_indices) for fold in folds] == [3, 2]


def test_invalid_split_count_raises() -> None:
    with pytest.raises(ValueError, match="n_splits"):
        purged_walk_forward_splits([0, 1], n_splits=1)


def test_too_few_rows_raises() -> None:
    with pytest.raises(ValueError, match="one row per split"):
        purged_walk_forward_splits([0], n_splits=2)


def test_negative_purge_or_embargo_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        purged_walk_forward_splits([0, 1], n_splits=2, purge_ms=-1)
    with pytest.raises(ValueError, match="non-negative"):
        purged_walk_forward_splits([0, 1], n_splits=2, embargo_ms=-1)
