"""A small Transformer that reads the last two minutes of one-second bars before a touch fill and
predicts the fill's markout (candidate 4 of ``docs/preregistration/paper-five-candidates-20261107.md``).

Input per fill: ``SEQ`` seconds ending at the last whole second at least ``latency_ms`` before the
fill, ``CHANNELS`` per second for the coin and for BTC:

* Hyperliquid mid return (bp), Coinbase mid return (bp), the gap (Hyperliquid over Coinbase less its
  5-minute average, bp), each signed by the fill's side, so a positive number means "moving my way";
* the spread (bp); the taker flow, (buy - sell) / (buy + sell + $1,000), signed by side; log(1 + trades).

The model: a linear embedding, a learned position embedding, two encoder layers (4 heads,
width 32), the mean over time and the last step, and a linear head. Target: the 30 s markout in bp
(clipped to +-20), Huber loss.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

SEQ = 120
PER_ASSET = 6
CHANNELS = 2 * PER_ASSET
FloatArray = npt.NDArray[np.float32]


def bar_features(g: pd.DataFrame) -> tuple[npt.NDArray[np.int64], FloatArray]:
    """Per-second unsigned channels for one coin's bars (index: second in ms). Columns 0-2 are
    directional (to be signed by side), 3 the spread, 4 the flow (directional), 5 log trades."""
    hl = np.log(g["hl_mid"].to_numpy(float))
    cb = np.log(g["cb_mid"].to_numpy(float))
    r_hl = np.r_[np.nan, np.diff(hl)] * 1e4
    r_cb = np.r_[np.nan, np.diff(cb)] * 1e4
    raw = hl - cb
    basis = pd.Series(raw).ewm(halflife=300, ignore_na=True, adjust=False).mean().shift(1).to_numpy()
    gap = (raw - basis) * 1e4
    spread = g["spread_bps"].to_numpy(float)
    b, s = g["buy_usd"].to_numpy(float), g["sell_usd"].to_numpy(float)
    flow = (b - s) / (b + s + 1000.0)
    trades = np.log1p(g["trades"].to_numpy(float))
    x = np.stack([r_hl, r_cb, gap, spread, flow, trades], axis=1)
    x[:, :3] = np.clip(x[:, :3], -20, 20)
    x[:, 3] = np.clip(x[:, 3], 0, 20)
    x = np.nan_to_num(x, nan=0.0).astype(np.float32)
    return g.index.to_numpy(), x


DIRECTIONAL = np.array([1, 1, 1, 0, 1, 0], dtype=np.float32)


def sequences(
    fills: pd.DataFrame, bars: dict[str, tuple[npt.NDArray[np.int64], FloatArray]], latency_ms: int = 200
) -> tuple[FloatArray, npt.NDArray[np.bool_]]:
    """(n, SEQ, CHANNELS) inputs for each fill; ``ok`` marks fills with a full window of bars."""
    out = np.zeros((len(fills), SEQ, CHANNELS), dtype=np.float32)
    ok = np.zeros(len(fills), dtype=bool)
    btc_t, btc_x = bars["BTC"]
    for j, (coin, t, side) in enumerate(zip(fills["coin"], fills["t"], fills["side"], strict=True)):
        if coin not in bars:
            continue
        ct, cx = bars[coin]
        last = (int(t) - latency_ms) // 1000 * 1000 - 1000  # the last whole second before the decision
        i = np.searchsorted(ct, last, side="right") - 1
        k = np.searchsorted(btc_t, last, side="right") - 1
        if i < SEQ or k < SEQ or ct[i] != last or btc_t[k] != last:
            continue
        sign = np.where(DIRECTIONAL > 0, float(side), 1.0).astype(np.float32)
        out[j, :, :PER_ASSET] = cx[i - SEQ + 1 : i + 1] * sign
        out[j, :, PER_ASSET:] = btc_x[k - SEQ + 1 : k + 1] * sign
        ok[j] = True
    return out, ok


def build_model(seed: int = 0, n_static: int = 0):  # type: ignore[no-untyped-def]
    """The Transformer; with ``n_static`` > 0 the head also reads that many per-fill features (the
    ridge model's book and wallet signals), so the sequence only has to add to them."""
    import torch
    from torch import nn

    torch.manual_seed(seed)

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.inp = nn.Linear(CHANNELS, 32)
            self.pos = nn.Parameter(torch.zeros(1, SEQ, 32))
            layer = nn.TransformerEncoderLayer(32, 4, 64, dropout=0.1, batch_first=True)
            self.enc = nn.TransformerEncoder(layer, 2)
            self.head = nn.Sequential(nn.Linear(64 + n_static, 32), nn.GELU(), nn.Linear(32, 1))

        def forward(self, x: torch.Tensor, s: torch.Tensor | None = None) -> torch.Tensor:
            h = self.enc(self.inp(x) + self.pos)
            z = torch.cat([h.mean(1), h[:, -1]] + ([s] if s is not None else []), dim=1)
            return self.head(z).squeeze(-1)

    return Net()
