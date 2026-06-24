# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 사양 (LLM Translator, Tesseract 오프라인 번들).

build_exe.py 가 이 spec 을 호출한다.
산출물: dist/LLMTranslator/LLM_Translator.exe (onedir, windowed)
  - vendor/Tesseract-OCR/ 전체(tesseract.exe + DLL + tessdata)를 함께 번들 →
    오프라인 환경에서 인터넷 없이 이미지/PDF OCR 동작
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH)

# ------------------------------------------------------------------
# 데이터 번들
# ------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = [
    # PyInstaller 정적 탐지에서 누락되기 쉬운 모듈들
    "pypdf.filters",
    "pypdf._crypt_providers",
    "pytesseract",
    "PIL", "PIL.Image",
    "fitz",
    "pptx",
    "openpyxl",
    "docx",
]

# Tesseract OCR 엔진 (vendor/Tesseract-OCR → 번들 루트의 Tesseract-OCR/).
# PyInstaller 6.x onedir 에서는 _internal/Tesseract-OCR 로 배치되며,
# config_manager.apply_tesseract_path() 가 sys._MEIPASS 기준으로 탐지한다.
_tess = ROOT / "vendor" / "Tesseract-OCR"
if _tess.is_dir():
    datas.append((str(_tess), "Tesseract-OCR"))
else:
    print("[spec][경고] vendor/Tesseract-OCR 가 없습니다 — OCR 없이 번들됩니다. "
          "먼저 `python prepare_tesseract.py` 를 실행하세요.")

# 드래그앤드롭(tkdnd 네이티브 바이너리 포함) — 선택 의존성
try:
    _dnd_datas, _dnd_binaries, _dnd_hidden = collect_all("tkinterdnd2")
    datas += _dnd_datas
    binaries += _dnd_binaries
    hiddenimports += _dnd_hidden
except Exception as exc:  # noqa: BLE001
    print(f"[spec] tkinterdnd2 수집 생략: {exc}")

# certifi CA 번들 (runtime_setup 가 SSL_CERT_FILE 로 사용)
try:
    datas += collect_data_files("certifi")
except Exception as exc:  # noqa: BLE001
    print(f"[spec] certifi 데이터 수집 생략: {exc}")


a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 보안검토: 사용하지 않는 무거운/외부 OCR 스택 제외 (혼입 방지)
        "paddle", "paddleocr", "paddlex",
        "torch", "tensorflow",
        # 앱이 직접 import 하지 않는데 전이 의존성으로 끌려오는 대형 과학 스택 —
        # 배포본 용량 절감을 위해 제외 (OCR/번역/문서처리에 불필요)
        "matplotlib", "scipy", "pandas", "sklearn", "scikit-learn", "pyarrow",
        "IPython", "notebook", "PyQt5", "PySide2", "PySide6", "PyQt6",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LLM_Translator",  # 산출 exe 파일명
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI(windowed). stdio 는 runtime_setup 가 보정
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LLMTranslator",
)
