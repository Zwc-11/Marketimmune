"""The policy ``optimal@`` follows: per coin, a table of which sides to quote for each position and
market state, solved by value iteration on a model calibrated on the selection hours
(``cli.paper_optimal_fit``, which documents the model).

The market state is the coin's predicted next-10 s move, ``coef[0] + coef[1:] . x`` over
``REGIME_FEATURES`` (``paper.immune.features``, clipped at 10), cut at the coin's ``edges``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REGIME_FEATURES = ("gap_z", "micro", "wallet1_z", "wallet5_z", "imbalance")
POLICY_PATH = Path(__file__).with_name("models") / "optimal.json"
ACTIONS = ((False, False), (True, False), (False, True), (True, True))  # (bid, ask)


@dataclass(frozen=True)
class CoinPolicy:
    coef: tuple[float, ...]
    edges: tuple[float, ...]
    table: tuple[tuple[int, ...], ...]  # [q + Q][state] -> action
    q_max: int

    def state(self, f: dict[str, float]) -> tuple[int, float]:
        pred = self.coef[0] + sum(c * max(-10.0, min(10.0, f[k])) for c, k in zip(self.coef[1:], REGIME_FEATURES, strict=True))
        return sum(pred >= e for e in self.edges), pred

    def action(self, units: int, state: int) -> tuple[bool, bool]:
        i = max(-self.q_max, min(self.q_max, units)) + self.q_max
        return ACTIONS[self.table[i][state]]


_CACHE: dict[str, dict[str, CoinPolicy]] = {}


def policies(phi: str, path: Path = POLICY_PATH) -> dict[str, CoinPolicy]:
    """Each coin's policy for risk aversion ``phi`` (a key of the file's ``phis``), loaded once."""
    key = f"{path}|{phi}"
    if key not in _CACHE:
        d = json.loads(path.read_text(encoding="utf-8"))
        if list(d["features"]) != list(REGIME_FEATURES):
            raise ValueError(f"{path}: features {d['features']} are not this code's {list(REGIME_FEATURES)}")
        if phi not in d["coins"][next(iter(d["coins"]))]["policies"]:
            raise ValueError(f"{path}: no policy for phi={phi} (have {d['phis']})")
        _CACHE[key] = {
            c: CoinPolicy(tuple(v["coef"]), tuple(v["edges"]), tuple(tuple(row) for row in v["policies"][phi]), int(d["Q"]))
            for c, v in d["coins"].items()
        }
    return _CACHE[key]
