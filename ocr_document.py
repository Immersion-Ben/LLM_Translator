"""파일 → 페이지별 OCR(PageResult).

- iter_pages(): 페이지를 하나씩 지연 yield. full 모드의 OCR∥번역 페이지
  파이프라인용(생산자가 한 페이지씩 당겨 OCR).
- ocr_document(): iter_pages 를 모아 OcrResult 로 반환(ocr_only 모드용),
  on_page 콜백으로 페이지 도착을 알릴 수 있다.
- count_pages(): 파이프라인에 필요한 총 페이지 수.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterator, Optional

from constants import IMAGE_EXTENSIONS
from ocr_store import PageResult, OcrResult

PageCallback = Callable[[PageResult], None]


def iter_pages(
    filepath: str,
    ocr_engine,                       # paddle_ocr.PaddleTableOCR
    pages_dir: Path,                  # 페이지 이미지 저장 폴더(OCR결과/<doc>_pages)
    pdf_text_extractor=None,          # Callable[[str], list[str]] | None (텍스트레이어)
    dpi: int = 200,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Iterator[PageResult]:
    """페이지를 하나씩 OCR 하여 지연 yield 한다(단일 스레드에서만 소비할 것).

    OCR 은 단일 PaddleOCR 파이프라인을 쓰므로 이 제너레이터를 여러 스레드에서
    동시에 당기면 안 된다(page_pipeline 의 단일 생산자 스레드가 소비)."""
    pages_dir = Path(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filepath).suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        page = ocr_engine.recognize(filepath)
        yield PageResult(0, "ocr", page.table_htmls, page.text_blocks, image=None)
        return

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
                yield PageResult(i, "text", [], [txt], image=None)
                continue
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
            img_name = f"page_{i+1}.png"
            pix.save(str(pages_dir / img_name))
            page = ocr_engine.recognize(str(pages_dir / img_name))
            yield PageResult(i, "ocr", page.table_htmls, page.text_blocks, image=img_name)
    finally:
        doc.close()


def ocr_document(
    filepath: str,
    ocr_engine,
    pages_dir: Path,
    pdf_text_extractor=None,
    dpi: int = 200,
    on_page: Optional[PageCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> OcrResult:
    """iter_pages 를 모아 OcrResult 로 반환(ocr_only 모드)."""
    results: list[PageResult] = []
    for pr in iter_pages(filepath, ocr_engine, pages_dir, pdf_text_extractor, dpi, should_cancel):
        results.append(pr)
        if on_page:
            on_page(pr)
    return OcrResult(source=filepath, pages=results)


def count_pages(filepath: str) -> int:
    """총 페이지 수. 이미지는 1, PDF 는 fitz 페이지 수."""
    if Path(filepath).suffix.lower() in IMAGE_EXTENSIONS:
        return 1
    import fitz
    doc = fitz.open(filepath)
    try:
        return len(doc)
    finally:
        doc.close()
