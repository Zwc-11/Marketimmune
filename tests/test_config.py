from datetime import date

import pytest

from marketimmune import config


def test_days_inclusive() -> None:
    d = config.days("2025-12-30", "2026-01-02")
    assert d == [date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2)]
    with pytest.raises(ValueError):
        config.days("2026-01-02", "2026-01-01")


def test_windows_load_and_tbd_raises() -> None:
    assert len(config.window("albers_l4")) == 31
    with pytest.raises(ValueError, match="TBD"):
        config.window("e1_post_launch")


def test_paths_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MARKETIMMUNE_DATA", str(tmp_path))
    p = config.paths()
    assert p.gold == tmp_path / "gold" and p.bronze == tmp_path / "bronze"


def test_episode_config_matches_filter_fields() -> None:
    from marketimmune.priority.nonces import ClockFilter

    f = ClockFilter.from_config()
    assert f.min_actions == 500 and f.delay_hi_ms == 1000 and f.latency_quantile == 0.05
