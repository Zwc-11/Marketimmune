from __future__ import annotations

import pytest

from marketimmune.cli.paper_tune import family, select


def test_tuning_selects_within_the_rate_limit_and_scores_left_out_segments() -> None:
    hours = {"a": 1.0, "b": 1.0, "c": 2.0}
    pnl = {
        ("100x10", "gap@0.05"): {"a": 30.0, "b": 30.0, "c": 60.0},  # best, but over the limit
        ("250x4", "gap@0.1"): {"a": 10.0, "b": -2.0, "c": 8.0},
        ("250x4", "gap@0.5"): {"a": -1.0, "b": 6.0, "c": 4.0},
        ("250x4", "touch"): {"a": -50.0, "b": -40.0, "c": -90.0},
    }
    per_usd = {("100x10", "gap@0.05"): 1.4, ("250x4", "gap@0.1"): 0.7, ("250x4", "gap@0.5"): 0.4, ("250x4", "touch"): 0.1}
    out = select(hours, pnl, per_usd, limit=1.0)
    gap = out["gap"]
    assert gap["best"]["strategy"] == "gap@0.1" and gap["best"]["config"] == "250x4"  # 16 against 9, the 1.4 excluded
    assert gap["best"]["usd_per_hour"] == pytest.approx(16 / 4, abs=0.05)
    # a left out: gap@0.5 (10 on b, c) beats gap@0.1 (6) and makes -1 on a; b and c left out: gap@0.1, -2 and 8
    picks = {f["left_out"]: f["pick"] for f in gap["folds"]}
    assert picks == {"a": "gap@0.5 250x4", "b": "gap@0.1 250x4", "c": "gap@0.1 250x4"}
    assert gap["cv_usd_per_hour"] == pytest.approx((-1.0 - 2.0 + 8.0) / 4, abs=0.06)  # rounded to 0.1
    assert not gap["picks_agree"]
    assert [o["strategy"] for o in gap["all"]] == ["gap@0.1", "gap@0.5"]
    assert family("improve+gap@0.05") == "improve+gap" and family("touch") == "touch"
