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
