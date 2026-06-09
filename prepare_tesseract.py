"""
vendor\\Tesseract-OCR\\ 폴더 자동 구성.

- 바이너리/DLL : C:\\Program Files\\Tesseract-OCR\\ (UB-Mannheim 설치본)
- 언어팩      : C:\\PI\\tesseract\\tessdata\\ (소스 저장소의 풍부한 팩)
                필요한 21개만 복사 (OCR_LANG_MAP + osd)

  python prepare_tesseract.py
  python prepare_tesseract.py --install C:\\path\\to\\Tesseract-OCR
                              --tessdata C:\\path\\to\\tessdata

이후 build_exe.py 가 vendor\\Tesseract-OCR\\ 를 자동 감지해 번들합니다.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from constants import OCR_LANG_MAP

DEFAULT_INSTALL = Path(r"C:\Program Files\Tesseract-OCR")
DEFAULT_RICH_TESSDATA = Path(r"C:\PI\tesseract\tessdata")
DEST = Path(__file__).resolve().parent / "vendor" / "Tesseract-OCR"

KEEP_TRAINED: set[str] = set(OCR_LANG_MAP.values()) | {"osd"}


def _copy_install_binaries(src_install: Path, dest: Path) -> int:
    """tessdata 제외하고 Program Files 의 모든 파일/폴더를 vendor 로 복사."""
    if not (src_install / "tesseract.exe").is_file():
        raise FileNotFoundError(
            f"{src_install}\\tesseract.exe 가 없습니다. 설치 경로 확인 필요."
        )

    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in src_install.iterdir():
        if item.name == "tessdata":
            continue  # tessdata 는 별도 처리
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        copied += 1
    return copied


def _build_minimal_tessdata(
    install_tessdata: Path, rich_tessdata: Path, dest_tessdata: Path
) -> tuple[list[str], list[str]]:
    """필요한 언어팩만 복사한 tessdata 폴더 구성."""
    dest_tessdata.mkdir(parents=True, exist_ok=True)

    # 보조 파일 (configs / pdf.ttf 등) — 설치본 tessdata 에서 가져옴
    if install_tessdata.is_dir():
        for item in install_tessdata.iterdir():
            if item.is_dir() and item.name in ("configs", "tessconfigs"):
                shutil.copytree(item, dest_tessdata / item.name, dirs_exist_ok=True)
            elif item.is_file() and item.suffix in (".ttf",):
                shutil.copy2(item, dest_tessdata / item.name)

    copied: list[str] = []
    missing: list[str] = []
    for stem in sorted(KEEP_TRAINED):
        # 1순위: 풍부한 tessdata, 2순위: 설치본 tessdata
        for src_dir in (rich_tessdata, install_tessdata):
            src = src_dir / f"{stem}.traineddata"
            if src.is_file():
                shutil.copy2(src, dest_tessdata / src.name)
                copied.append(stem)
                break
        else:
            missing.append(stem)

    return copied, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="vendor/Tesseract-OCR 자동 구성")
    parser.add_argument(
        "--install", type=str, default=str(DEFAULT_INSTALL),
        help=f"Tesseract 설치 경로 (기본: {DEFAULT_INSTALL})",
    )
    parser.add_argument(
        "--tessdata", type=str, default=str(DEFAULT_RICH_TESSDATA),
        help=f"풍부한 tessdata 경로 (기본: {DEFAULT_RICH_TESSDATA})",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="기존 vendor/Tesseract-OCR 삭제 후 새로 구성",
    )
    args = parser.parse_args()

    src_install = Path(args.install)
    rich_tessdata = Path(args.tessdata)

    if args.clean and DEST.exists():
        print(f"기존 {DEST} 제거")
        shutil.rmtree(DEST, ignore_errors=True)

    print(f"설치 경로: {src_install}")
    print(f"tessdata : {rich_tessdata}")
    print(f"대상     : {DEST}\n")

    print("[1/2] 바이너리/DLL 복사 중...")
    copied = _copy_install_binaries(src_install, DEST)
    print(f"      {copied}개 항목 복사")

    print("\n[2/2] 언어팩 정리 (필요한 21개만)...")
    install_tessdata = src_install / "tessdata"
    copied_langs, missing_langs = _build_minimal_tessdata(
        install_tessdata, rich_tessdata, DEST / "tessdata"
    )
    print(f"      복사된 언어팩 ({len(copied_langs)}): {', '.join(copied_langs)}")
    if missing_langs:
        print(f"      [경고] 못 찾은 언어팩 ({len(missing_langs)}): {', '.join(missing_langs)}")
        print(f"             {rich_tessdata} 또는 {install_tessdata} 에서 직접 추가 필요.")

    # 최종 크기 요약
    total_size = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    file_count = sum(1 for _ in DEST.rglob("*") if _.is_file())
    print(f"\n[완료] vendor/Tesseract-OCR 구성 완료")
    print(f"  파일 수: {file_count}")
    print(f"  크기   : {total_size/1024/1024:.1f} MB")
    print("\n다음 단계:")
    print("  python build_exe.py        # 풀 빌드 + zip")
    print("  python build_patch.py      # 패치 zip (풀 빌드 후)")
    return 0 if not missing_langs else 2


if __name__ == "__main__":
    raise SystemExit(main())
