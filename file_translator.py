"""파일 형식별 번역 처리. v3: 취소 체크 + 중복 로직 통합."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

from constants import EXTRACT_DIR_NAME, IMAGE_EXTENSIONS, INPUT_DIR_NAME, RESULT_DIR_NAME
from dependencies import (
    Document,
    Image,
    PdfReader,
    Presentation,
    Pt,
    load_workbook,
    pymupdf,
    pytesseract,
)
from logging_config import logger
from security import validate_input_path

ProgressCallback = Callable[[int, int, str], None]
TextCallback = Callable[[str], None]

# 외부 파서(pypdf/PyMuPDF/Tesseract)가 손상되거나 비정상적인 입력에 대해 던질 수 있는
# 예외들. 광범위한 ``except Exception`` 대신 구체적으로 명시하여(CWE-754) 폴백 동작은
# 유지하되 예기치 못한 프로그래밍 오류는 그대로 전파되도록 한다.
_EXTRACT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
    RuntimeError,
    RecursionError,
    MemoryError,
    UnicodeError,
    ZeroDivisionError,
)


class FileTranslator:
    """파일 형식별 번역 처리."""

    def __init__(self, translator) -> None:
        self.translator = translator
        self._on_extract: Optional[TextCallback] = None
        self._on_translate: Optional[TextCallback] = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def translate_file(
        self,
        filepath: str,
        cb: Optional[ProgressCallback] = None,
        on_extract: Optional[TextCallback] = None,
        on_translate: Optional[TextCallback] = None,
    ) -> str:
        """단일 파일 번역 후 결과 파일 경로 반환."""
        # CWE-22: 외부 입력 경로를 파일 작업에 사용하기 전에 검증/정규화한다.
        filepath = str(validate_input_path(filepath))
        self._on_extract = on_extract
        self._on_translate = on_translate
        ext = Path(filepath).suffix.lower()

        handlers = {
            ".docx": self._translate_docx,
            ".pdf": self._translate_pdf,
            ".txt": self._translate_txt,
            ".xlsx": self._translate_xlsx,
            ".pptx": self._translate_pptx,
        }
        if ext in IMAGE_EXTENSIONS:
            return self._translate_image(filepath, cb)
        handler = handlers.get(ext)
        if handler:
            return handler(filepath, cb)
        raise ValueError(f"지원하지 않는 파일 형식: {ext}")

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------
    def _check_cancel(self) -> None:
        if hasattr(self.translator, "is_cancelled") and self.translator.is_cancelled():
            from translator_engine import TranslationCancelled
            raise TranslationCancelled("사용자가 번역을 취소했습니다.")

    def _notify_extract(self, text: str) -> None:
        if self._on_extract and text and text.strip():
            self._on_extract(text)

    def _notify_translate(self, text: str) -> None:
        if self._on_translate and text and text.strip():
            self._on_translate(text)

    def _translate_and_notify(self, text: str) -> str:
        self._check_cancel()
        translated = self.translator.translate(text)
        self._notify_translate(translated)
        return translated

    def _result_dir(self, filepath: str) -> Path:
        """번역 결과물 저장 디렉터리."""
        src = Path(filepath)
        if src.parent.name == INPUT_DIR_NAME:
            result_dir = src.parent.parent / RESULT_DIR_NAME
        else:
            result_dir = src.parent / RESULT_DIR_NAME
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_dir

    def _output_path(self, filepath: str, new_ext: Optional[str] = None) -> str:
        p = Path(filepath)
        ext = new_ext or p.suffix
        return str(self._result_dir(filepath) / f"{p.stem}_translated{ext}")

    def _intermediate_text_dir(self, source_filepath: str) -> Path:
        """OCR 중간 txt 저장 디렉터리."""
        src = Path(source_filepath)
        if src.parent.name == INPUT_DIR_NAME:
            txt_dir = src.parent.parent / EXTRACT_DIR_NAME
        else:
            txt_dir = (Path.home() / "Desktop") / EXTRACT_DIR_NAME
        txt_dir.mkdir(parents=True, exist_ok=True)
        return txt_dir

    def _save_intermediate_text(
        self, source_filepath: str, text: str, suffix: str = "_ocr_source.txt"
    ) -> str:
        src = Path(source_filepath)
        txt_dir = self._intermediate_text_dir(source_filepath)
        txt_path = txt_dir / f"{src.stem}{suffix}"
        txt_path.write_text(text or "", encoding="utf-8")
        return str(txt_path)

    @staticmethod
    def _read_text_file(filepath: str) -> str:
        """인코딩 이슈에 대비해 txt를 안전하게 읽기."""
        for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    # ------------------------------------------------------------------
    # DOCX
    # ------------------------------------------------------------------
    def _iter_docx_paragraphs(self, doc) -> Iterable:
        """본문 + 표 셀의 모든 paragraph를 순회."""
        for para in doc.paragraphs:
            yield para
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield para

    def _translate_docx(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        doc = Document(filepath)
        output = self._output_path(filepath)

        all_paragraphs = list(self._iter_docx_paragraphs(doc))
        extract_text = "\n".join(p.text for p in all_paragraphs if p.text.strip())
        self._notify_extract(extract_text)

        total = len(all_paragraphs) or 1
        for i, para in enumerate(all_paragraphs):
            self._check_cancel()
            if cb:
                cb(i + 1, total, f"문단 {i+1}/{total} 번역 중...")
            if not para.text.strip():
                continue
            translated = self._translate_and_notify(para.text)
            if not translated or translated == para.text:
                continue
            runs = para.runs
            if len(runs) <= 1:
                if runs:
                    runs[0].text = translated
            else:
                runs[0].text = translated
                for run in runs[1:]:
                    run.text = ""

        doc.save(output)
        return output

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------
    def _add_translated_text(self, doc, translated: str) -> None:
        paragraphs = re.split(r"\n\s*\n", translated)
        for para_text in paragraphs:
            para_text = para_text.strip()
            if not para_text:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            lines = para_text.split("\n")
            for i, line in enumerate(lines):
                run = p.add_run(line)
                if i < len(lines) - 1:
                    run.add_break()

    def _translate_pdf(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        output = self._output_path(filepath, ".docx")

        with open(filepath, "rb") as f:
            pdf_bytes = f.read()

        logger.info(f"PDF-DEBUG: file loaded, size={len(pdf_bytes)} bytes")

        page_texts: list[str] = []

        # 1) pypdf로 텍스트 추출 시도
        if PdfReader is not None:
            try:
                import io
                reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
                total = len(reader.pages)
                for page_num, page in enumerate(reader.pages):
                    self._check_cancel()
                    if cb:
                        cb(page_num + 1, total, f"PDF 텍스트 추출 중... 페이지 {page_num+1}/{total}")
                    try:
                        text = page.extract_text() or ""
                    except _EXTRACT_ERRORS:
                        text = ""
                    page_texts.append(text)
            except _EXTRACT_ERRORS:
                logger.error("PDF-01: pypdf failed")
                page_texts = []

        # 2) pypdf가 실패했거나 페이지 수를 못 얻은 경우 PyMuPDF로 재시도
        if not page_texts and pymupdf is not None:
            try:
                pdf_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                try:
                    for page_num in range(len(pdf_doc)):
                        self._check_cancel()
                        page_texts.append(pdf_doc[page_num].get_text() or "")
                finally:
                    pdf_doc.close()
            except _EXTRACT_ERRORS:
                logger.error("PDF-02: PyMuPDF text extraction failed")
                page_texts = []

        if not page_texts:
            raise RuntimeError(
                "PDF 처리 실패: 페이지를 읽을 수 없습니다. "
                "(PyMuPDF 모듈이 누락되어 OCR 폴백이 동작하지 않을 수 있습니다.)"
            )

        # 3) 텍스트가 부족한 페이지는 OCR 폴백
        ocr_capable = pymupdf is not None and pytesseract is not None and Image is not None
        ocr_attempted = False
        for page_num, text in enumerate(page_texts):
            if len(text.strip()) >= 10:
                continue
            if not ocr_capable:
                continue
            self._check_cancel()
            if cb:
                cb(page_num + 1, len(page_texts), f"PDF OCR 중... 페이지 {page_num+1}/{len(page_texts)}")
            ocr_text = self._ocr_pdf_page_from_bytes(pdf_bytes, page_num)
            if not ocr_text:
                ocr_text = self._ocr_pdf_page(filepath, page_num)
            if ocr_text:
                page_texts[page_num] = ocr_text
                ocr_attempted = True

        full_text = "\n\n".join(t.strip() for t in page_texts if t and t.strip())
        if not full_text.strip():
            if not ocr_capable:
                raise RuntimeError(
                    "PDF 처리 실패: 텍스트 레이어가 없는 PDF입니다. "
                    "OCR이 필요하지만 PyMuPDF 또는 Tesseract가 사용 가능하지 않습니다."
                )
            raise RuntimeError(
                "PDF 처리 실패: 모든 페이지에서 텍스트를 추출하지 못했습니다. "
                "(OCR 시도 여부: " + ("yes" if ocr_attempted else "no") + ")"
            )

        self._notify_extract(full_text)

        # 4) 번역 및 docx 작성
        doc = Document()
        total = len(page_texts)
        for page_num, text in enumerate(page_texts):
            self._check_cancel()
            if cb:
                cb(page_num + 1, total, f"PDF 번역 중... 페이지 {page_num+1}/{total}")
            if text and text.strip():
                translated = self._translate_and_notify(text.strip())
                if translated:
                    self._add_translated_text(doc, translated)
            if page_num < total - 1:
                doc.add_page_break()

        doc.save(output)
        return output

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    def _ocr_pdf_page(self, filepath: str, page_num: int) -> str:
        if pymupdf is None or pytesseract is None or Image is None:
            return ""
        pdf_doc = None
        try:
            pdf_doc = pymupdf.open(filepath)
            page = pdf_doc[page_num]
            mat = pymupdf.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pdf_doc.close()
            pdf_doc = None
            ocr_lang = self.translator.get_ocr_lang()
            return self._safe_ocr(img, ocr_lang)
        except FileNotFoundError:
            logger.error("ERROR-03: PDF file not found")
        except IndexError:
            logger.error("ERROR-04: Invalid page number")
        except pytesseract.TesseractError:
            logger.error("ERROR-05: Tesseract engine error")
        except Exception:
            logger.error("ERROR-06: Unexpected OCR failure")
        finally:
            if pdf_doc is not None:
                pdf_doc.close()
        return ""

    def _ocr_pdf_page_from_bytes(self, pdf_bytes: bytes, page_num: int) -> str:
        if pymupdf is None or pytesseract is None or Image is None:
            return ""
        pdf_doc = None
        try:
            pdf_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            page = pdf_doc[page_num]
            mat = pymupdf.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pdf_doc.close()
            pdf_doc = None
            ocr_lang = self.translator.get_ocr_lang()
            return self._safe_ocr(img, ocr_lang)
        except _EXTRACT_ERRORS:
            logger.error("ERROR-07: OCR from bytes failed")
        finally:
            if pdf_doc is not None:
                pdf_doc.close()
        return ""

    def _safe_ocr(self, img, ocr_lang: str) -> str:
        """Windows에서 콘솔 창이 뜨지 않도록 subprocess.Popen 래핑."""
        import subprocess

        original_popen = subprocess.Popen

        def patched_popen(*args, **kwargs):
            if sys.platform == "win32":
                startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = startupinfo
                if "stdin" not in kwargs:
                    kwargs["stdin"] = subprocess.DEVNULL
            return original_popen(*args, **kwargs)

        subprocess.Popen = patched_popen
        try:
            try:
                return pytesseract.image_to_string(img, lang=ocr_lang)
            except UnicodeDecodeError:
                # 문자열 디코딩 실패 시 바이트 출력으로 재시도한다(아래 BYTES 경로).
                logger.debug("OCR-DEC: 문자열 디코딩 실패, 바이트 출력으로 재시도")

            raw = pytesseract.image_to_string(
                img, lang=ocr_lang, output_type=pytesseract.Output.BYTES
            )
            for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, AttributeError):
                    continue
            return raw.decode("utf-8", errors="replace")
        finally:
            subprocess.Popen = original_popen

    # ------------------------------------------------------------------
    # TXT
    # ------------------------------------------------------------------
    def _translate_txt(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        content = self._read_text_file(filepath)
        self._notify_extract(content)

        output = self._output_path(filepath, ".docx")
        doc = Document()

        paragraphs = re.split(r"\n{2,}", content)
        total = len(paragraphs) or 1
        for i, para in enumerate(paragraphs):
            self._check_cancel()
            if cb:
                cb(i + 1, total, f"문단 {i+1}/{total} 번역 중...")
            if para.strip():
                translated = self._translate_and_notify(para.strip())
                doc.add_paragraph(translated or para)
            else:
                doc.add_paragraph("")

        doc.save(output)
        return output

    # ------------------------------------------------------------------
    # XLSX
    # ------------------------------------------------------------------
    def _translate_xlsx(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        if load_workbook is None:
            raise ImportError("openpyxl 필요: conda install -c conda-forge openpyxl")

        wb = load_workbook(filepath)
        output = self._output_path(filepath)

        all_text = [
            cell.value
            for sheet in wb.worksheets
            for row in sheet.iter_rows()
            for cell in row
            if cell.value and isinstance(cell.value, str) and cell.value.strip()
        ]
        self._notify_extract("\n".join(all_text))

        for sheet in wb.worksheets:
            total_rows = sheet.max_row or 1
            for row_idx, row in enumerate(sheet.iter_rows(), 1):
                self._check_cancel()
                if cb:
                    cb(row_idx, total_rows, f"시트 '{sheet.title}' 행 {row_idx}/{total_rows}")
                for cell in row:
                    if cell.value and isinstance(cell.value, str) and cell.value.strip():
                        translated = self._translate_and_notify(cell.value)
                        if translated:
                            cell.value = translated

        wb.save(output)
        return output

    # ------------------------------------------------------------------
    # PPTX
    # ------------------------------------------------------------------
    def _translate_pptx(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        if Presentation is None:
            raise ImportError("python-pptx 필요: conda install -c conda-forge python-pptx")

        prs = Presentation(filepath)
        output = self._output_path(filepath)
        total = len(prs.slides) or 1

        all_text: list[str] = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            all_text.append(para.text)
        self._notify_extract("\n".join(all_text))

        for slide_idx, slide in enumerate(prs.slides):
            self._check_cancel()
            if cb:
                cb(slide_idx + 1, total, f"슬라이드 {slide_idx+1}/{total}")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            translated = self._translate_and_notify(para.text)
                            if translated and translated != para.text and para.runs:
                                para.runs[0].text = translated
                                for run in para.runs[1:]:
                                    run.text = ""

        prs.save(output)
        return output

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------
    def _translate_image(self, filepath: str, cb: Optional[ProgressCallback]) -> str:
        if pytesseract is None or Image is None:
            raise ImportError("pytesseract, Pillow 필요")

        if cb:
            cb(1, 3, "OCR 텍스트 추출 중...")

        img = Image.open(filepath)
        ocr_lang = self.translator.get_ocr_lang()
        try:
            text = self._safe_ocr(img, ocr_lang)
        except _EXTRACT_ERRORS as ocr_err:
            raise RuntimeError(f"OCR 실행 실패 ({type(ocr_err).__name__})")

        if cb:
            cb(2, 3, "OCR 텍스트 저장 중...")

        self._save_intermediate_text(filepath, text, suffix="_ocr_source.txt")
        self._notify_extract(text)

        if not text or not text.strip():
            raise RuntimeError("OCR 결과가 비어 있어 번역할 수 없습니다.")

        if cb:
            cb(3, 3, "FabriX 번역 중...")

        doc = Document()
        paragraphs = re.split(r"\n{2,}", text.strip())
        total = len(paragraphs) or 1
        for i, para in enumerate(paragraphs):
            self._check_cancel()
            if cb:
                cb(3, 3, f"FabriX 번역 중... 문단 {i+1}/{total}")
            if para.strip():
                translated = self._translate_and_notify(para.strip())
                doc.add_paragraph(translated or para)
            else:
                doc.add_paragraph("")

        src = Path(filepath)
        output = str(self._result_dir(filepath) / f"{src.stem}_translated.docx")
        doc.save(output)
        return output
