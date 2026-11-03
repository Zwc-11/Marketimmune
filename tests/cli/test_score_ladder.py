from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.cli import score_ladder

REGIMES = ("all", "cex_move", "quiet", "taker_liquidation", "forced_60s")
PAIRS = (("l1", "l0"), ("l2", "l1"), ("l3a", "l2"), ("l3b", "l2"), ("l3a_placebo", "l2"))


def _regime(improvement: float, p: float) -> dict[str, object]:
    return {
        "mean_daily_improvement": improvement,
        "days": 24,
        "days_improved": 20,
        "diebold_mariano": {"t_stat": 3.0, "p_value": p},
        "bootstrap_ci_95": [improvement / 2, improvement * 2],
    }


def _run(root: Path, p: dict[str, float], mcs: list[str]) -> Path:
    root.mkdir()
    for prefix, mcs_report in (("", "mcs_brier.json"), ("q_", "mcs_pinball_q10.json")):
        for challenger, base in PAIRS:
            report = {r: _regime(0.0 if challenger == "l3a_placebo" else 0.01, p[challenger]) for r in REGIMES}
            (root / f"{prefix}sol_dec_{challenger}_book_vs_{prefix}sol_dec_{base}_book.json").write_text(json.dumps(report))
        (root / mcs_report).write_text(json.dumps({"days": 24, "included": [f"{prefix}sol_dec_{m}_book" for m in mcs]}))
    return root


def test_holm_steps_down_and_stays_monotone() -> None:
    assert score_ladder.holm({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})


def test_a_hypothesis_is_claimed_only_when_every_run_supports_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _run(tmp_path / "a", {"l1": 0.001, "l2": 0.02, "l3a": 0.01, "l3b": 0.3, "l3a_placebo": 0.5}, ["l2", "l3"])
    b = _run(tmp_path / "b", {"l1": 0.001, "l2": 0.03, "l3a": 0.01, "l3b": 0.3, "l3a_placebo": 0.05}, ["l1", "l2"])
    rows = score_ladder.score_metric(a, "brier", "sol_dec")
    # H4 enters Holm at 2 x 0.3 (two routes); H1 0.004, H3 0.03, H2 0.04
    assert rows["H4"]["p_family"] == pytest.approx(0.6) and rows["H2"]["p_holm"] == pytest.approx(0.04)
    assert [h for h, r in rows.items() if r["supported"]] == ["H1", "H2", "H3", "H5"]
    rows = score_ladder.score_metric(b, "pinball_q10", "sol_dec")
    assert [h for h, r in rows.items() if r["supported"]] == ["H1"]  # H2 Holm 0.06, placebo p 0.05, L1 in the MCS
    out = tmp_path / "verdicts.json"
    assert score_ladder.main(["--runs", f"{a},{b}", "--out", str(out)]) == 0
    verdicts = json.loads(out.read_text())["verdicts"]
    assert [h for h, v in verdicts.items() if v["claimed"]] == ["H1"]
    assert verdicts["H5"]["per_run"] == {str(a): True, str(b): False}
    assert "H1: CLAIMED" in capsys.readouterr().out
