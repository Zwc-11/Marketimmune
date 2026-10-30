"""Tests for temporal CV splits: anchored walk-forward and purged k-fold."""

from __future__ import annotations

import pytest

from marketimmune.models.walk_forward import (
    TemporalFold,
    purged_kfold_splits,
    purged_walk_forward_splits,
    temporal_fold_arrays,
    temporal_splits,
    walk_forward_splits,
)


def test_purged_kfold_returns_contiguous_temporal_test_folds() -> None:
    folds = purged_kfold_splits([0, 1, 2, 3, 4, 5], n_splits=3)
    assert all(isinstance(fold, TemporalFold) for fold in folds)
    assert [fold.test_indices for fold in folds] == [(0, 1), (2, 3), (4, 5)]
    assert folds[0].train_indices == (2, 3, 4, 5)
    assert folds[1].train_indices == (0, 1, 4, 5)
    assert folds[2].train_indices == (0, 1, 2, 3)


def test_walk_forward_preserves_original_indices_after_sorting() -> None:
    folds = purged_kfold_splits([30, 10, 20, 40], n_splits=2)
    assert folds[0].test_indices == (1, 2)
    assert folds[1].test_indices == (0, 3)


def test_purge_and_embargo_remove_rows_around_test_window() -> None:
    folds = purged_kfold_splits(
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
    folds = purged_kfold_splits([0, 1, 2, 3, 4], n_splits=2)
    assert [len(fold.test_indices) for fold in folds] == [3, 2]


def test_invalid_split_count_raises() -> None:
    with pytest.raises(ValueError, match="n_splits"):
        purged_kfold_splits([0, 1], n_splits=1)


def test_too_few_rows_raises() -> None:
    with pytest.raises(ValueError, match="one row per split"):
        purged_kfold_splits([0], n_splits=2)


def test_negative_purge_or_embargo_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        purged_kfold_splits([0, 1], n_splits=2, purge_ms=-1)
    with pytest.raises(ValueError, match="non-negative"):
        purged_kfold_splits([0, 1], n_splits=2, embargo_ms=-1)


def test_walk_forward_trains_only_on_the_past() -> None:
    folds = walk_forward_splits([0, 1, 2, 3, 4, 5], n_splits=2)

    assert [fold.test_indices for fold in folds] == [(2, 3), (4, 5)]
    assert folds[0].train_indices == (0, 1)
    assert folds[1].train_indices == (0, 1, 2, 3)
    for fold in folds:
        assert max(fold.train_indices) < min(fold.test_indices)


def test_walk_forward_purge_drops_rows_whose_labels_reach_the_test_window() -> None:
    folds = walk_forward_splits([0, 10, 20, 30, 40, 50], n_splits=2, purge_ms=15)

    assert folds[0].train_indices == (0,)
    assert folds[1].train_indices == (0, 1, 2)


def test_array_and_tuple_apis_agree_for_both_schemes() -> None:
    timestamps = [5, 3, 9, 1, 7, 2, 8, 6, 4, 0]
    for scheme in ("walk_forward", "purged_kfold"):
        arrays = temporal_fold_arrays(timestamps, n_splits=3, purge_ms=1, scheme=scheme)
        tuples = temporal_splits(timestamps, n_splits=3, purge_ms=1, scheme=scheme)
        for fast, slow in zip(arrays, tuples, strict=True):
            assert tuple(fast.train.tolist()) == slow.train_indices
            assert tuple(fast.test.tolist()) == slow.test_indices


def test_purged_walk_forward_alias_is_purged_kfold() -> None:
    assert purged_walk_forward_splits is purged_kfold_splits


def test_rejects_unknown_scheme_and_too_few_rows_for_walk_forward() -> None:
    with pytest.raises(ValueError, match="scheme"):
        temporal_splits([0, 1, 2], n_splits=2, scheme="random")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="one row per split"):
        walk_forward_splits([0, 1], n_splits=2)
