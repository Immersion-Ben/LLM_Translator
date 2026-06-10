"""파일 형식별 번역 처리. v3: 취소 체크 + 중복 로직 통합."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional

from constants import EXTRACT_DIR_NAME, IMAGE_EXTENSIONS, INPUT_DIR_NAME, RESULT_DIR_NAME
from dependencies import (
    Document,
    Presentation,
    Pt,
    load_workbook,
)
from table_grid import parse_table_html, build_docx_table
from logging_config import logger
from security import validate_input_path

ProgressCallback = Callable[[int, int, str], None]
TextCallback = Callable[[str], None]

# 외부 파서(pypdf/PyMuPDF)가 손상되거나 비정상적인 입력에 대해 던질 수 있는
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
            ".txt": self._translate_txt,
            ".xlsx": self._translate_xlsx,
            ".pptx": self._translate_pptx,
        }
        if ext == ".pdf" or ext in IMAGE_EXTENSIONS:
            raise RuntimeError("이미지/PDF는 작업 큐(JobManager)를 통해 처리됩니다.")
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

    def render_page_to_doc(self, doc, page_result, cell_cache: dict | None = None) -> None:
        """PageResult(표 HTML + 본문) 를 번역해 docx 에 기록. 표 병합 보존."""
        cache = cell_cache if cell_cache is not None else {}

        def translate_cell(text: str) -> str:
            t = text.strip()
            if not t or t.replace(".", "").replace(",", "").replace("%", "").isdigit():
                return text
            if t not in cache:
                self._check_cancel()
                cache[t] = self._translate_and_notify(t) or text
            return cache[t]

        if getattr(page_result, "kind", "ocr") == "text":
            body = "\n".join(page_result.text_blocks).strip()
            if body:
                translated = self._translate_and_notify(body)
                self._add_translated_text(doc, translated or body)
            return
        for html in page_result.table_htmls:
            grid = parse_table_html(html)
            build_docx_table(doc, grid, translate=translate_cell)
            doc.add_paragraph("")
        body = "\n".join(page_result.text_blocks).strip()
        if body:
            translated = self._translate_and_notify(body)
            self._add_translated_text(doc, translated or body)

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

