import time
from page_pipeline import run_page_pipeline


def test_overlap_and_order():
    calls = []
    def produce(i):
        time.sleep(0.05); calls.append(("ocr", i)); return f"p{i}"
    def consume(i, data):
        time.sleep(0.05); calls.append(("llm", i)); return data.upper()
    out = run_page_pipeline(3, produce, consume)
    assert out == ["P0", "P1", "P2"]
    assert calls.index(("ocr", 1)) < calls.index(("llm", 0))  # 겹침
