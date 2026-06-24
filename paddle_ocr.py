"""PaddleOCR TableRecognitionPipelineV2 래퍼 (wired/mobile, mkldnn off, 오프라인).

mkldnn(oneDNN) 은 paddlepaddle 3.3.1 PIR 실행기 버그로 켜면 즉시 크래시한다
(NotImplementedError: ConvertPirAttribute2RuntimeAttribute, onednn_instruction.cc).
FLAGS_enable_pir_api=0 우회도 무효 — off 가 실측으로 확인된 필수값."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from constants import PADDLE_MODELS, PADDLE_REC_BY_LANG, PADDLE_VENDOR_DIRNAME
from logging_config import logger


def _ascii_safe_dir(path: Path) -> Path:
    """paddle C++ 엔진이 Windows 에서 비ASCII 경로의 파일을 열지 못하므로
    (빈 스트림 → "parse error ... empty input"), 한글 등 비ASCII 경로를
    ASCII 경로로 변환한다: 8.3 short path 우선, 안되면 ASCII 위치에 junction."""
    s = str(path)
    if s.isascii() or sys.platform != "win32":
        return path
    import ctypes
    buf = ctypes.create_unicode_buffer(len(s) + 260)
    n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, len(buf))
    if 0 < n < len(buf) and buf.value.isascii():
        return Path(buf.value)
    import _winapi
    import hashlib
    # 대상 경로별로 junction 을 분리(해시 suffix) — 고정 단일 경로면 다른 대상을
    # 변환할 때 기존 링크를 가로채 모델 해석이 깨진다.
    tag = hashlib.sha1(os.path.normcase(s).encode("utf-8")).hexdigest()[:8]
    for base in (os.environ.get("PUBLIC"), os.environ.get("ProgramData")):
        if not base or not base.isascii():
            continue
        link = Path(base) / ".llm_translator" / f"pdx_{tag}"
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.exists():
                try:
                    if os.path.samefile(link, path):
                        return link
                except OSError:
                    pass
                link.rmdir()  # junction 은 rmdir 로 링크만 제거됨
            _winapi.CreateJunction(s, str(link))
            return link
        except OSError:
            continue
    logger.warning("PADDLE: 비ASCII 모델 경로를 ASCII 로 변환하지 못함 — 모델 로드 실패 가능: %s", s)
    return path


def _bundled_cache_home() -> Optional[Path]:
    """오프라인 번들된 PaddleX 캐시 루트(하위에 official_models/ 보유) 탐지.

    frozen(exe) 에서는 _MEIPASS/exe폴더, 개발 모드에서는 vendor/ 를 본다.
    prepare_paddleocr.py 가 만든 <root>/official_models 가 있으면 그 <root> 를 반환."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(os.path.dirname(sys.executable)) / PADDLE_VENDOR_DIRNAME)
        mp = getattr(sys, "_MEIPASS", "")
        if mp:
            candidates.append(Path(mp) / PADDLE_VENDOR_DIRNAME)
    candidates.append(Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME)
    for c in candidates:
        if (c / "official_models").is_dir():
            return c
    return None


# 오프라인 동작 보장: 모델 소스 체크 비활성 + 번들 캐시가 있으면 그쪽을 PaddleX
# 캐시 홈으로 지정한다. PaddleX 는 <PADDLE_PDX_CACHE_HOME>/official_models/<모델>
# 이 존재하면 인터넷 hoster 를 전혀 호출하지 않는다(없을 때만 다운로드 시도).
# 무거운 paddleocr/paddlex import 이전에 환경을 설정해야 적용된다.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
_OFFLINE_CACHE = _bundled_cache_home()
if _OFFLINE_CACHE is not None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_ascii_safe_dir(_OFFLINE_CACHE)))


@dataclass
class PageOCR:
    table_htmls: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)


def _to_xyxy(box) -> Optional[tuple[float, float, float, float]]:
    """rec_boxes 의 [x0,y0,x1,y1] 또는 rec_polys 의 4점 다각형을
    축정렬 bbox (x0,y0,x1,y1) 로 정규화. numpy 배열/스칼라도 허용."""
    if box is None:
        return None
    try:
        first = box[0]
    except (TypeError, IndexError, KeyError):
        return None
    # 다각형: 각 원소가 [x, y] 점(길이 보유) → 꼭짓점들의 min/max
    if hasattr(first, "__len__"):
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
        except (TypeError, ValueError, IndexError):
            return None
        return (min(xs), min(ys), max(xs), max(ys))
    # 축정렬 bbox [x0, y0, x1, y1]
    try:
        x0, y0, x1, y1 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    except (TypeError, ValueError, IndexError):
        return None
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _extract_boxes(ocr: dict, n: int) -> list:
    """overall_ocr_res 에서 텍스트와 1:1 대응하는 bbox 목록을 뽑는다.
    좌표 키가 없거나 개수가 안 맞으면 [None]*n (→ 원래 순서 유지)."""
    for key in ("rec_boxes", "rec_polys", "dt_polys"):
        raw = ocr.get(key)
        if raw is None:
            continue
        try:
            seq = list(raw)
        except TypeError:
            continue
        if len(seq) != n:
            continue
        boxes = [_to_xyxy(b) for b in seq]
        if any(b is not None for b in boxes):
            return boxes
    return [None] * n


def _region_from_cell_boxes(cell_boxes) -> Optional[tuple[float, float, float, float]]:
    """표 셀 박스 목록의 합집합을 표 영역 bbox 로 계산. 비면 None."""
    xys = [xy for b in (cell_boxes or []) if (xy := _to_xyxy(b)) is not None]
    if not xys:
        return None
    return (min(x[0] for x in xys), min(x[1] for x in xys),
            max(x[2] for x in xys), max(x[3] for x in xys))


def _drop_inside(texts: list[str], boxes: list, regions: list):
    """표 영역(regions) 안에 중심이 들어간 텍스트를 본문에서 제거한다.

    표 영역 텍스트는 이미 table_htmls(docx 표)로 렌더되므로 본문에 또 넣으면
    중복되고, 다열 표라면 본문 순서까지 뒤섞는다. 영역 밖 텍스트만 남긴다.
    좌표가 없는(또는 regions 가 빈) 텍스트는 안전하게 유지."""
    if not regions:
        return list(texts), list(boxes)
    kept_t, kept_b = [], []
    for t, b in zip(texts, boxes):
        xy = _to_xyxy(b)
        if xy is not None:
            cx, cy = (xy[0] + xy[2]) / 2, (xy[1] + xy[3]) / 2
            if any(rx0 <= cx <= rx1 and ry0 <= cy <= ry1
                   for (rx0, ry0, rx1, ry1) in regions):
                continue
        kept_t.append(t)
        kept_b.append(b)
    return kept_t, kept_b


def _reading_order(texts: list[str], boxes: list) -> list[str]:
    """좌표 기반 행 우선(row-major) 읽기 순서로 텍스트를 재정렬한다.

    TableRecognitionPipelineV2 의 overall_ocr_res 는 문서 단위 읽기순서 복원이
    없어, 무테두리 2단 키-값 표에서 라벨열과 값열이 검출 원시 순서대로 뒤섞여
    들어온다. 같은 가로 행 밴드(세로 겹침)에 있는 박스들을 한 줄로 묶어 좌→우로
    읽고, 줄은 위→아래로 이어 순서를 복원한다. 좌표가 없으면 원래 순서를 유지."""
    items = [(t, xy) for t, b in zip(texts, boxes or [])
             if t and t.strip() and (xy := _to_xyxy(b)) is not None]
    if not items:
        # 좌표 정보가 없으면 안전하게 원래 순서(빈 텍스트 제외) 유지
        return [t for t in texts if t and t.strip()]

    items.sort(key=lambda it: (it[1][1], it[1][0]))  # top, then left
    lines: list[list[tuple]] = []
    bands: list[tuple[float, float]] = []  # 각 줄의 (top, bottom)
    for t, b in items:
        y0, y1 = b[1], b[3]
        placed = False
        for i in range(len(lines)):
            lt, lb = bands[i]
            overlap = min(y1, lb) - max(y0, lt)
            denom = min(y1 - y0, lb - lt)
            if denom > 0 and overlap > 0.5 * denom:
                lines[i].append((t, b))
                bands[i] = (min(lt, y0), max(lb, y1))
                placed = True
                break
        if not placed:
            lines.append([(t, b)])
            bands.append((y0, y1))

    out: list[str] = []
    for i in sorted(range(len(lines)), key=lambda i: bands[i][0]):
        for t, _ in sorted(lines[i], key=lambda it: it[1][0]):
            out.append(t)
    return out


class PaddleTableOCR:
    def __init__(self, model_root: Optional[Path] = None,
                 source_lang: Optional[str] = None) -> None:
        self._model_root = model_root
        self._pipe = None
        self._rec_model = PADDLE_REC_BY_LANG.get(
            source_lang or "", PADDLE_MODELS["text_recognition_model_name"])

    def set_language(self, source_lang: str) -> None:
        """원본 언어(영문명)에 맞는 rec 모델 선택 — 바뀌면 파이프라인을 지연 재생성.

        translator.set_languages 와 같은 패턴: UI 가 언어 변경 시 호출한다.
        진행 중인 recognize 는 기존 파이프라인 참조로 끝까지 수행된다."""
        rec = PADDLE_REC_BY_LANG.get(
            source_lang, PADDLE_MODELS["text_recognition_model_name"])
        if rec != self._rec_model:
            self._rec_model = rec
            self._pipe = None
            logger.info("PADDLE: rec model -> %s (%s)", rec, source_lang)

    def _kwargs(self) -> dict:
        kw = {
            "use_doc_orientation_classify": True,
            "use_doc_unwarping": False,
            "use_layout_detection": True,
            "enable_mkldnn": False,  # 필수
        }
        models = dict(PADDLE_MODELS)
        models["text_recognition_model_name"] = self._rec_model
        kw.update(models)
        if self._model_root is not None:
            for nk, mn in models.items():
                local = self._model_root / mn
                if local.is_dir():
                    kw[nk.replace("_model_name", "_model_dir")] = str(local)
        return kw

    def _ensure(self):
        if self._pipe is None:
            from paddleocr import TableRecognitionPipelineV2
            self._pipe = TableRecognitionPipelineV2(**self._kwargs())
            logger.info("PADDLE: pipeline ready (wired/mobile, mkldnn off)")
        return self._pipe

    def recognize(self, image_path: str) -> PageOCR:
        page = PageOCR()
        for res in self._ensure().predict(str(image_path)):
            table_regions: list = []
            for t in (res.get("table_res_list") or []):
                html = t.get("pred_html")
                if html:
                    page.table_htmls.append(html)
                    # 표로 렌더된 영역은 본문에서 제외하기 위해 영역 bbox 를 모은다.
                    region = _region_from_cell_boxes(t.get("cell_box_list"))
                    if region is not None:
                        table_regions.append(region)
            ocr = res.get("overall_ocr_res")
            if ocr:
                texts = list(ocr.get("rec_texts") or [])
                boxes = _extract_boxes(ocr, len(texts))
                # 1) 표 영역 텍스트 제거(table_htmls 와 중복·본문 순서 교란 방지)
                texts, boxes = _drop_inside(texts, boxes, table_regions)
                # 2) 남은 본문을 좌표 기반 행 우선 순서로 재정렬(무테두리 다열 본문 대비)
                page.text_blocks.extend(_reading_order(texts, boxes))
        return page


def run_selftest(out_path: Path) -> bool:
    """합성 표 1장을 인식해 OCR 스택(모델 번들·오프라인 해석 포함)을 자가진단한다.

    GUI 없이 배포본 검증용 — frozen 에서는 `python.exe --selftest-ocr`.
    결과를 out_path 에 기록하고 성공 여부를 반환한다."""
    import tempfile
    try:
        from PIL import Image, ImageDraw, ImageFont
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
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "selftest.png"
            img.save(str(p))
            page = PaddleTableOCR().recognize(str(p))
        ok = bool(page.table_htmls and "<table" in page.table_htmls[0].lower())
        detail = "OK" if ok else "FAIL: table not detected"
    except Exception as e:  # noqa: BLE001 — 진단 결과로 남기는 것이 목적
        import traceback
        ok, detail = False, f"FAIL: {type(e).__name__}: {e}\n\n{traceback.format_exc()}"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(detail, encoding="utf-8")
    logger.info("PADDLE selftest: %s", detail)
    return ok
