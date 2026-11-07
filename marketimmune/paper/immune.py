"""The fill-markout model behind ``immune@`` (``paper.strategies.Immune``): MarketImmune's question,
"will this fill be toxic?", asked of every quote before it is left in the book.

``features(coin, local_ms)`` reads a coin's signals as they stand, the same function for the
training rows (``cli.paper_fills``) and the live quoter, so the model is served exactly what it was
fitted on. For a quote on ``side`` (+1 bid, -1 ask) the directional signals are multiplied by the
side, so one model scores both sides: positive means the move favours the side quoted.

``FillModel`` is a linear model of a fill's markout over ``horizon_s`` (bps from the fill price to
the seen mid ``horizon_s`` later, signed by side; the spread edge included, the fee not), fitted
by ridge on standardised, clipped features with an intercept per coin (``cli.paper_immune_fit``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.paper.mm import micro_bps
from marketimmune.paper.signals import FLOW_MS, CoinState

BPS = 1e4
SIGNED = ("gap_z", "wallet5_z", "wallet1_z", "micro", "imbalance", "burst", "forecast")
UNSIGNED = ("spread", "sigma", "abs_gap_z")
FEATURES = SIGNED + UNSIGNED
MODEL_DIR = Path(__file__).with_name("models")


def features(st: CoinState, local_ms: int) -> dict[str, float] | None:
    """The coin's signals now, unsigned (``side_features`` signs them); None before the gap and
    the book are known."""
    top, gap, gs = st.top, st.gap(), st.gap_sigma
    if top is None or gap is None or not gs or top.mid <= 0:
        return None
    bb, sb = st.intensity_ratio(1, local_ms), st.intensity_ratio(-1, local_ms)
    signed = total = 0.0
    for t, s, n, _ in reversed(st.flow):
        if t < local_ms - FLOW_MS:
            break
        if t <= local_ms:
            signed += s
            total += n
    fc = st.forecast()
    gz = gap / gs
    return {
        "gap_z": gz,
        "wallet5_z": st.informed_z(local_ms) or 0.0,
        "wallet1_z": st.informed_z(local_ms, 1_000) or 0.0,
        "micro": micro_bps(top),
        "imbalance": signed / total if total else 0.0,
        "burst": math.log(bb / sb) if bb and sb else 0.0,
        "forecast": fc if fc is not None else 0.0,
        "spread": (top.ask - top.bid) / top.mid * BPS,
        "sigma": st.sigma_1s or 0.0,
        "abs_gap_z": abs(gz),
    }


def side_features(f: dict[str, float], side: int) -> list[float]:
    return [side * f[k] for k in SIGNED] + [f[k] for k in UNSIGNED]


@dataclass(frozen=True)
class FillModel:
    horizon_s: int
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: dict[str, float]
    clip: float = 5.0
    info: dict[str, Any] | None = None

    @classmethod
    def load(cls, path: Path) -> FillModel:
        d = json.loads(path.read_text(encoding="utf-8"))
        if list(d["features"]) != list(FEATURES):
            raise ValueError(f"{path}: features {d['features']} are not this code's {list(FEATURES)}")
        return cls(
            int(d["horizon_s"]),
            tuple(d["mean"]),
            tuple(d["scale"]),
            tuple(d["coef"]),
            dict(d["intercept"]),
            float(d["clip"]),
            d.get("info"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "features": list(FEATURES),
            "horizon_s": self.horizon_s,
            "mean": list(self.mean),
            "scale": list(self.scale),
            "coef": list(self.coef),
            "intercept": self.intercept,
            "clip": self.clip,
            "info": self.info or {},
        }

    def predict(self, coin: str, x: list[float]) -> float:
        """Expected markout in bps of a fill on the side ``x`` was signed for."""
        out = self.intercept.get(coin, self.intercept.get("*", 0.0))
        for v, m, s, c in zip(x, self.mean, self.scale, self.coef, strict=True):
            z = (v - m) / s if s > 0 else 0.0
            out += c * max(-self.clip, min(self.clip, z))
        return out


_CACHE: dict[int, FillModel] = {}


def model_for(horizon_s: int) -> FillModel:
    """The committed model for a horizon (``paper/models/immune_<h>s.json``), loaded once."""
    if horizon_s not in _CACHE:
        _CACHE[horizon_s] = FillModel.load(MODEL_DIR / f"immune_{horizon_s}s.json")
    return _CACHE[horizon_s]
