"""파일 → 페이지별 OCR(PageResult). full 모드 페이지 스트리밍을 위한 on_page 콜백 제공."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from constants import IMAGE_EXTENSIONS
from ocr_store import PageResult, OcrResult

PageCallback = Callable[[PageResult], None]


def ocr_document(
    filepath: str,
    ocr_engine,                       # paddle_ocr.PaddleTableOCR
    pages_dir: Path,                  # 페이지 이미지 저장 폴더(OCR결과/<doc>_pages)
    pdf_text_extractor=None,          # Callable[[str], list[str]] | None (텍스트레이어)
    dpi: int = 200,
    on_page: Optional[PageCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> OcrResult:
    pages_dir = Path(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filepath).suffix.lower()
    results: list[PageResult] = []

    def emit(pr: PageResult):
        results.append(pr)
        if on_page:
            on_page(pr)

    if ext in IMAGE_EXTENSIONS:
        page = ocr_engine.recognize(filepath)
        emit(PageResult(0, "ocr", page.table_htmls, page.text_blocks, image=None))
        return OcrResult(source=filepath, pages=results)

    # PDF
    import fitz
    text_layer = pdf_text_extractor(filepath) if pdf_text_extractor else None
    doc = fitz.open(filepath)
    try:
        for i in range(len(doc)):
            if should_cancel and should_cancel():
                break
            txt = (text_layer[i] if text_layer and i < len(text_layer) else "") or ""
            if len(txt.strip()) >= 10:
                emit(PageResult(i, "text", [], [txt], image=None))
                continue
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
            img_name = f"page_{i+1}.png"
            pix.save(str(pages_dir / img_name))
            page = ocr_engine.recognize(str(pages_dir / img_name))
            emit(PageResult(i, "ocr", page.table_htmls, page.text_blocks, image=img_name))
    finally:
        doc.close()
    return OcrResult(source=filepath, pages=results)
