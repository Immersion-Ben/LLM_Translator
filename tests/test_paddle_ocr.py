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
