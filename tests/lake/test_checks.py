import polars as pl

from marketimmune.lake import checks


def test_heights_contiguous() -> None:
    assert checks.heights_contiguous(pl.Series([3, 1, 2, 4])).ok
    c = checks.heights_contiguous(pl.Series([1, 2, 4, 4, 5]))
    assert not c.ok and c.detail["duplicates"] == 1 and c.detail["breaks"] == 2


def test_block_times_increasing() -> None:
    ok = pl.DataFrame({"height": [1, 2, 3], "t_block_ms": [10, 10, 20]})
    bad = pl.DataFrame({"height": [1, 2, 3], "t_block_ms": [10, 30, 20]})
    assert checks.block_times_increasing(ok).ok
    assert checks.block_times_increasing(bad).detail["decreases"] == 1
