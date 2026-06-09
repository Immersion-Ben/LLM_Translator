import time
from page_pipeline import run_page_pipeline


def test_overlap_and_order():
    # 비대칭 타이밍으로 겹침을 결정적으로 만든다: produce 는 빠르고(0.02),
    # consume 은 느리다(0.10). 단일 순차 생산자라도 consume(0) 이 도는 동안
    # produce(1) 이 끝나므로 ("ocr",1) 은 항상 ("llm",0) 보다 먼저 기록된다.
    calls = []

    def produce(i):
        time.sleep(0.02); calls.append(("ocr", i)); return f"p{i}"

    def consume(i, data):
        time.sleep(0.10); calls.append(("llm", i)); return data.upper()

    out = run_page_pipeline(3, produce, consume)
    assert out == ["P0", "P1", "P2"]                       # 순서 보존
    assert calls.index(("ocr", 1)) < calls.index(("llm", 0))  # 겹침(deterministic)


def test_producer_exception_propagates():
    def produce(i):
        if i == 1:
            raise ValueError("boom")
        return f"p{i}"

    def consume(i, data):
        return data

    try:
        run_page_pipeline(3, produce, consume)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "boom" in str(e)
