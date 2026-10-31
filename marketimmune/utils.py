"""Small helpers shared by every pipeline stage: dates and comma lists."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

DAY_MS = 86_400_000


def split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_date(value: str) -> datetime:
    """``YYYYMMDD`` as midnight UTC."""
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)


def shift_date(date: str, days: int) -> str:
    return (parse_date(date) + timedelta(days=days)).strftime("%Y%m%d")


def day_start_ms(date: str) -> int:
    return int(parse_date(date).timestamp()) * 1000


def parse_date_spec(value: str) -> tuple[str, ...]:
    """``20251201..20251211,20251213`` -> every date, in order, without repeats."""
    dates: list[str] = []
    for token in split_csv(value):
        start, _, end = token.partition("..")
        first, last = parse_date(start), parse_date(end or start)
        assert first <= last, f"{token=}: range end before start"
        dates += [(first + timedelta(days=k)).strftime("%Y%m%d") for k in range((last - first).days + 1)]
    assert dates, f"{value=}: no dates"
    return tuple(dict.fromkeys(dates))


def parse_symbol_spec(value: str) -> tuple[str, ...]:
    symbols = tuple(dict.fromkeys(item.upper().replace("/", "-") for item in split_csv(value)))
    assert symbols, f"{value=}: no coins"
    return symbols
