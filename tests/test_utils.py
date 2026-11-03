from __future__ import annotations

import threading
from collections.abc import Iterator

from marketimmune.utils import prefetch


def test_prefetch_yields_every_item_in_order_from_another_thread() -> None:
    def produce() -> Iterator[tuple[int, int]]:
        for k in range(5):
            yield k, threading.get_ident()

    got = list(prefetch(produce()))
    assert [k for k, _ in got] == list(range(5))
    assert all(thread != threading.get_ident() for _, thread in got)
