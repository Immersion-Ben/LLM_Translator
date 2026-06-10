"""선택 의존성 래핑. 부재 시 None으로 설정하여 기능별 graceful degradation."""
from __future__ import annotations

import sys

from logging_config import logger

try:
    from docx import Document
    from docx.shared import Pt, RGBColor  # noqa: F401
except ImportError:
    print("❌ python-docx 필요: conda install -c conda-forge python-docx")
    sys.exit(1)

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# PyInstaller에서 누락되는 pypdf 서브모듈 강제 import (PyInstaller 정적 탐지를 위해
# 명시적 import 유지). 미탑재는 선택적 상황이므로 조용히 기록만 한다.
try:
    import pypdf.filters  # noqa: F401
except ImportError as e:
    logger.debug(f"DEP-OPT: pypdf.filters 미탑재 ({type(e).__name__})")
try:
    import pypdf._crypt_providers  # noqa: F401
except ImportError as e:
    logger.debug(f"DEP-OPT: pypdf._crypt_providers 미탑재 ({type(e).__name__})")

try:
    import fitz as pymupdf
except ImportError:
    pymupdf = None

try:
    from PIL import Image
except ImportError:
    Image = None

# OCR 엔진: PaddleOCR (Tesseract 완전 대체). 무거운 import 는 사용 시점까지 미룬다.
try:
    import importlib.util as _ilu
    PADDLE_AVAILABLE = _ilu.find_spec("paddle") is not None and _ilu.find_spec("paddleocr") is not None
except (ImportError, ValueError):
    PADDLE_AVAILABLE = False

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

# v3 신규: 드래그앤드롭 (선택 의존성)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False
