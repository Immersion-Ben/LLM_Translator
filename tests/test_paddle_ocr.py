import pytest
from dependencies import PADDLE_AVAILABLE


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
