import sys

import pytest
from dependencies import PADDLE_AVAILABLE


@pytest.mark.skipif(sys.platform != "win32", reason="windows path encoding issue")
def test_ascii_safe_dir_converts_non_ascii_path(tmp_path):
    from paddle_ocr import _ascii_safe_dir
    korean = tmp_path / "한글 폴더"
    korean.mkdir()
    (korean / "marker.txt").write_text("x", encoding="utf-8")
    safe = _ascii_safe_dir(korean)
    try:
        assert str(safe).isascii()
        assert (safe / "marker.txt").is_file()
    finally:
        if safe != korean and safe.is_junction():
            safe.rmdir()


def test_ascii_safe_dir_keeps_ascii_path(tmp_path):
    from paddle_ocr import _ascii_safe_dir
    assert _ascii_safe_dir(tmp_path) == tmp_path


def test_reading_order_pairs_borderless_keyvalue_rows():
    """무테두리 2단 키-값 표: 라벨열과 값열이 검출 원시 순서로는 뒤섞여 들어와도
    좌표 기반 행 우선 정렬로 '라벨→값, 다음 행' 순서를 복원해야 한다."""
    from paddle_ocr import _reading_order
    # PaddleOCR 가 흔히 내놓는 뒤섞인 순서: 왼쪽 라벨들을 먼저, 그 다음 값들을.
    # bbox = (x0, y0, x1, y1). 라벨열 x≈[20,180], 값열 x≈[220,600].
    texts = ["거래명:", "대표자:", "등록주소:",
             "현대 주식회사", "Thai Duy Do", "Tang 13 ..."]
    boxes = [(20, 100, 180, 130), (20, 160, 180, 190), (20, 220, 180, 250),
             (220, 102, 600, 132), (220, 162, 600, 192), (220, 222, 600, 252)]
    assert _reading_order(texts, boxes) == [
        "거래명:", "현대 주식회사",
        "대표자:", "Thai Duy Do",
        "등록주소:", "Tang 13 ...",
    ]


def test_reading_order_keeps_single_column_top_to_bottom():
    """단일 열 본문은 위→아래 순서를 그대로 유지한다."""
    from paddle_ocr import _reading_order
    texts = ["첫 줄", "둘째 줄", "셋째 줄"]
    boxes = [(40, 50, 500, 80), (40, 100, 500, 130), (40, 150, 500, 180)]
    assert _reading_order(texts, boxes) == ["첫 줄", "둘째 줄", "셋째 줄"]


def test_reading_order_falls_back_to_original_when_no_boxes():
    """좌표가 없거나 개수가 맞지 않으면 원래 순서(빈 텍스트 제외)를 유지한다."""
    from paddle_ocr import _reading_order
    texts = ["a", " ", "b", "c"]
    assert _reading_order(texts, []) == ["a", "b", "c"]
    assert _reading_order(texts, [None, None, None, None]) == ["a", "b", "c"]


def test_reading_order_accepts_polygon_boxes():
    """rec_polys 형태(4점 다각형)도 축정렬 bbox 로 변환해 처리한다."""
    from paddle_ocr import _reading_order
    texts = ["좌", "우"]
    # 같은 행 밴드, 좌측/우측 — 4점 다각형 [[x,y],...]
    boxes = [
        [[20, 100], [180, 100], [180, 130], [20, 130]],
        [[220, 102], [600, 102], [600, 132], [220, 132]],
    ]
    assert _reading_order(texts, boxes) == ["좌", "우"]


def test_region_from_cell_boxes_unions_to_bbox():
    """표 셀 박스 목록의 합집합 bbox 를 표 영역으로 계산한다."""
    from paddle_ocr import _region_from_cell_boxes
    cells = [(10, 10, 50, 30), (50, 10, 90, 30), (10, 30, 90, 50)]
    assert _region_from_cell_boxes(cells) == (10, 10, 90, 50)
    assert _region_from_cell_boxes([]) is None


def test_drop_inside_removes_table_region_text():
    """표 영역 안에 들어간 텍스트는 본문에서 제거하고, 밖의 텍스트는 남긴다."""
    from paddle_ocr import _drop_inside
    texts = ["제목 문단", "S.No", "Name", "꼬리말 문단"]
    boxes = [(20, 5, 300, 25),          # 표 위 본문
             (12, 40, 48, 60),           # 표 안
             (52, 40, 120, 60),          # 표 안
             (20, 200, 300, 220)]        # 표 아래 본문
    regions = [(10, 35, 130, 65)]
    kept_t, kept_b = _drop_inside(texts, boxes, regions)
    assert kept_t == ["제목 문단", "꼬리말 문단"]
    assert kept_b == [(20, 5, 300, 25), (20, 200, 300, 220)]


def test_drop_inside_noop_when_no_regions():
    """표 영역이 없으면 모든 텍스트를 그대로 유지한다."""
    from paddle_ocr import _drop_inside
    texts = ["a", "b"]
    boxes = [(0, 0, 10, 10), (0, 20, 10, 30)]
    kept_t, kept_b = _drop_inside(texts, boxes, [])
    assert kept_t == ["a", "b"]
    assert kept_b == boxes


@pytest.mark.skipif(not PADDLE_AVAILABLE, reason="paddleocr not installed")
def test_run_selftest_writes_ok(tmp_path):
    from paddle_ocr import run_selftest
    out = tmp_path / "selftest_ocr.txt"
    assert run_selftest(out) is True
    assert out.read_text(encoding="utf-8").startswith("OK")


@pytest.mark.skipif(not PADDLE_AVAILABLE, reason="paddleocr not installed")
def test_recognize_synthetic_table(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    from paddle_ocr import PaddleTableOCR
    rows = [["Item", "Qty"], ["Apple", "10"], ["Banana", "24"]]
    cw, ch = 180, 56
    img = Image.new("RGB", (cw * 2 + 2, ch * 3 + 2), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for r in range(4):
        d.line([(0, r * ch), (cw * 2, r * ch)], fill="black", width=2)
    for c in range(3):
        d.line([(c * cw, 0), (c * cw, ch * 3)], fill="black", width=2)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            d.text((c * cw + 16, r * ch + 16), v, fill="black", font=font)
    p = tmp_path / "t.png"; img.save(str(p))
    page = PaddleTableOCR().recognize(str(p))
    assert page.table_htmls and "<table" in page.table_htmls[0].lower()
