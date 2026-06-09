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
