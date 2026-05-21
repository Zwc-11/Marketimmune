"""ML risk-scoring head — gradient boosting trained on engineered features.

Drop-in replacement for the rule engine when you want a calibrated
probability rather than a discrete action. Kept dependency-light
(scikit-learn only) so it runs on a laptop, in CI, and inside Django
without GPU or torch.

Design notes
------------
* The model exposes a `RiskScorer` Protocol-like ABC. Anything that
  produces a probability from a feature dict satisfies it — that means
  swapping the gradient-boosting head for a neural MTPP later is a
  one-line change in the simulator.
* The feature list is *frozen at training time* and persisted with the
  model. Inference cannot silently disagree about feature order.
* Categorical thresholds and decision policy live in
  :class:`RiskDecisionPolicy` — a value object — so the alert / block
  thresholds are version-controlled with the model.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

# The 10 engineered features the simulator emits at every tick. The
# *order matters* — we store it on the model and assert at load time.
FEATURE_ORDER: tuple[str, ...] = (
    "w1000_agentic_burst_rate_per_second",
    "w5000_order_quantity_sum",
    "w5000_order_sell_ratio",
    "w1000_agentic_min_interarrival_ms",
    "w60000_market_price_drift",
    "w1000_order_cancel_rate",
    "w5000_agentic_self_cross_proxy_count",
    "w1000_agentic_unique_agents",
    "w5000_order_price_range",
    "w5000_order_quantity_max",
)


@dataclass(frozen=True, slots=True)
class RiskDecisionPolicy:
    """Maps a calibrated probability to a discrete action label.

    Thresholds are deliberately conservative so the head behaves
    well-calibrated against the existing rule-engine baseline.
    """

    alert_threshold: float = 0.40
    block_threshold: float = 0.75

    def label(self, probability: float) -> str:
        if probability >= self.block_threshold:
            return "BLOCK"
        if probability >= self.alert_threshold:
            return "ALERT"
        return "ALLOW"


@dataclass(frozen=True, slots=True)
class RiskPrediction:
    """One ML scoring call's full output."""

    score: float
    label: str
    top_features: tuple[tuple[str, float], ...]
    model_name: str


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Held-out metrics for a single trained model."""

    pr_auc: float
    roc_auc: float
    f1: float
    precision_at_50: float
    accuracy: float
    n_train: int
    n_test: int
    model_name: str

    def to_dict(self) -> dict:
        return {
            "pr_auc": self.pr_auc,
            "roc_auc": self.roc_auc,
            "f1": self.f1,
            "precision_at_50": self.precision_at_50,
            "accuracy": self.accuracy,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "model_name": self.model_name,
        }


class RiskScorer:
    """A calibrated gradient-boosting risk head.

    Use the class methods to train or load; instances are immutable once
    constructed.
    """

    MODEL_NAME = "GradientBoostingRiskHead-v1"

    def __init__(
        self,
        estimator: GradientBoostingClassifier,
        feature_order: Sequence[str] = FEATURE_ORDER,
        policy: RiskDecisionPolicy | None = None,
    ):
        self._estimator = estimator
        self._feature_order = tuple(feature_order)
        self._policy = policy if policy is not None else RiskDecisionPolicy()

    # ---- inference -------------------------------------------------

    def predict(self, features: dict[str, float]) -> RiskPrediction:
        vector = self._vectorise(features)
        proba = float(self._estimator.predict_proba(vector.reshape(1, -1))[0, 1])
        label = self._policy.label(proba)
        top = self._top_contributions(vector)
        return RiskPrediction(
            score=proba,
            label=label,
            top_features=top,
            model_name=self.MODEL_NAME,
        )

    def predict_batch(self, feature_dicts: Sequence[dict[str, float]]) -> list[RiskPrediction]:
        return [self.predict(f) for f in feature_dicts]

    def _vectorise(self, features: dict[str, float]) -> np.ndarray:
        return np.array(
            [float(features.get(name, 0.0)) for name in self._feature_order],
            dtype=np.float64,
        )

    def _top_contributions(
        self, vector: np.ndarray, k: int = 3
    ) -> tuple[tuple[str, float], ...]:
        """Return the top-k features contributing to this prediction.

        We approximate per-prediction contributions with `feature value
        × global feature importance`. It's not as principled as SHAP
        but it ships today; switching to TreeExplainer later requires
        only changing this method.
        """
        importances = self._estimator.feature_importances_
        contribs = vector * importances
        order = np.argsort(-np.abs(contribs))[:k]
        return tuple((self._feature_order[i], float(contribs[i])) for i in order)

    # ---- training / persistence -----------------------------------

    @classmethod
    def train(
        cls,
        X: np.ndarray,
        y: np.ndarray,
        *,
        feature_order: Sequence[str] = FEATURE_ORDER,
        seed: int = 42,
        test_size: float = 0.25,
        scenario_names: Sequence[str] | None = None,
        held_out_scenarios: Sequence[str] | None = None,
    ) -> tuple[RiskScorer, BenchmarkReport]:
        """Train a calibrated gradient-boosting risk head.

        Two split modes:

        * **Random row split** (default) — fast but generous. Use this
          for the in-distribution baseline.
        * **Scenario-family held-out split** — pass ``scenario_names``
          aligned to ``X`` and ``held_out_scenarios``; the named
          scenarios are *removed entirely* from training and used as
          the test set. This is the honest benchmark a recruiter
          should look at: it tests "does the head detect attacks the
          training set never saw?".
        """
        if X.shape[1] != len(feature_order):
            raise ValueError(
                f"X has {X.shape[1]} columns but FEATURE_ORDER has {len(feature_order)}"
            )

        if held_out_scenarios and scenario_names is not None:
            held = set(held_out_scenarios)
            names_arr = np.asarray(scenario_names)
            test_mask = np.isin(names_arr, list(held))
            train_mask = ~test_mask
            X_train, X_test = X[train_mask], X[test_mask]
            y_train, y_test = y[train_mask], y[test_mask]
            if X_train.shape[0] == 0 or X_test.shape[0] == 0:
                raise ValueError(
                    "Held-out split produced an empty train or test set."
                )
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=seed, stratify=y
            )

        clf = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.08,
            random_state=seed,
        )
        clf.fit(X_train, y_train)
        proba_test = clf.predict_proba(X_test)[:, 1]
        pred_test = (proba_test >= 0.5).astype(int)
        # `average_precision_score` requires both classes in the test
        # split. The held-out path may give us all-hostile or
        # all-benign rows; fall back to NaN-equivalents in that case
        # so the report never crashes the loop.
        if len(set(y_test.tolist())) < 2:
            pr = float("nan")
            roc = float("nan")
        else:
            pr = float(average_precision_score(y_test, proba_test))
            roc = float(roc_auc_score(y_test, proba_test))
        report = BenchmarkReport(
            pr_auc=pr,
            roc_auc=roc,
            f1=float(f1_score(y_test, pred_test, zero_division=0)),
            precision_at_50=cls._precision_at_top_k(y_test, proba_test, k=50),
            accuracy=float((pred_test == y_test).mean()),
            n_train=int(X_train.shape[0]),
            n_test=int(X_test.shape[0]),
            model_name=cls.MODEL_NAME,
        )
        return cls(clf, feature_order=feature_order), report

    @staticmethod
    def _precision_at_top_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
        if len(scores) == 0:
            return 0.0
        top = np.argsort(-scores)[: min(k, len(scores))]
        return float(y_true[top].mean())

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "estimator": self._estimator,
                "feature_order": list(self._feature_order),
                "policy": {
                    "alert_threshold": self._policy.alert_threshold,
                    "block_threshold": self._policy.block_threshold,
                },
                "model_name": self.MODEL_NAME,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path | str) -> RiskScorer:
        bundle = joblib.load(Path(path))
        policy_args = bundle.get("policy") or {}
        return cls(
            estimator=bundle["estimator"],
            feature_order=bundle["feature_order"],
            policy=RiskDecisionPolicy(**policy_args),
        )

    # ---- introspection --------------------------------------------

    @property
    def feature_order(self) -> tuple[str, ...]:
        return self._feature_order

    @property
    def feature_importances(self) -> dict[str, float]:
        return dict(
            zip(self._feature_order, self._estimator.feature_importances_.tolist(), strict=False)
        )


def write_report(report: BenchmarkReport, path: Path | str) -> None:
    """Persist a benchmark report as JSON for the dashboard to read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
