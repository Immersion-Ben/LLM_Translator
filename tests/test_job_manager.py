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
