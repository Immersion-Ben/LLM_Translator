import time
from job_store import JobStore
from job_manager import JobManager
from constants import JobStatus, MODE_OCR_ONLY, MODE_FULL


class FakeOCR:
    def recognize(self, image_path):
        from paddle_ocr import PageOCR
        return PageOCR(table_htmls=["<table><tr><td>A</td></tr></table>"], text_blocks=["t"])


class FakeTranslator:
    def translate(self, text):
        return "T:" + text


def _mgr(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    from PIL import Image
    p = tmp_path / "doc.png"
    Image.new("RGB", (40, 40), "white").save(str(p))
    return store, JobManager(store, translator=FakeTranslator(), ocr_engine=FakeOCR()), str(p)


def _wait(cond, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_ocr_only_then_translate(tmp_path):
    store, mgr, path = _mgr(tmp_path)
    mgr.start()
    jid = mgr.submit(path, mode=MODE_OCR_ONLY)
    _wait(lambda: store.get(jid).status == JobStatus.OCR_DONE)
    assert store.get(jid).ocr_json
    mgr.request_translation(jid)
    _wait(lambda: store.get(jid).status == JobStatus.DONE)
    assert store.get(jid).result_docx
    mgr.stop()


def test_full_mode_reaches_done(tmp_path):
    store, mgr, path = _mgr(tmp_path)
    mgr.start()
    jid = mgr.submit(path, mode=MODE_FULL)
    _wait(lambda: store.get(jid).status == JobStatus.DONE)
    mgr.stop()


def test_full_mode_overlaps_ocr_and_translation(tmp_path):
    """page1 OCR(생산자) 가 page0 번역(소비자) 보다 먼저 끝나야 한다(겹침).

    OCR 은 빠르게(0.02), 번역은 느리게(0.15) 만들어 결정적으로 검증한다.
    각 페이지는 고유 셀 텍스트(P{i})를 내 셀 캐시 간섭을 피한다."""
    import threading
    import fitz

    pdf = tmp_path / "multi.pdf"
    d = fitz.open()
    for _ in range(3):
        d.new_page()           # 빈 페이지(텍스트 레이어 없음 → 전부 OCR)
    d.save(str(pdf)); d.close()

    events: list = []
    lock = threading.Lock()

    class SlowOCR:
        def __init__(self):
            self.n = 0

        def recognize(self, image_path):
            from paddle_ocr import PageOCR
            i = self.n; self.n += 1
            time.sleep(0.02)
            with lock:
                events.append(("ocr_done", i))
            return PageOCR(table_htmls=[f"<table><tr><td>P{i}</td></tr></table>"], text_blocks=[])

    class SlowTranslator:
        def translate(self, text):
            time.sleep(0.15)
            with lock:
                events.append(("llm_done", text))
            return "T:" + text

    store = JobStore(tmp_path / "jobs.json")
    mgr = JobManager(store, translator=SlowTranslator(), ocr_engine=SlowOCR())
    mgr.start()
    jid = mgr.submit(str(pdf), mode=MODE_FULL)
    _wait(lambda: store.get(jid).status in (JobStatus.DONE, JobStatus.FAILED), timeout=20)
    mgr.stop()

    assert store.get(jid).status == JobStatus.DONE, store.get(jid).error
    # 겹침: page1 OCR 완료가 page0 번역 완료보다 먼저
    assert ("ocr_done", 1) in events and ("llm_done", "P0") in events
    assert events.index(("ocr_done", 1)) < events.index(("llm_done", "P0"))
