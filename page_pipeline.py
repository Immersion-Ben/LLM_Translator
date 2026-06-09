"""페이지 OCR(생산자) ∥ 번역(소비자) 2단계, 출력 순서 보존."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_SENTINEL = object()


def run_page_pipeline(n_pages, produce: Callable[[int], object],
                      consume: Callable[[int, object], object], max_prefetch: int = 2) -> list:
    # Use a bounded queue to limit in-flight OCR results waiting for consumption.
    q: "queue.Queue" = queue.Queue(maxsize=max_prefetch)
    err: list[BaseException] = []

    def producer():
        # Run produce() calls concurrently so that produce(i+1) is already
        # in flight while consume(i) is executing — this is the overlap.
        with ThreadPoolExecutor(max_workers=max_prefetch) as pool:
            futures = {}
            try:
                # Submit all pages eagerly; the bounded queue will backpressure
                # by blocking q.put() once max_prefetch results are queued.
                for i in range(n_pages):
                    fut = pool.submit(produce, i)
                    futures[i] = fut
                for i in range(n_pages):
                    result = futures[i].result()  # propagates exceptions
                    q.put((i, result))
            except BaseException as e:  # noqa: BLE001
                err.append(e)
        q.put(_SENTINEL)

    t = threading.Thread(target=producer, daemon=True); t.start()
    results = [None] * n_pages
    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        i, data = item
        results[i] = consume(i, data)
    t.join()
    if err:
        raise err[0]
    return results
