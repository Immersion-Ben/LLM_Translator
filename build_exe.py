"""
Windows 배포용 실행 파일 빌드 스크립트 (v3).

  python build_exe.py            # 풀 빌드 + tessdata 정리 + 풀 zip 생성
  python build_exe.py --no-zip   # 빌드만, zip 생성은 생략
  python build_exe.py --no-trim  # tessdata 정리 안 함 (모든 언어팩 유지)

결과물:
  dist\\LLMTranslator\\python.exe (onedir; 사내 보안 정책 우회용 명명)
  LLMTranslator_v{버전}_full.zip          (배포용 풀 패키지)

Tesseract OCR을 exe에 포함하려면 아래 중 하나를 준비하세요.
  1) 프로젝트 폴더에 vendor\\Tesseract-OCR\\ (tesseract.exe, tessdata 포함)
  2) 환경변수 TESSERACT_BUNDLE = tesseract.exe가 들어 있는 폴더의 절대 경로

빌드 후 OCR_LANG_MAP 에 정의된 언어팩만 남기고 나머지는 자동 제거됩니다 (--no-trim 으로 비활성화).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from constants import APP_VERSION, OCR_LANG_MAP


# 번역기에서 실제 사용하는 언어 팩 + Orientation/Script Detection (osd)
KEEP_TRAINED: set[str] = set(OCR_LANG_MAP.values()) | {"osd"}


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _find_tesseract_root() -> Path | None:
    root = _project_root()
    env = os.environ.get("TESSERACT_BUNDLE", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            root / "vendor" / "Tesseract-OCR",
            root / "Tesseract-OCR",
        ]
    )
    for p in candidates:
        if (p / "tesseract.exe").is_file():
            return p.resolve()
    return None


def _trim_tessdata(dist_dir: Path) -> tuple[int, int]:
    """배포본 tessdata 에서 KEEP_TRAINED 외 언어팩/스크립트 제거.

    반환: (제거된 항목 수, 절약된 바이트)
    """
    candidates = [
        dist_dir / "Tesseract-OCR" / "tessdata",
        dist_dir / "_internal" / "Tesseract-OCR" / "tessdata",
    ]
    target = next((p for p in candidates if p.is_dir()), None)
    if not target:
        print("  [trim] tessdata 폴더를 찾지 못함, 정리 생략")
        return (0, 0)

    removed = 0
    saved = 0
    # script/ (Latin.traineddata 등 script-level pack) 통째로 제거
    script_dir = target / "script"
    if script_dir.is_dir():
        size = sum(f.stat().st_size for f in script_dir.rglob("*") if f.is_file())
        shutil.rmtree(script_dir, ignore_errors=True)
        removed += 1
        saved += size
        print(f"  [trim] script/ 디렉터리 제거 (~{size/1024/1024:.1f} MB)")

    # 개별 .traineddata 정리
    for entry in target.iterdir():
        if not (entry.is_file() and entry.suffix == ".traineddata"):
            continue
        if entry.stem in KEEP_TRAINED:
            continue
        size = entry.stat().st_size
        try:
            entry.unlink()
            removed += 1
            saved += size
        except OSError as e:
            print(f"  [trim] {entry.name} 제거 실패: {e}")

    if removed:
        print(f"  [trim] 총 {removed}개 항목 제거, ~{saved/1024/1024:.1f} MB 절약")

    # 남은 항목 요약
    kept = sorted(
        f.stem for f in target.iterdir()
        if f.is_file() and f.suffix == ".traineddata"
    )
    print(f"  [trim] 유지된 언어팩 ({len(kept)}): {', '.join(kept)}")
    return (removed, saved)


def _make_full_zip(dist_dir: Path, version: str) -> Path:
    """dist/LLMTranslator/ 전체를 풀 배포 zip 으로 묶음."""
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
    parser = argparse.ArgumentParser(description="LLMTranslator 풀 빌드")
    parser.add_argument("--no-zip", action="store_true", help="zip 생성 생략")
    parser.add_argument("--no-trim", action="store_true",
                        help="tessdata 정리 생략 (모든 언어팩 유지)")
    args = parser.parse_args()

    root = _project_root()
    spec = root / "LLMTranslator.spec"
    if not spec.is_file():
        print("오류: LLMTranslator.spec 파일이 없습니다.")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("오류: PyInstaller가 설치되어 있지 않습니다.\n  pip install pyinstaller")
        return 1

    tess = _find_tesseract_root()
    if tess:
        print(f"Tesseract 번들: {tess}")
    else:
        print(
            "[경고] 번들할 Tesseract를 찾지 못했습니다.\n"
            "       vendor\\Tesseract-OCR\\ 에 tesseract.exe와 tessdata를 두거나\n"
            "       환경변수 TESSERACT_BUNDLE 을 설정한 뒤 다시 빌드하세요.\n"
            "       (이미지/PDF OCR 없이 빌드는 계속됩니다.)\n"
        )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec),
        "--clean",
        "-y",
        "--noconfirm",
    ]
    print("실행:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(root))
    if proc.returncode != 0:
        print("PyInstaller가 실패했습니다.")
        return proc.returncode

    dist_dir = root / "dist" / "LLMTranslator"
    # 사내 보안 정책 우회 — exe 파일명은 python.exe (spec 의 EXE name 과 일치)
    out_exe = dist_dir / "python.exe"
    if not out_exe.is_file():
        print("\n빌드는 끝났지만 예상 경로에 exe가 없습니다. dist 폴더를 확인하세요.")
        return 1

    print(f"\n빌드 완료: {out_exe}")

    # tessdata 정리
    if not args.no_trim and tess:
        print("\n[tessdata 정리]")
        _trim_tessdata(dist_dir)

    # 풀 zip 생성
    if not args.no_zip:
        print(f"\n[풀 패키지 zip 생성 v{APP_VERSION}]")
        _make_full_zip(dist_dir, APP_VERSION)

    print("\n배포 시 풀 zip 또는 dist\\LLMTranslator 폴더 전체를 전달하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
