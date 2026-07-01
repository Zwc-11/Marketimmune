"""Tests for the champion/challenger promotion policy — 100% coverage."""

from marketimmune.models.promotion import ModelMetrics, PromotionPolicy

CHAMPION = ModelMetrics(
    pr_auc=0.80, markout_lift_bps=0.0, brier=0.15, latency_p95_ms=0.6, leakage_safe=True
)
POLICY = PromotionPolicy()  # min_criteria=4 of 5, latency budget 1.0 ms


def test_promote_when_challenger_beats_champion() -> None:
    challenger = ModelMetrics(0.82, 0.5, 0.14, 0.6, leakage_safe=True)
    verdict = POLICY.evaluate(CHAMPION, challenger)
    assert verdict.verdict == "promote"
    assert verdict.passed == 5
    assert verdict.total == 5
    assert verdict.criteria["markout_lift"].passed


def test_needs_more_data_when_borderline() -> None:
    # Fails markout + pr_auc (3 of 5 pass) -> one short of the bar.
    challenger = ModelMetrics(0.78, -0.1, 0.14, 0.6, leakage_safe=True)
    verdict = POLICY.evaluate(CHAMPION, challenger)
    assert verdict.verdict == "needs_more_data"
    assert verdict.passed == 3


def test_reject_when_clearly_worse() -> None:
    challenger = ModelMetrics(0.70, -1.0, 0.20, 2.0, leakage_safe=True)
    verdict = POLICY.evaluate(CHAMPION, challenger)
    assert verdict.verdict == "reject"
    assert not verdict.criteria["latency"].passed
    assert not verdict.criteria["calibration"].passed


def test_reject_leaky_model_even_if_metrics_win() -> None:
    challenger = ModelMetrics(0.85, 1.0, 0.10, 0.5, leakage_safe=False)
    verdict = POLICY.evaluate(CHAMPION, challenger)
    assert verdict.verdict == "reject"
    assert not verdict.criteria["no_leakage"].passed
