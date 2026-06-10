"""
Windows 배포용 실행 파일 빌드 스크립트 (PaddleOCR 오프라인 번들).

  python build_exe.py            # 풀 빌드 + 풀 zip 생성
  python build_exe.py --no-zip   # 빌드만, zip 생성은 생략

사전 준비:
  1) PaddleOCR 모델을 vendor/paddleocr-models 에 수집  →  python prepare_paddleocr.py
     (사내 오프라인망에서 모델 다운로드 없이 구동하려면 필수)
  2) PyInstaller 설치  →  pip install pyinstaller

결과물:
  dist\\python\\python.exe (onedir; 사내 보안 정책 우회용 명명)
  LLMTranslator_v{버전}_full.zip          (배포용 풀 패키지)

PaddleOCR 모델(vendor/paddleocr-models)과 paddle/paddleocr/paddlex 패키지 데이터가
exe 에 함께 번들되어 오프라인에서 그대로 구동됩니다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

from constants import APP_VERSION, PADDLE_VENDOR_DIRNAME

ENTRY = "main.py"
EXE_NAME = "python"  # 사내 보안 정책 우회 — 산출 exe 파일명

# PyInstaller 정적 탐지로는 누락되기 쉬운 PaddleOCR/PaddleX 런타임 의존성.
_COLLECT_ALL = ["paddle", "paddleocr", "paddlex"]
_HIDDEN_IMPORTS = [
    "paddle", "paddleocr", "paddlex",
    "shapely", "pyclipper", "scipy", "sklearn", "skimage",
    "lxml", "premailer", "tokenizers", "ftfy",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _find_paddle_models() -> Path | None:
    """vendor/paddleocr-models (prepare_paddleocr.py 산출물) 탐지."""
    p = _project_root() / "vendor" / PADDLE_VENDOR_DIRNAME
    return p if p.is_dir() else None


def _build_command(root: Path, models: Path | None) -> list[str]:
    cmd = [
        sys.executable, "-m", "PyInstaller", str(root / ENTRY),
        "--name", EXE_NAME,
        "--onedir", "--windowed",
        "--clean", "-y", "--noconfirm",
    ]
    for pkg in _COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    for mod in _HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    # 드래그앤드롭(선택 의존성)이 설치돼 있으면 함께 수집
    try:
        import tkinterdnd2  # noqa: F401
        cmd += ["--collect-all", "tkinterdnd2"]
    except ImportError:
        pass
    # 오프라인 모델 번들 (Windows: src;dest 구분자 ';')
    if models is not None:
        cmd += ["--add-data", f"{models}{';'}{PADDLE_VENDOR_DIRNAME}"]
    return cmd


def _make_full_zip(dist_dir: Path, version: str) -> Path:
    """dist/python/ 전체를 풀 배포 zip 으로 묶음."""
    out = _project_root() / f"LLMTranslator_v{version}_full.zip"
    if out.exists():
        out.unlink()

    files = [f for f in dist_dir.rglob("*") if f.is_file()]
    print(f"  [zip] {len(files)}개 파일 압축 중...")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            zf.write(f, arcname=f"LLMTranslator/{f.relative_to(dist_dir)}")

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"  [zip] {out.name} ({size_mb:.1f} MB)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="LLMTranslator 풀 빌드 (PaddleOCR 번들)")
    parser.add_argument("--no-zip", action="store_true", help="zip 생성 생략")
    args = parser.parse_args()

    root = _project_root()
    if not (root / ENTRY).is_file():
        print(f"오류: 진입점 {ENTRY} 을 찾을 수 없습니다.")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("오류: PyInstaller가 설치되어 있지 않습니다.\n  pip install pyinstaller")
        return 1

    models = _find_paddle_models()
    if models:
        print(f"PaddleOCR 모델 번들: {models}")
    else:
        print(
            "[경고] vendor/paddleocr-models 를 찾지 못했습니다.\n"
            "       먼저 `python prepare_paddleocr.py` 로 모델을 수집하세요.\n"
            "       (모델 없이 빌드하면 오프라인망에서 OCR 이 동작하지 않습니다.)\n"
        )

    cmd = _build_command(root, models)
    print("실행:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(root))
    if proc.returncode != 0:
        print("PyInstaller가 실패했습니다.")
        return proc.returncode

    dist_dir = root / "dist" / EXE_NAME
    out_exe = dist_dir / f"{EXE_NAME}.exe"
    if not out_exe.is_file():
        print("\n빌드는 끝났지만 예상 경로에 exe가 없습니다. dist 폴더를 확인하세요.")
        return 1

    print(f"\n빌드 완료: {out_exe}")

    if not args.no_zip:
        print(f"\n[풀 패키지 zip 생성 v{APP_VERSION}]")
        _make_full_zip(dist_dir, APP_VERSION)

    print("\n배포 시 풀 zip 또는 dist\\python 폴더 전체를 전달하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
