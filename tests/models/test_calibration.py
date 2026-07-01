"""Tests for model calibration metrics."""

from __future__ import annotations

import pytest

from marketimmune.models.calibration import (
    CalibrationBin,
    brier_score,
    calibration_bins,
    expected_calibration_error,
)


def test_brier_score() -> None:
    score = brier_score([False, True, True], [0.1, 0.8, 0.6])
    expected = ((0.0 - 0.1) ** 2 + (1.0 - 0.8) ** 2 + (1.0 - 0.6) ** 2) / 3
    assert score == pytest.approx(expected)


def test_calibration_bins_return_non_empty_bins() -> None:
    bins = calibration_bins([False, True, True], [0.1, 0.8, 1.0], bins=2)
    assert bins == (
        CalibrationBin(0.0, 0.5, 1, 0.1, 0.0),
        CalibrationBin(0.5, 1.0, 2, 0.9, 1.0),
    )


def test_calibration_bins_skip_empty_bins() -> None:
    bins = calibration_bins([True], [0.1], bins=3)

    assert len(bins) == 1
    assert bins[0].lower == pytest.approx(0.0)
    assert bins[0].upper == pytest.approx(1 / 3)
    assert bins[0].count == 1
    assert bins[0].mean_prediction == pytest.approx(0.1)
    assert bins[0].observed_rate == pytest.approx(1.0)


def test_expected_calibration_error() -> None:
    ece = expected_calibration_error([False, True, True], [0.1, 0.8, 1.0], bins=2)
    assert ece == pytest.approx((1 / 3 * 0.1) + (2 / 3 * 0.1))


def test_rejects_bad_bins() -> None:
    with pytest.raises(ValueError, match="bins"):
        calibration_bins([True], [0.5], bins=0)


def test_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        brier_score([], [])


def test_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        brier_score([True], [0.1, 0.2])


def test_rejects_out_of_range_probability() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        brier_score([True], [1.5])
