import numpy as np
import pandas as pd

from marketimmune.paper.range_study import Band, band_maker, hour_shuffle, second_series


def _series(x: np.ndarray) -> pd.Series:
    return pd.Series(x, index=np.arange(len(x)) * 1000 + 1_000_000_000_000)


def test_band_maker_is_passive_and_round_trips_on_a_swing() -> None:
    rng = np.random.default_rng(1)
    n = 3 * 3600
    noise = np.cumsum(rng.normal(0, 0.3, n))
    swing = np.zeros(n)
    swing[7000:7600] = -np.linspace(0, 60, 600)
    swing[7600:8200] = -60 + np.linspace(0, 60, 600)
    x = 75_000 + noise + swing
    df = band_maker(_series(x), "BTC", Band(k=1.0, horizon_min=15, centre_halflife_min=30))
    assert len(df) >= 1
    bought = df[df["side"] == 1]
    for _, r in bought.iterrows():
        i = int((r["t_in"] - 1_000_000_000_000) // 1000)
        assert r["px_in"] < x[i - 1] + 0.5  # below the ask when placed: a maker
        assert x[i] <= r["px_in"] - 0.5 + 1e-9  # filled only when the book traded through it
    assert (df["fee_bps"] >= 3.0).all()


def test_hour_shuffle_keeps_hourly_moves_and_volatility() -> None:
    rng = np.random.default_rng(2)
    x = 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, 7200)))
    s = _series(x)
    y = hour_shuffle(s, 0).to_numpy()
    assert np.isclose(y[3600], x[3600]) and np.isclose(y[-1], x[-1])
    assert np.isclose(np.std(np.diff(np.log(y))), np.std(np.diff(np.log(x))))


def test_second_series_breaks_long_gaps() -> None:
    t = np.r_[np.arange(0, 60_000, 500), np.arange(60_000 + 20 * 60_000, 60_000 + 21 * 60_000, 500)] + 10**12
    mids = pd.DataFrame({"coin": "BTC", "t_ms": t, "mid": 1.0})
    s = second_series(mids)["BTC"]
    assert s.isna().sum() > 0 and s.iloc[0] == 1.0 and s.iloc[-1] == 1.0
