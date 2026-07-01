"""Tests for the drift monitors (PSI, KS, severity) — 100% coverage."""

import pytest

from marketimmune.monitoring import PSI_SIGNIFICANT, drift_severity, ks_statistic, psi


def test_psi_zero_for_same_distribution() -> None:
    data = [float(i) for i in range(100)]
    assert psi(data, data) == pytest.approx(0.0, abs=1e-9)


def test_psi_positive_for_shifted_distribution() -> None:
    ref = [float(i) for i in range(100)]
    cur = [float(i) + 50.0 for i in range(100)]
    assert psi(ref, cur) > PSI_SIGNIFICANT  # large shift -> significant drift


def test_psi_single_bin_is_zero() -> None:
    assert psi([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], bins=1) == pytest.approx(0.0)


def test_psi_rejects_bad_bins() -> None:
    with pytest.raises(ValueError, match="bins"):
        psi([1.0], [1.0], bins=0)


def test_psi_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        psi([], [1.0])
    with pytest.raises(ValueError, match="non-empty"):
        psi([1.0], [])


def test_ks_zero_for_identical() -> None:
    assert ks_statistic([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(0.0)


def test_ks_one_for_disjoint() -> None:
    assert ks_statistic([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(1.0)
    assert ks_statistic([4.0, 5.0, 6.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_ks_partial_overlap() -> None:
    distance = ks_statistic([1.0, 2.0, 3.0, 4.0], [3.0, 4.0, 5.0, 6.0])
    assert 0.0 < distance < 1.0


def test_ks_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ks_statistic([], [1.0])
    with pytest.raises(ValueError, match="non-empty"):
        ks_statistic([1.0], [])


def test_drift_severity_levels() -> None:
    assert drift_severity(0.30) == "significant"
    assert drift_severity(0.15) == "moderate"
    assert drift_severity(0.05) == "none"
