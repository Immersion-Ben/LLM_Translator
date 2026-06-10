"""파일별 번역 소요시간 추정.

추출된 텍스트의 청크 수와 OCR 페이지 수, 그리고 모드별 평균 호출 시간(이력 기반)
을 결합해 단일 파일의 예상 시간을 계산한다. 평균은 번역 완료 시 EMA 로 갱신된다.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from constants import IMAGE_EXTENSIONS
from dependencies import Document, PdfReader, Presentation, load_workbook
from logging_config import logger

# 파일 파싱 라이브러리가 비정상 입력에 대해 던질 수 있는 예외들.
# 광범위한 ``except Exception`` 대신 구체적으로 명시한다(CWE-754).
_EST_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
    RuntimeError,
    RecursionError,
    MemoryError,
)


@dataclass
class Estimate:
    """단일 파일 추정 결과."""
    chars: int = 0
    chunks: int = 0          # API 호출 횟수 (translate() 호출 단위 합)
    ocr_pages: int = 0       # OCR 처리 대상 페이지 / 이미지 수
    est_seconds: float = 0.0
    est_low: float = 0.0
    est_high: float = 0.0
    confidence: str = "low"  # high | medium | low
    error: Optional[str] = None


class TimeEstimator:
    """파일 형식별 추출 + 모드별 평균으로 시간 추정."""

    OCR_PER_PAGE_S = 12.0
    DEFAULT_AVG_SEC_PER_CHUNK = {"fast": 3.0, "deep": 8.0}
    PDF_SAMPLE_PAGES = 3
    LOW_RANGE_FACTOR = 0.55
    HIGH_RANGE_FACTOR = 1.7
    EMA_ALPHA = 0.3
    AVG_MIN, AVG_MAX = 1.0, 60.0

    def __init__(self, config) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # 평균 (이력 기반 학습)
    # ------------------------------------------------------------------
    def get_avg_per_chunk(self, mode: str) -> float:
        key = f"avg_secs_per_chunk_{mode}"
        try:
            v = float(self.config.get(key) or 0)
        except (TypeError, ValueError):
            v = 0
        if v <= 0:
            return self.DEFAULT_AVG_SEC_PER_CHUNK.get(mode, 5.0)
        return v

    def update_avg(self, mode: str, total_secs: float, chunks: int) -> None:
        """번역 완료 후 실측치로 평균 갱신 (지수 이동 평균)."""
        if chunks <= 0 or total_secs <= 0:
            return
        if mode not in self.DEFAULT_AVG_SEC_PER_CHUNK:
            return
        per_chunk = total_secs / chunks
        prev = self.get_avg_per_chunk(mode)
        new_avg = prev * (1 - self.EMA_ALPHA) + per_chunk * self.EMA_ALPHA
        new_avg = max(self.AVG_MIN, min(self.AVG_MAX, new_avg))
        self.config.set(f"avg_secs_per_chunk_{mode}", str(round(new_avg, 2)))
        try:
            self.config.save()
        except OSError as e:
            logger.error(f"ESTIM-SAVE: {type(e).__name__}")

    # ------------------------------------------------------------------
    # 추정 (백그라운드 스레드에서 호출 권장)
    # ------------------------------------------------------------------
    def estimate(self, filepath: str, mode: str, chunk_size: int) -> Estimate:
        ext = Path(filepath).suffix.lower()
        try:
            if ext == ".txt":
                est = self._est_txt(filepath, chunk_size)
            elif ext == ".docx":
                est = self._est_docx(filepath, chunk_size)
            elif ext == ".xlsx":
                est = self._est_xlsx(filepath, chunk_size)
            elif ext == ".pptx":
                est = self._est_pptx(filepath, chunk_size)
            elif ext == ".pdf":
                est = self._est_pdf(filepath, chunk_size)
            elif ext in IMAGE_EXTENSIONS:
                est = self._est_image(filepath)
            else:
                return Estimate(error=f"지원 안 함: {ext}")
        except _EST_ERRORS as e:
            logger.error(f"ESTIM-{ext}: {type(e).__name__}: {e}")
            return Estimate(error=type(e).__name__)

        avg = self.get_avg_per_chunk(mode)
        est.est_seconds = est.ocr_pages * self.OCR_PER_PAGE_S + est.chunks * avg
        est.est_low = est.est_seconds * self.LOW_RANGE_FACTOR
        est.est_high = est.est_seconds * self.HIGH_RANGE_FACTOR
        return est

    # ------------------------------------------------------------------
    # 형식별 추출
    # ------------------------------------------------------------------
    def _chunks_for(self, text: str, chunk_size: int) -> int:
        if not text or not text.strip():
            return 0
        return max(1, math.ceil(len(text) / max(500, chunk_size)))

    def _est_txt(self, filepath: str, chunk_size: int) -> Estimate:
        path = Path(filepath)
        size = path.stat().st_size
        if size > 1_000_000:
            with open(filepath, "rb") as f:
                sample = f.read(100_000)
            try:
                sample_text = sample.decode("utf-8", errors="replace")
            except (UnicodeError, LookupError):
                sample_text = ""
            ratio = size / max(1, len(sample))
            est_chars = int(len(sample_text) * ratio)
        else:
            est_chars = 0
            for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
                try:
                    est_chars = len(path.read_text(encoding=enc))
                    break
                except UnicodeDecodeError:
                    continue
                except OSError:
                    break
            if est_chars == 0:
                est_chars = size  # 최후 폴백
        chunks = max(1, math.ceil(est_chars / max(500, chunk_size)))
        return Estimate(chars=est_chars, chunks=chunks, confidence="high")

    def _est_docx(self, filepath: str, chunk_size: int) -> Estimate:
        if Document is None:
            return Estimate(error="python-docx 없음")
        doc = Document(filepath)
        chars = 0
        chunks = 0
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                chars += len(t)
                chunks += self._chunks_for(t, chunk_size)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        t = (p.text or "").strip()
                        if t:
                            chars += len(t)
                            chunks += self._chunks_for(t, chunk_size)
        return Estimate(chars=chars, chunks=chunks, confidence="high")

    def _est_xlsx(self, filepath: str, chunk_size: int) -> Estimate:
        if load_workbook is None:
            return Estimate(error="openpyxl 없음")
        wb = load_workbook(filepath, read_only=True, data_only=True)
        chars = 0
        chunks = 0
        try:
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    for v in row:
                        if isinstance(v, str):
                            t = v.strip()
                            if t:
                                chars += len(t)
                                chunks += self._chunks_for(t, chunk_size)
        finally:
            wb.close()
        return Estimate(chars=chars, chunks=chunks, confidence="high")

    def _est_pptx(self, filepath: str, chunk_size: int) -> Estimate:
        if Presentation is None:
            return Estimate(error="python-pptx 없음")
        prs = Presentation(filepath)
        chars = 0
        chunks = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for p in shape.text_frame.paragraphs:
                    t = (p.text or "").strip()
                    if t:
                        chars += len(t)
                        chunks += self._chunks_for(t, chunk_size)
        return Estimate(chars=chars, chunks=chunks, confidence="high")

    def _est_pdf(self, filepath: str, chunk_size: int) -> Estimate:
        if PdfReader is None:
            return Estimate(error="pypdf 없음")
        with open(filepath, "rb") as f:
            data = f.read()
        reader = PdfReader(io.BytesIO(data), strict=False)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return Estimate(error="빈 PDF")

        sample_n = min(self.PDF_SAMPLE_PAGES, total_pages)
        sample_chars = 0
        sample_scan_pages = 0
        for i in range(sample_n):
            try:
                t = (reader.pages[i].extract_text() or "").strip()
            except _EST_ERRORS:
                t = ""
            if len(t) < 10:
                sample_scan_pages += 1
            else:
                sample_chars += len(t)

        # 외삽
        scan_ratio = sample_scan_pages / sample_n if sample_n else 0
        est_scan_pages = int(round(total_pages * scan_ratio))
        text_pages = total_pages - est_scan_pages
        sampled_text_pages = max(1, sample_n - sample_scan_pages)
        avg_chars_per_text_page = (
            sample_chars / sampled_text_pages
            if sample_n > sample_scan_pages else 0
        )
        chars = int(avg_chars_per_text_page * text_pages)

        # 텍스트 페이지: 페이지당 1+ chunk, 스캔 페이지: OCR 후 1 chunk 가정
        if text_pages > 0:
            chunks_per_text_page = max(
                1, math.ceil(avg_chars_per_text_page / max(500, chunk_size))
            )
            text_chunks = chunks_per_text_page * text_pages
        else:
            text_chunks = 0
        chunks = text_chunks + est_scan_pages  # 스캔 = OCR + 1 chunk

        if est_scan_pages == 0:
            confidence = "high"
        elif est_scan_pages < total_pages:
            confidence = "medium"
        else:
            confidence = "low"
        return Estimate(
            chars=chars,
            chunks=chunks,
            ocr_pages=est_scan_pages,
            confidence=confidence,
        )

    def _est_image(self, filepath: str) -> Estimate:
        # 이미지: OCR 1회 + 1~3 chunk 가정. 파일 크기로 거친 보정.
        try:
            size = Path(filepath).stat().st_size
        except OSError:
            size = 0
        if size > 5_000_000:
            chunks = 3
        elif size > 1_000_000:
            chunks = 2
        else:
            chunks = 1
        return Estimate(chars=0, chunks=chunks, ocr_pages=1, confidence="low")


# ----------------------------------------------------------------------
# 표시 헬퍼
# ----------------------------------------------------------------------
def format_secs(s: float) -> str:
    """초 → 사람이 읽기 좋은 형태."""
    if s < 5:
        return "<5초"
    if s < 60:
        return f"{int(round(s))}초"
    m = s / 60
    if m < 10:
        return f"{m:.1f}분"
    if m < 60:
        return f"{int(round(m))}분"
    h = m / 60
    return f"{h:.1f}시간"


def format_estimate_label(est: Estimate) -> str:
    """파일 행 뱃지용 짧은 표시."""
    if est is None or est.error:
        return ""
    return f"~{format_secs(est.est_seconds)}"


def format_estimate_range(est: Estimate) -> str:
    """범위 표시 (툴팁 등)."""
    if est is None or est.error:
        return ""
    return f"{format_secs(est.est_low)} ~ {format_secs(est.est_high)}"
