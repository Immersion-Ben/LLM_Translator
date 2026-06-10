"""PaddleOCR TableRecognitionPipelineV2 래퍼 (wired/server, mkldnn off, 오프라인)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from constants import PADDLE_MODELS, PADDLE_VENDOR_DIRNAME
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
