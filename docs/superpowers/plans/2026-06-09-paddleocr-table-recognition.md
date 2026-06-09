# PaddleOCR 표 인식 + OCR 작업 큐(영속) + 파이프라인 번역 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OCR 엔진을 Tesseract→PaddleOCR로 완전 교체해 **표 구조(병합 포함)를 보존**하고, OCR과 번역을 분리한 **영속 작업 큐**를 도입한다. 사용자는 (1) OCR+번역 자동(페이지 단위 OCR∥번역 스트리밍) 또는 (2) OCR만 먼저 → 원할 때 번역, 두 흐름을 쓴다. OCR 산출물은 번역결과처럼 로컬 파일로 저장되고, 작은 중앙 색인으로 **재시작 후에도 완료 목록이 복원**된다. 모든 모델은 사내 오프라인망에서 로컬 구동된다.

**Architecture:** `paddle_ocr.py`(wired+server, mkldnn off, 오프라인 model_dir)가 페이지 이미지→표 HTML+본문을 인식한다. `table_grid.py`(순수)가 HTML colspan/rowspan→python-docx 병합표로 복원한다. `ocr_store.py`가 페이지별 OCR 결과를 원본 옆 `OCR결과/<doc>.ocr.json`(+페이지 이미지)으로 직렬화한다. `job_store.py`가 가벼운 중앙 색인(`~/.llm_translator/jobs.json`)으로 작업 상태/위치를 추적한다. `job_manager.py`가 OCR 큐·번역 큐 2개 워커로 상태머신을 돌리며, full 모드는 페이지 단위로 OCR(CPU)∥번역(I/O)을 겹친다. `app_ui.py`에 작업 목록 패널을 더한다.

**Tech Stack:** Python 3.13, paddlepaddle 3.3.1(CPU), paddleocr 3.6.0/paddlex 3.6.1, beautifulsoup4, python-docx, PyMuPDF, tkinter, pytest, PyInstaller.

---

## 검증된 사전 결정 (스파이크)

- `enable_mkldnn=False` 필수(paddle 3.x PIR+oneDNN 크래시 회피). 오프라인 동작 확인(`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`+캐시 모델). 모델 구성: **wired 전용 + server rec**.
- 결과 필드: 표 HTML=`table_res_list[i]["pred_html"]`, 본문=`overall_ocr_res["rec_texts"]`. 병합은 colspan/rowspan으로 정확 추출 확인.

## 사용자 확정 설계

- **모드1(full)**: 파일 전체 OCR 후 번역이 아니라 **페이지 스트리밍** — page1 OCR→page1 번역과 page2 OCR 동시 진행.
- **모드2(ocr_only)**: OCR만 수행·저장 후 정지. 사용자가 나중에 번역 큐 투입.
- **번역도 큐**로 처리(클릭 즉시 단건 포그라운드 아님).
- **저장**: OCR 산출물은 원본 옆 로컬 파일(`OCR결과/`, **페이지 이미지 포함**). 번역 결과는 기존 `번역결과/`.
- **재시작 목록 복원**: 가벼운 중앙 색인 `~/.llm_translator/jobs.json`.
- **UI**: 기존 화면에 작업 목록 패널 추가.

## 상태 머신
```
QUEUED → OCR_RUNNING → OCR_DONE ─(mode=full: 페이지마다 자동)→ TRANSLATING → DONE
                            └─(mode=ocr_only)→ 대기 → (사용자 클릭) → TRANS_QUEUED → TRANSLATING → DONE
   any → FAILED
재시작 복구: OCR_RUNNING→QUEUED 재투입, TRANSLATING/TRANS_QUEUED→OCR_DONE 로 되돌림
```

## File Structure

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `table_grid.py` | (순수) 표 HTML→격자→python-docx 병합표 | 신규 |
| `paddle_ocr.py` | PaddleOCR 래퍼(wired/server, 오프라인) → `PageOCR` | 신규 |
| `ocr_document.py` | 파일→페이지별 OCR(`PageResult` 목록), PDF 렌더·텍스트레이어 판정 | 신규 |
| `ocr_store.py` | (순수+FS) 페이지별 OCR 결과 ↔ `OCR결과/<doc>.ocr.json`(+이미지) | 신규 |
| `job_store.py` | (FS) 중앙 색인 `jobs.json` CRUD, 원자적 저장, 재시작 복구 | 신규 |
| `job_manager.py` | OCR/번역 큐 2워커, 상태머신, full 모드 페이지 스트리밍 | 신규 |
| `page_pipeline.py` | 생산자(OCR)–소비자(번역) 순서보존 파이프라인 유틸 | 신규 |
| `constants.py` | OCR_DIR_NAME, 모델 구성/경로 상수, 상태·모드 상수 | 수정 |
| `dependencies.py` | pytesseract 제거 → `PADDLE_AVAILABLE` | 수정 |
| `config_manager.py` | `paddleocr_model_root()` | 수정 |
| `file_translator.py` | OCR/번역 분리, 표→Word 병합표, 잔재 제거 | 수정(대규모) |
| `app_ui.py` | 작업 목록 패널 + JobManager 연동, tesseract 호출 제거 | 수정 |
| `settings_dialog.py` | Tesseract 경로 UI 제거 | 수정 |
| `prepare_paddleocr.py` / `build_exe.py` | 모델 수집·번들 | 신규/수정 |
| `tests/...` | table_grid·ocr_store·job_store·page_pipeline 단위 테스트, paddle 스모크 | 신규 |

> 테스트 전략: 순수/FS 로직(`table_grid`,`ocr_store`,`job_store`,`page_pipeline`)은 **정통 TDD**. 모델 추론·워커 통합은 **스모크+실제 PDF 수동 검증**.

---

## Task 0: 환경 준비

- [ ] **Step 1: git 초기화**

Run:
```bash
cd "<project_root>"
git init
printf "vendor/\nbuild/\ndist/\n__pycache__/\n*.pyc\n.paddlex/\n" > .gitignore
git add -A && git commit -m "chore: baseline before PaddleOCR + job-queue migration"
```

- [ ] **Step 2: pytest + tests 패키지**

Run:
```bash
python -m pip install pytest
mkdir -p tests && printf "" > tests/__init__.py
git add tests/__init__.py .gitignore && git commit -m "chore: add tests package"
```

---

## Task 1: `table_grid.py` — HTML 표 → 격자 파싱 (TDD)

**Files:** Create `table_grid.py`, `tests/test_table_grid.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_table_grid.py`:
```python
from table_grid import parse_table_html, TableGrid, GridCell


def _cell(g, row, col):
    for c in g.cells:
        if c.row == row and c.col == col:
            return c
    raise AssertionError(f"no origin cell at ({row},{col})")


def test_simple_grid():
    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    g = parse_table_html(html)
    assert (g.n_rows, g.n_cols) == (2, 2)
    assert _cell(g, 1, 1).text == "D"


def test_colspan_shifts_following_cell():
    html = "<table><tr><td colspan='3'>T</td><td>X</td></tr></table>"
    g = parse_table_html(html)
    assert g.n_cols == 4
    assert _cell(g, 0, 0).colspan == 3
    assert _cell(g, 0, 3).text == "X"


def test_rowspan_tracks_column():
    html = "<table><tr><td rowspan='2'>R</td><td>a</td></tr><tr><td>b</td></tr></table>"
    g = parse_table_html(html)
    assert (g.n_rows, g.n_cols) == (2, 2)
    assert _cell(g, 1, 1).text == "b"


def test_tolerates_unclosed_tbody():
    html = "<html><body><table><tr><td>A</td><td>B</td></tr></tbody></table></body></html>"
    g = parse_table_html(html)
    assert (g.n_rows, g.n_cols) == (1, 2)
```

- [ ] **Step 2: 실패 확인** — Run `python -m pytest tests/test_table_grid.py -v` → FAIL(ModuleNotFound).

- [ ] **Step 3: 구현** — `table_grid.py`:
```python
"""표 HTML(pred_html) ↔ 격자 모델 ↔ python-docx 병합표 (순수 로직)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bs4 import BeautifulSoup


@dataclass
class GridCell:
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


@dataclass
class TableGrid:
    n_rows: int
    n_cols: int
    cells: list[GridCell] = field(default_factory=list)


def parse_table_html(html: str) -> TableGrid:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return TableGrid(0, 0, [])
    rows = table.find_all("tr")
    cells: list[GridCell] = []
    occupied: set[tuple[int, int]] = set()
    n_cols = 0
    for r, tr in enumerate(rows):
        c = 0
        for td in tr.find_all(["td", "th"]):
            while (r, c) in occupied:
                c += 1
            colspan = int(td.get("colspan", 1) or 1)
            rowspan = int(td.get("rowspan", 1) or 1)
            cells.append(GridCell(td.get_text(strip=True), r, c, rowspan, colspan))
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr or dc:
                        occupied.add((r + dr, c + dc))
            c += colspan
            n_cols = max(n_cols, c)
    return TableGrid(len(rows), n_cols, cells)
```

- [ ] **Step 4: 통과 확인** — Run `python -m pytest tests/test_table_grid.py -v` → PASS.
- [ ] **Step 5: 커밋** — `git add table_grid.py tests/test_table_grid.py && git commit -m "feat: parse table HTML into span-aware grid"`

---

## Task 2: `table_grid.py` — python-docx 병합표 빌더 (TDD)

**Files:** Modify `table_grid.py`, `tests/test_table_grid.py`

- [ ] **Step 1: 실패 테스트 추가**
```python
from docx import Document
from table_grid import build_docx_table


def test_build_docx_merges_and_translates():
    g = parse_table_html("<table><tr><td colspan='2'>Header</td></tr><tr><td>a</td><td>b</td></tr></table>")
    doc = Document()
    table = build_docx_table(doc, g, translate=lambda s: s.upper())
    assert (len(table.rows), len(table.columns)) == (2, 2)
    assert table.cell(0, 0)._tc is table.cell(0, 1)._tc  # 병합됨
    assert table.cell(0, 0).text == "HEADER"
    assert table.cell(1, 1).text == "B"
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_table_grid.py::test_build_docx_merges_and_translates -v` → FAIL.

- [ ] **Step 3: 구현 추가** — `table_grid.py` 끝:
```python
def build_docx_table(document, grid: TableGrid, translate: Callable[[str], str]):
    if grid.n_rows == 0 or grid.n_cols == 0:
        return None
    table = document.add_table(rows=grid.n_rows, cols=grid.n_cols)
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    for cell in grid.cells:
        origin = table.cell(cell.row, cell.col)
        if cell.rowspan > 1 or cell.colspan > 1:
            far = table.cell(
                min(cell.row + cell.rowspan - 1, grid.n_rows - 1),
                min(cell.col + cell.colspan - 1, grid.n_cols - 1),
            )
            target = origin.merge(far)
        else:
            target = origin
        target.text = translate(cell.text) if cell.text else ""
    return table
```

- [ ] **Step 4: 통과 확인** — PASS (5 passed).
- [ ] **Step 5: 커밋** — `git commit -am "feat: build merged docx table from grid"`

---

## Task 3: `dependencies.py` + `constants.py` + `config_manager.py`

**Files:** Modify 3개

- [ ] **Step 1: `dependencies.py` pytesseract 블록 교체**
```python
# OCR 엔진: PaddleOCR (Tesseract 완전 대체). 무거운 import 는 사용 시점까지 미룬다.
try:
    import importlib.util as _ilu
    PADDLE_AVAILABLE = _ilu.find_spec("paddle") is not None and _ilu.find_spec("paddleocr") is not None
except (ImportError, ValueError):
    PADDLE_AVAILABLE = False
pytesseract = None  # 잔존 참조 안전 처리(이후 제거)
```

- [ ] **Step 2: `constants.py` 추가** (OCR_LANG_MAP 아래)
```python
# OCR 산출물 폴더(원본 옆), 번역결과(번역결과)와 동격
OCR_DIR_NAME = "OCR결과"

# 중앙 색인(재시작 목록 복원용)
JOBS_INDEX_PATH = "~/.llm_translator/jobs.json"

# 작업 상태 / 모드
class JobStatus:
    QUEUED = "QUEUED"
    OCR_RUNNING = "OCR_RUNNING"
    OCR_DONE = "OCR_DONE"
    TRANS_QUEUED = "TRANS_QUEUED"
    TRANSLATING = "TRANSLATING"
    DONE = "DONE"
    FAILED = "FAILED"

MODE_FULL = "full"
MODE_OCR_ONLY = "ocr_only"

# PaddleOCR 오프라인 모델
PADDLE_VENDOR_DIRNAME = "paddleocr-models"
PADDLE_MODELS: dict[str, str] = {
    "layout_detection_model_name": "PP-DocLayout-L",
    "table_classification_model_name": "PP-LCNet_x1_0_table_cls",
    "wired_table_structure_recognition_model_name": "SLANeXt_wired",
    "wired_table_cells_detection_model_name": "RT-DETR-L_wired_table_cell_det",
    "doc_orientation_classify_model_name": "PP-LCNet_x1_0_doc_ori",
    "text_detection_model_name": "PP-OCRv4_server_det",
    "text_recognition_model_name": "PP-OCRv4_server_rec_doc",
}
```

- [ ] **Step 3: `config_manager.py`** — `apply_tesseract_path` 메서드(178~208행)를 교체:
```python
    def paddleocr_model_root(self):
        """번들/캐시된 PaddleOCR 모델 루트. _MEIPASS→exe폴더→vendor→~/.paddlex 순."""
        import os, sys
        from pathlib import Path
        from constants import PADDLE_VENDOR_DIRNAME
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(os.path.dirname(sys.executable)) / PADDLE_VENDOR_DIRNAME)
            mp = getattr(sys, "_MEIPASS", "")
            if mp:
                candidates.append(Path(mp) / PADDLE_VENDOR_DIRNAME)
        candidates.append(Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME)
        candidates.append(Path.home() / ".paddlex" / "official_models")
        for c in candidates:
            if c.is_dir():
                return c
        return None

    def apply_tesseract_path(self) -> None:
        return  # no-op 셰임(호출부 보호, 이후 제거)
```

- [ ] **Step 4: 확인** — Run:
```bash
python -c "from dependencies import PADDLE_AVAILABLE; from constants import JobStatus, OCR_DIR_NAME; from config_manager import ConfigManager; print(PADDLE_AVAILABLE, OCR_DIR_NAME, ConfigManager().paddleocr_model_root())"
```
Expected: `True OCR결과 ...official_models`

- [ ] **Step 5: 커밋** — `git commit -am "feat: PADDLE_AVAILABLE, job constants, model root"`

---

## Task 4: `paddle_ocr.py` — PaddleOCR 래퍼 (스모크)

**Files:** Create `paddle_ocr.py`, `tests/test_paddle_ocr.py`

- [ ] **Step 1: 구현** — `paddle_ocr.py`:
```python
"""PaddleOCR TableRecognitionPipelineV2 래퍼 (wired/server, mkldnn off, 오프라인)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from constants import PADDLE_MODELS
from logging_config import logger

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


@dataclass
class PageOCR:
    table_htmls: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)


class PaddleTableOCR:
    def __init__(self, model_root: Optional[Path] = None) -> None:
        self._model_root = model_root
        self._pipe = None

    def _kwargs(self) -> dict:
        kw = {
            "use_doc_orientation_classify": True,
            "use_doc_unwarping": False,
            "use_layout_detection": True,
            "enable_mkldnn": False,  # 필수
        }
        kw.update(PADDLE_MODELS)
        if self._model_root is not None:
            for nk, mn in PADDLE_MODELS.items():
                local = self._model_root / mn
                if local.is_dir():
                    kw[nk.replace("_model_name", "_model_dir")] = str(local)
        return kw

    def _ensure(self):
        if self._pipe is None:
            from paddleocr import TableRecognitionPipelineV2
            self._pipe = TableRecognitionPipelineV2(**self._kwargs())
            logger.info("PADDLE: pipeline ready (wired/server, mkldnn off)")
        return self._pipe

    def recognize(self, image_path: str) -> PageOCR:
        page = PageOCR()
        for res in self._ensure().predict(str(image_path)):
            for t in (res.get("table_res_list") or []):
                html = t.get("pred_html")
                if html:
                    page.table_htmls.append(html)
            ocr = res.get("overall_ocr_res")
            if ocr:
                page.text_blocks.extend([s for s in (ocr.get("rec_texts") or []) if s and s.strip()])
        return page
```

- [ ] **Step 2: 스모크 테스트** — `tests/test_paddle_ocr.py`:
```python
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
```

- [ ] **Step 3: 실행** — `python -m pytest tests/test_paddle_ocr.py -v` → PASS.
- [ ] **Step 4: 커밋** — `git add paddle_ocr.py tests/test_paddle_ocr.py && git commit -m "feat: PaddleOCR wrapper (offline wired/server)"`

---

## Task 5: `ocr_store.py` — 페이지별 OCR 결과 영속화 (TDD)

원본 옆 `OCR결과/<doc>.ocr.json`(+`<doc>_pages/page_N.png`) 직렬화/역직렬화. 순수+FS → TDD.

**Files:** Create `ocr_store.py`, `tests/test_ocr_store.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_ocr_store.py`:
```python
from ocr_store import PageResult, OcrResult, save_ocr_result, load_ocr_result


def test_roundtrip(tmp_path):
    pages = [
        PageResult(index=0, kind="ocr", table_htmls=["<table><tr><td>A</td></tr></table>"],
                   text_blocks=["hello"], image="p1.png"),
        PageResult(index=1, kind="text", table_htmls=[], text_blocks=["body"], image=None),
    ]
    res = OcrResult(source=r"C:\docs\x.pdf", pages=pages)
    path = save_ocr_result(tmp_path, "x", res)
    assert path.exists()
    loaded = load_ocr_result(path)
    assert loaded.source == res.source
    assert len(loaded.pages) == 2
    assert loaded.pages[0].table_htmls[0].startswith("<table")
    assert loaded.pages[1].kind == "text"
```

- [ ] **Step 2: 실패 확인** — FAIL(ModuleNotFound).

- [ ] **Step 3: 구현** — `ocr_store.py`:
```python
"""페이지별 OCR 결과 ↔ OCR결과/<doc>.ocr.json (순수+FS)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class PageResult:
    index: int
    kind: str                      # "ocr" | "text"
    table_htmls: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)
    image: str | None = None       # 페이지 이미지 파일명(상대)


@dataclass
class OcrResult:
    source: str
    pages: list[PageResult] = field(default_factory=list)


def save_ocr_result(out_dir: Path, doc_stem: str, result: OcrResult) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc_stem}.ocr.json"
    payload = {"source": result.source, "pages": [asdict(p) for p in result.pages]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 원자적 교체
    return path


def load_ocr_result(path: Path) -> OcrResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pages = [PageResult(**p) for p in data.get("pages", [])]
    return OcrResult(source=data.get("source", ""), pages=pages)
```

- [ ] **Step 4: 통과** — PASS. **Step 5: 커밋** — `git add ocr_store.py tests/test_ocr_store.py && git commit -m "feat: persist per-page OCR result as local json"`

---

## Task 6: `ocr_document.py` — 파일 → 페이지별 OCR

PDF/이미지를 페이지로 렌더, 텍스트레이어 충분하면 그대로, 부족하면 PaddleOCR. 페이지 콜백으로 스트리밍 지원.

**Files:** Create `ocr_document.py`

- [ ] **Step 1: 구현** — `ocr_document.py`:
```python
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
```

- [ ] **Step 2: import 확인** — `python -c "import ocr_document; print('ok')"` → `ok`
- [ ] **Step 3: 커밋** — `git add ocr_document.py && git commit -m "feat: document -> per-page OCR with streaming callback"`

---

## Task 7: `page_pipeline.py` — OCR∥번역 순서보존 (TDD)

**Files:** Create `page_pipeline.py`, `tests/test_page_pipeline.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_page_pipeline.py`:
```python
import time
from page_pipeline import run_page_pipeline


def test_overlap_and_order():
    calls = []
    def produce(i):
        time.sleep(0.05); calls.append(("ocr", i)); return f"p{i}"
    def consume(i, data):
        time.sleep(0.05); calls.append(("llm", i)); return data.upper()
    out = run_page_pipeline(3, produce, consume)
    assert out == ["P0", "P1", "P2"]
    assert calls.index(("ocr", 1)) < calls.index(("llm", 0))  # 겹침
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `page_pipeline.py`:
```python
"""페이지 OCR(생산자) ∥ 번역(소비자) 2단계, 출력 순서 보존."""
from __future__ import annotations

import queue
import threading
from typing import Callable

_SENTINEL = object()


def run_page_pipeline(n_pages, produce: Callable[[int], object],
                      consume: Callable[[int, object], object], max_prefetch: int = 2) -> list:
    q: "queue.Queue" = queue.Queue(maxsize=max_prefetch)
    err: list[BaseException] = []

    def producer():
        try:
            for i in range(n_pages):
                q.put((i, produce(i)))
        except BaseException as e:  # noqa: BLE001
            err.append(e)
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=producer, daemon=True); t.start()
    results = [None] * n_pages
    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        i, data = item
        results[i] = consume(i, data)
    t.join()
    if err:
        raise err[0]
    return results
```

- [ ] **Step 4: 통과** — PASS. **Step 5: 커밋** — `git add page_pipeline.py tests/test_page_pipeline.py && git commit -m "feat: order-preserving OCR||LLM page pipeline"`

---

## Task 8: `file_translator.py` — OCR/번역 분리 + 표 보존 렌더

기존 일체형 `_translate_image`/`_ocr_pdf_page*`/`_safe_ocr` 제거. 번역 측은 **페이지 단위 렌더 함수**만 제공(워커가 호출).

**Files:** Modify `file_translator.py`

- [ ] **Step 1: import 정리** — `from dependencies import (...)` 에서 `pytesseract,` 제거. 추가:
```python
from table_grid import parse_table_html, build_docx_table
```

- [ ] **Step 2: 표/본문 페이지 렌더 + 셀 번역 캐시 추가** — `FileTranslator` 에 메서드 추가:
```python
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
```

- [ ] **Step 3: 구식 OCR 메서드 제거** — `_translate_image`(494~536), `_ocr_pdf_page`(312~), `_ocr_pdf_page_from_bytes`(339~), `_safe_ocr`(360~) 삭제. `translate_file` 의 이미지/PDF 분기는 JobManager 가 대신 호출하므로, 직접 호출 경로는 `_translate_docx/_txt/_xlsx/_pptx` 만 유지(이들은 OCR 불필요). 이미지/PDF 는 JobManager 경로로만 처리.
> 주의: `translate_file` 에서 `.pdf`/이미지 핸들러를 제거하고 "JobManager 를 사용하라"는 RuntimeError 를 던지거나, 하위호환을 위해 `ocr_document`+`render_page_to_doc` 로 동기 처리하는 얇은 래퍼를 둔다(택1; 본 계획은 JobManager 경로 사용).

- [ ] **Step 4: import 확인** — `python -c "import file_translator; print('ok')"` → `ok`
- [ ] **Step 5: 커밋** — `git commit -am "refactor: split OCR from translation; table-preserving page render"`

---

## Task 9: `job_store.py` — 중앙 색인 (TDD)

**Files:** Create `job_store.py`, `tests/test_job_store.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_job_store.py`:
```python
from job_store import Job, JobStore
from constants import JobStatus, MODE_FULL


def test_add_update_persist(tmp_path):
    idx = tmp_path / "jobs.json"
    s = JobStore(idx)
    j = s.add(Job(id="j1", source=r"C:\x.pdf", mode=MODE_FULL, status=JobStatus.QUEUED))
    assert s.get("j1").status == JobStatus.QUEUED
    s.update("j1", status=JobStatus.OCR_DONE, ocr_json=r"C:\OCR결과\x.ocr.json")
    # 새 인스턴스로 재로드 → 영속 확인
    s2 = JobStore(idx)
    assert s2.get("j1").status == JobStatus.OCR_DONE
    assert s2.get("j1").ocr_json.endswith("x.ocr.json")


def test_recover_resets_running(tmp_path):
    idx = tmp_path / "jobs.json"
    s = JobStore(idx)
    s.add(Job(id="a", source="a", mode=MODE_FULL, status=JobStatus.OCR_RUNNING))
    s.add(Job(id="b", source="b", mode=MODE_FULL, status=JobStatus.TRANSLATING))
    s.recover()
    assert s.get("a").status == JobStatus.QUEUED
    assert s.get("b").status == JobStatus.OCR_DONE
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `job_store.py`:
```python
"""작업 중앙 색인(jobs.json) — 재시작 목록 복원용 가벼운 포인터 저장소."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from constants import JobStatus


@dataclass
class Job:
    id: str
    source: str
    mode: str
    status: str
    ocr_json: Optional[str] = None      # OCR결과/<doc>.ocr.json
    result_docx: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""


class JobStore:
    def __init__(self, index_path: Path) -> None:
        self._path = Path(index_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for d in data.get("jobs", []):
                self._jobs[d["id"]] = Job(**d)

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        payload = {"jobs": [asdict(j) for j in self._jobs.values()]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._save()
            return job

    def update(self, job_id: str, **fields) -> Job:
        with self._lock:
            j = self._jobs[job_id]
            for k, v in fields.items():
                setattr(j, k, v)
            self._save()
            return j

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._save()

    def recover(self) -> None:
        """재시작 복구: 진행 중이던 상태를 안전 지점으로 되돌린다."""
        with self._lock:
            for j in self._jobs.values():
                if j.status == JobStatus.OCR_RUNNING:
                    j.status = JobStatus.QUEUED
                elif j.status in (JobStatus.TRANSLATING, JobStatus.TRANS_QUEUED):
                    j.status = JobStatus.OCR_DONE
            self._save()
```

- [ ] **Step 4: 통과** — PASS. **Step 5: 커밋** — `git add job_store.py tests/test_job_store.py && git commit -m "feat: central job index with restart recovery"`

---

## Task 10: `job_manager.py` — OCR/번역 큐 워커 + 상태머신

**Files:** Create `job_manager.py`, `tests/test_job_manager.py`

- [ ] **Step 1: 페이크 기반 통합 테스트(모델 불필요)** — `tests/test_job_manager.py`:
```python
import time, uuid
from job_store import JobStore
from job_manager import JobManager
from constants import JobStatus, MODE_OCR_ONLY, MODE_FULL


class FakeOCR:
    def recognize(self, image_path):
        from paddle_ocr import PageOCR
        return PageOCR(table_htmls=["<table><tr><td>A</td></tr></table>"], text_blocks=["t"])


class FakeTranslator:
    def translate(self, text):
        return "T:" + text


def _mgr(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    # 이미지 1장짜리 더미 입력
    from PIL import Image
    p = tmp_path / "doc.png"; Image.new("RGB", (40, 40), "white").save(str(p))
    return store, JobManager(store, translator=FakeTranslator(), ocr_engine=FakeOCR()), str(p)


def test_ocr_only_then_translate(tmp_path):
    store, mgr, path = _mgr(tmp_path)
    mgr.start()
    jid = mgr.submit(path, mode=MODE_OCR_ONLY)
    _wait(lambda: store.get(jid).status == JobStatus.OCR_DONE)
    assert store.get(jid).ocr_json  # 결과 파일 경로 기록됨
    mgr.request_translation(jid)
    _wait(lambda: store.get(jid).status == JobStatus.DONE)
    assert store.get(jid).result_docx
    mgr.stop()


def test_full_mode_reaches_done(tmp_path):
    store, mgr, path = _mgr(tmp_path)
    mgr.start()
    jid = mgr.submit(path, mode=MODE_FULL)
    _wait(lambda: store.get(jid).status == JobStatus.DONE)
    mgr.stop()


def _wait(cond, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `job_manager.py`:
```python
"""OCR 큐·번역 큐 2워커 + 상태머신.

- OCR 워커(1): OCR 큐 소비. 페이지별 OCR → OCR결과/<doc>.ocr.json 저장.
  full 모드는 page_pipeline 로 페이지 OCR∥번역을 겹쳐 docx 직접 생성.
- 번역 워커(1): ocr_only 후 요청된 작업을 OCR결과 로드 → 번역 → docx.
- 두 워커가 동시에 돌아 파일 A 번역 중 파일 B OCR 진행(큐 레벨 겹침)."""
from __future__ import annotations

import queue
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from constants import JobStatus, MODE_FULL, MODE_OCR_ONLY, OCR_DIR_NAME, INPUT_DIR_NAME, RESULT_DIR_NAME
from docx import Document
from file_translator import FileTranslator
from job_store import Job, JobStore
from ocr_document import ocr_document
from ocr_store import save_ocr_result, load_ocr_result
from page_pipeline import run_page_pipeline


def _ocr_dir(source: str) -> Path:
    src = Path(source)
    base = src.parent.parent if src.parent.name == INPUT_DIR_NAME else src.parent
    d = base / OCR_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _result_docx_path(source: str) -> Path:
    src = Path(source)
    base = src.parent.parent if src.parent.name == INPUT_DIR_NAME else src.parent
    d = base / RESULT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{src.stem}_translated.docx"


class JobManager:
    def __init__(self, store: JobStore, translator, ocr_engine,
                 on_change: Optional[Callable[[Job], None]] = None) -> None:
        self.store = store
        self.translator = translator
        self.ocr_engine = ocr_engine
        self.on_change = on_change
        self.ft = FileTranslator(translator)
        self._ocr_q: "queue.Queue[str]" = queue.Queue()
        self._trans_q: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.store.recover()
        for j in self.store.list():  # 복구된 큐 재투입
            if j.status == JobStatus.QUEUED:
                self._ocr_q.put(j.id)
            elif j.status == JobStatus.OCR_DONE and j.mode == MODE_FULL:
                self._trans_q.put(j.id)

    # ---- 공개 API ----
    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._ocr_worker, daemon=True),
            threading.Thread(target=self._trans_worker, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._ocr_q.put(None); self._trans_q.put(None)

    def submit(self, source: str, mode: str = MODE_FULL) -> str:
        jid = uuid.uuid4().hex[:12]
        self.store.add(Job(id=jid, source=source, mode=mode, status=JobStatus.QUEUED))
        self._notify(jid)
        self._ocr_q.put(jid)
        return jid

    def request_translation(self, job_id: str) -> None:
        j = self.store.get(job_id)
        if j and j.status == JobStatus.OCR_DONE:
            self.store.update(job_id, status=JobStatus.TRANS_QUEUED)
            self._notify(job_id)
            self._trans_q.put(job_id)

    # ---- 내부 ----
    def _notify(self, job_id: str) -> None:
        if self.on_change:
            j = self.store.get(job_id)
            if j:
                self.on_change(j)

    def _ocr_worker(self) -> None:
        while not self._stop.is_set():
            jid = self._ocr_q.get()
            if jid is None:
                break
            j = self.store.get(jid)
            if not j or j.status != JobStatus.QUEUED:
                continue
            try:
                self.store.update(jid, status=JobStatus.OCR_RUNNING); self._notify(jid)
                src = j.source
                stem = Path(src).stem
                pages_dir = _ocr_dir(src) / f"{stem}_pages"

                if j.mode == MODE_FULL:
                    # 페이지 스트리밍: produce=OCR 페이지, consume=번역 페이지 → docx
                    result_pages = []
                    doc = Document()
                    cell_cache: dict = {}
                    gen = []  # 페이지 결과를 순서대로 수집(이미지/텍스트 판정 포함)

                    # 1) 페이지 산출(생산자)과 번역(소비자)을 겹친다.
                    produced = ocr_document(src, self.ocr_engine, pages_dir,
                                            pdf_text_extractor=_pdf_text, on_page=result_pages.append)
                    #   ocr_document 는 동기지만 page 콜백으로 즉시 수집되므로,
                    #   대규모 PDF 에서 페이지 겹침을 원하면 run_page_pipeline 로 감싼다(아래).
                    for pr in produced.pages:
                        self.ft.render_page_to_doc(doc, pr, cell_cache)
                    # OCR 결과 영속화(이미지까지 보관됨)
                    ocr_json = save_ocr_result(_ocr_dir(src), stem, produced)
                    out = _result_docx_path(src); doc.save(str(out))
                    self.store.update(jid, status=JobStatus.DONE,
                                      ocr_json=str(ocr_json), result_docx=str(out))
                    self._notify(jid)
                else:  # OCR_ONLY
                    produced = ocr_document(src, self.ocr_engine, pages_dir,
                                            pdf_text_extractor=_pdf_text)
                    ocr_json = save_ocr_result(_ocr_dir(src), stem, produced)
                    self.store.update(jid, status=JobStatus.OCR_DONE, ocr_json=str(ocr_json))
                    self._notify(jid)
            except Exception as e:  # noqa: BLE001
                self.store.update(jid, status=JobStatus.FAILED, error=f"{type(e).__name__}")
                self._notify(jid)

    def _trans_worker(self) -> None:
        while not self._stop.is_set():
            jid = self._trans_q.get()
            if jid is None:
                break
            j = self.store.get(jid)
            if not j or j.status not in (JobStatus.TRANS_QUEUED,):
                continue
            try:
                self.store.update(jid, status=JobStatus.TRANSLATING); self._notify(jid)
                result = load_ocr_result(Path(j.ocr_json))
                doc = Document(); cell_cache: dict = {}
                for pr in result.pages:
                    self.ft.render_page_to_doc(doc, pr, cell_cache)
                out = _result_docx_path(j.source); doc.save(str(out))
                self.store.update(jid, status=JobStatus.DONE, result_docx=str(out))
                self._notify(jid)
            except Exception as e:  # noqa: BLE001
                self.store.update(jid, status=JobStatus.FAILED, error=f"{type(e).__name__}")
                self._notify(jid)


def _pdf_text(filepath: str):
    """PDF 텍스트레이어 추출(없으면 None). PyMuPDF 사용."""
    try:
        import fitz
        doc = fitz.open(filepath)
        try:
            return [doc[i].get_text() or "" for i in range(len(doc))]
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return None
```
> 비고: 위 full 모드는 페이지 결과를 모은 뒤 렌더한다. **페이지 OCR∥번역을 진짜로 겹치려면** `produced.pages` 대신 `run_page_pipeline(n, produce=ocr_page_i, consume=translate_page_i)` 로 감싸 OCR 워커 내부에서 번역을 소비하게 한다(번역 워커는 ocr_only 전용으로 유지). 1차 구현은 단순화(겹침은 큐 레벨에서 이미 확보), 페이지 레벨 겹침은 후속 Step 으로 분리한다.

- [ ] **Step 4: 실행** — `python -m pytest tests/test_job_manager.py -v` → PASS (2 passed).
- [ ] **Step 5: 커밋** — `git add job_manager.py tests/test_job_manager.py && git commit -m "feat: OCR/translation queue workers with state machine + persistence"`

---

## Task 11: full 모드 페이지 레벨 OCR∥번역 겹침 (TDD)

Task 10 의 full 경로를 `page_pipeline` 으로 감싸 **page i 번역 중 page i+1 OCR** 가 진행되게 한다.

**Files:** Modify `job_manager.py`, `tests/test_job_manager.py`

- [ ] **Step 1: 겹침 검증 테스트 추가** — 페이크 OCR/번역에 sleep+타임스탬프를 넣어, page1 OCR 이 page0 번역보다 먼저 일어남을 검증(구조는 Task 7 테스트와 동일 패턴). (구체 코드는 Task 7 테스트를 PageResult 흐름에 맞게 복제)

- [ ] **Step 2: full 경로 교체** — `_ocr_worker` 의 MODE_FULL 분기를 아래로:
```python
                if j.mode == MODE_FULL:
                    doc = Document(); cell_cache: dict = {}
                    pages_meta: list = []
                    # 생산자: 페이지 i 를 OCR(또는 텍스트레이어) 하여 PageResult 반환
                    produced = ocr_document(src, self.ocr_engine, pages_dir,
                                            pdf_text_extractor=_pdf_text,
                                            on_page=pages_meta.append)
                    # produced.pages 를 생산 즉시 소비하도록 파이프라인 처리
                    def produce(i): return produced.pages[i]
                    def consume(i, pr):
                        self.ft.render_page_to_doc(doc, pr, cell_cache); return True
                    run_page_pipeline(len(produced.pages), produce, consume)
                    ocr_json = save_ocr_result(_ocr_dir(src), stem, produced)
                    out = _result_docx_path(src); doc.save(str(out))
                    self.store.update(jid, status=JobStatus.DONE,
                                      ocr_json=str(ocr_json), result_docx=str(out))
                    self._notify(jid)
```
> 참고: `ocr_document` 가 동기 완료된 뒤 파이프라인을 도는 현 형태는 OCR 전체→번역이 된다. **진정한 페이지 겹침**은 `ocr_document` 를 제너레이터화(`yield PageResult`)하여 `produce(i)` 가 i번째 페이지를 그 시점에 OCR 하도록 바꾼다 — 이 Step 에서 `ocr_document` 에 `iter_pages()` 제너레이터를 추가하고 `produce` 가 그것을 당겨 쓰게 한다.

- [ ] **Step 3: `ocr_document.iter_pages()` 제너레이터 추가** — `ocr_document.py` 에 페이지를 하나씩 `yield` 하는 함수 추가(기존 `ocr_document` 는 이를 `list()` 로 감싼 형태로 리팩터). `produce(i)` 는 제너레이터의 다음 페이지를 받아 반환.

- [ ] **Step 4: 통과 + 커밋** — PASS 후 `git commit -am "feat: true page-level OCR||LLM overlap in full mode"`

---

## Task 12: `app_ui.py` — 작업 목록 패널 + JobManager 연동

**Files:** Modify `app_ui.py`

- [ ] **Step 1: JobManager 생성** — `TranslatorApp.__init__` 에서 번역엔진 생성 직후:
```python
        from job_store import JobStore
        from job_manager import JobManager
        from paddle_ocr import PaddleTableOCR
        from constants import JOBS_INDEX_PATH
        self._job_store = JobStore(Path(JOBS_INDEX_PATH).expanduser())
        self._ocr_engine = PaddleTableOCR(model_root=self.config.paddleocr_model_root())
        self.jobs = JobManager(self._job_store, self.translator, self._ocr_engine,
                               on_change=self._on_job_change)
        self.jobs.start()
```

- [ ] **Step 2: 패널 위젯 + 갱신** — `_build_ui` 에 작업 목록 영역(Treeview: 파일/상태/액션) 추가. `on_change` 콜백은 UI 스레드로 마샬링:
```python
    def _on_job_change(self, job) -> None:
        # 워커 스레드 → tkinter 메인 스레드로 안전 전달
        self.root.after(0, lambda: self._refresh_job_row(job))

    def _refresh_job_row(self, job) -> None:
        # Treeview 항목 갱신: 상태 표시, OCR_DONE 이면 '번역' 버튼 활성
        ...  # 기존 file_rows 패턴과 동일하게 행 위젯 구성
```
> 기존 파일 목록 위젯(`self.file_rows`, `_refresh_file_list`) 패턴을 그대로 따라 작업 목록 행을 구성한다. OCR_DONE 행에는 "번역 시작" 버튼 → `self.jobs.request_translation(job.id)`.

- [ ] **Step 3: 추가 버튼에 모드 선택** — 파일 추가 시 모드(OCR+번역 / OCR만) 선택 UI(라디오/토글) → `self.jobs.submit(path, mode)`.

- [ ] **Step 4: 시작 시 목록 복원** — `__init__` 끝에서 `for j in self._job_store.list(): self._refresh_job_row(j)` 로 재시작 후 완료 목록 표시.

- [ ] **Step 5: 종료 처리** — 창 닫힘 핸들러에 `self.jobs.stop()` 추가.

- [ ] **Step 6: 수동 검증** — 앱 실행 → 파일 추가(OCR만) → 목록에 OCR_DONE 표시 → 앱 재시작 → **목록 유지 확인** → '번역 시작' → DONE.

- [ ] **Step 7: 커밋** — `git commit -am "feat: job list panel wired to JobManager with restart restore"`

---

## Task 13: 통합 검증 (실제 중국어 PDF)

- [ ] **Step 1: OCR→표복원 검증(LLM 없이)** — `Scanned Table.pdf` 로 `ocr_document`+`build_docx_table`(항등 번역) 실행해 `verify_table.docx` 생성 → **병합표 구조 육안 확인**.
- [ ] **Step 2: 재시작 영속 검증** — OCR_ONLY 작업 생성 → `OCR결과/<doc>.ocr.json`+이미지 생성 확인 → 앱/프로세스 재시작 → 목록 복원 확인 → 번역 → `번역결과/...docx` 생성.

---

## Task 14: 정리 + 모델 번들

**Files:** Modify `app_ui.py`/`config_manager.py`/`settings_dialog.py`(tesseract 호출 제거), Create `prepare_paddleocr.py`, Modify `build_exe.py`, Delete `prepare_tesseract.py`(선택)

- [ ] **Step 1: `apply_tesseract_path` 호출 3곳 제거** (`app_ui.py:140`, `config_manager.py:55`, `settings_dialog.py:431`) + 설정창 Tesseract 경로 UI 제거.

- [ ] **Step 2: `prepare_paddleocr.py`** (wired 전용 모델만 수집):
```python
"""vendor/paddleocr-models/ 구성: ~/.paddlex/official_models 에서 확정 모델만 복사."""
from __future__ import annotations
import shutil
from pathlib import Path
from constants import PADDLE_MODELS, PADDLE_VENDOR_DIRNAME

SRC = Path.home() / ".paddlex" / "official_models"
DEST = Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for name in sorted(set(PADDLE_MODELS.values())):
        src = SRC / name
        if src.is_dir():
            shutil.copytree(src, DEST / name, dirs_exist_ok=True); copied.append(name)
        else:
            missing.append(name)
    total = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    print(f"[완료] {len(copied)}개 모델 → {DEST} ({total/1024/1024:.1f} MB)")
    if missing:
        print(f"  [경고] 누락(먼저 1회 구동해 캐시): {', '.join(missing)}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
```
Run: `python prepare_paddleocr.py` → 약 800MB(wired 전용).

- [ ] **Step 3: `build_exe.py` 번들 추가** — PyInstaller 옵션에:
```python
    paddle_models = root / "vendor" / "paddleocr-models"
    if paddle_models.is_dir():
        add_data.append((str(paddle_models), "paddleocr-models"))
    collect_all += ["paddleocr", "paddlex", "paddle"]
    hidden_imports += ["paddle", "paddleocr", "paddlex", "shapely", "pyclipper", "scipy", "sklearn"]
```

- [ ] **Step 4: 커밋** — `git add -A && git commit -m "chore: bundle PaddleOCR models, remove Tesseract wiring"`

---

## Self-Review (작성자 점검)

- **Spec 커버리지**: 표 보존(T1,2,8), 완전 교체(T3,4,8,14), 오프라인 번들(T3,4,14), OCR/번역 분리(T6,8), 영속 OCR 파일(T5,6), 중앙 색인·재시작 복구(T9,12,13), 2큐 워커·상태머신(T10), 모드1 페이지 겹침(T7,11), 모드2 후속 번역(T10), 번역도 큐(T10), 로컬 OCR결과 저장(T5,10), UI 패널(T12) — 매핑됨.
- **타입 일관성**: `PageOCR`(T4)→`PageResult`/`OcrResult`(T5)→`ocr_document`(T6)→`render_page_to_doc`(T8)→`JobManager`(T10) 흐름의 필드·시그니처 일치. `Job`/`JobStore`/`JobStatus`(T3,9) 일관. `run_page_pipeline`(T7) 재사용(T11).
- **알려진 한계(명시)**: (1) Task 10 의 full 경로는 1차에선 OCR 전체→번역 형태이며 **진정한 페이지 겹침은 Task 11**에서 `ocr_document.iter_pages()` 제너레이터화로 완성. (2) 본문/표 영역 정밀 분리 미구현(표 지배 문서 기준). (3) CPU 추론 절대시간(server 66초/페이지)은 별도 과제 — 큐/겹침으로 체감 완화. (4) 서식(bold/폰트) 미보존 — OCR 비제공(역할기반 서식은 향후 PP-StructureV3 옵션). (5) PyInstaller frozen 오프라인 구동은 빌드 후 실기 검증 필요.

## 잔여 리스크
- 워커 스레드 ↔ tkinter UI 갱신은 반드시 `root.after` 로 마샬링(직접 위젯 조작 금지).
- 동일 원본 재제출 시 작업 중복 — 1차는 허용(목록에 별 작업으로). dedup(경로+mtime 키)은 후속.
- 셀 번역 캐시는 호출 수를 줄이나 대형 표는 LLM 호출 다수 — 배치 번역은 후속 최적화.
