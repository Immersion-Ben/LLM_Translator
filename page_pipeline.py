"""페이지 OCR(생산자) ∥ 번역(소비자) 2단계, 출력 순서 보존.

생산자는 **단일 스레드에서 순차적으로** produce(i) 를 호출한다. OCR 은
단일 PaddleOCR 파이프라인(thread-safe 아님)을 쓰고, 페이지 제너레이터를
당겨 쓰므로 동시 호출하면 안 된다. 겹침은 "consume(i) 가 도는 동안
produce(i+1) 가 진행"되는 형태로 자연 발생한다(생산자/소비자가 별 스레드)."""
from __future__ import annotations

import queue
import threading
from typing import Callable

_SENTINEL = object()


def run_page_pipeline(n_pages, produce: Callable[[int], object],
                      consume: Callable[[int, object], object], max_prefetch: int = 2) -> list:
    q: "queue.Queue" = queue.Queue(maxsize=max_prefetch)
    err: list[BaseException] = []

    def producer():
        try:
            for i in range(n_pages):
                q.put((i, produce(i)))
        except BaseException as e:  # noqa: BLE001
            err.append(e)
        finally:
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
