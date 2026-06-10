"""
패치 zip 생성기.

기존 배포본 위에 덮어쓸 수 있는 패치 zip 을 만든다 — Tesseract-OCR 폴더를 제외해서
용량을 크게 줄임. 사용자는 자신의 폴더 위에 압축 해제하면 코드만 갱신되고 Tesseract
는 그대로 유지됨.

사전 조건: 먼저 build_exe.py 로 dist\\LLMTranslator\\ 가 만들어져 있어야 함.

  python build_exe.py        # 풀 빌드 한 번
  python build_patch.py      # 그 결과로부터 패치 zip 생성

결과물: LLMTranslator_v{버전}_patch.zip
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from constants import APP_VERSION


# 패치에서 제외할 디렉터리 (경로 부분 어디에든 매치되면 제외)
EXCLUDE_DIR_PARTS = {"Tesseract-OCR"}


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _should_exclude(rel_path: Path) -> bool:
    return any(part in EXCLUDE_DIR_PARTS for part in rel_path.parts)


PATCH_README = """LLMTranslator v{version} 패치
==============================

이 zip 은 코드 업데이트만 포함합니다 (Tesseract-OCR 폴더는 제외).
기존 LLMTranslator 폴더 위에 그대로 압축 해제하면 됩니다.

[적용 방법]
  1. 기존 LLMTranslator 폴더 백업 (선택, 권장)
  2. 이 zip 을 기존 폴더와 같은 위치에 압축 해제 → "덮어쓰기" 선택
     (LLMTranslator/ 폴더 안의 파일들이 갱신됨, Tesseract-OCR 은 유지)
  3. python.exe 실행 (LLMTranslator 폴더 안에 있음 — 사내 보안 우회용 명명)

[문제 발생 시]
  - 백업한 폴더로 복원
  - 또는 풀 패키지(LLMTranslator_v{version}_full.zip) 다시 받아 새로 설치

[버전 v{version} 변경 사항]
  - 파일별 번역 예상 시간 표시 (적응형 학습)
  - 메인/설정 GUI 적응형 폰트 시스템 (창 크기에 비례)
  - 번역 모드 선택 카드 스타일 라디오
  - Source/Target 언어 선택값 영속화
  - 언어 리스트 한국어/영어 우선 + 가나다 정렬
  - 드래그앤드롭 정상 동작 (tkinterdnd2 의존성 추가)
"""


def _make_patch_zip(dist_dir: Path, version: str) -> Path:
    out = _project_root() / f"LLMTranslator_v{version}_patch.zip"
    if out.exists():
        out.unlink()

    included = 0
    excluded = 0
    excluded_bytes = 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in dist_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(dist_dir)
            if _should_exclude(rel):
                excluded += 1
                excluded_bytes += f.stat().st_size
                continue
            zf.write(f, arcname=f"LLMTranslator/{rel}")
            included += 1

        # 적용 안내 README
        zf.writestr("LLMTranslator/PATCH_README.txt",
                    PATCH_README.format(version=version))

    return out, included, excluded, excluded_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="LLMTranslator 패치 zip 생성")
    parser.add_argument(
        "--dist", type=str, default=None,
        help="기본: dist/LLMTranslator. 다른 위치에 빌드한 경우 지정",
    )
    args = parser.parse_args()

    root = _project_root()
    dist_dir = Path(args.dist) if args.dist else (root / "dist" / "LLMTranslator")

    if not dist_dir.is_dir():
        print(f"오류: {dist_dir} 가 없습니다.")
        print("       먼저 build_exe.py 로 풀 빌드를 실행하세요.")
        return 1
    if not (dist_dir / "python.exe").is_file():
        print(f"오류: {dist_dir}/python.exe 가 없습니다. 빌드가 완전하지 않습니다.")
        return 1

    print(f"패치 대상 dist: {dist_dir}")
    print(f"버전: v{APP_VERSION}")
    print("제외: Tesseract-OCR/ (사용자 기존 설치 유지)\n")

    out, included, excluded, excluded_bytes = _make_patch_zip(dist_dir, APP_VERSION)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n[완료] 패치 zip 생성 완료")
    print(f"  파일: {out.name} ({size_mb:.1f} MB)")
    print(f"  포함: {included}개 파일")
    if excluded:
        print(f"  제외: {excluded}개 파일 (~{excluded_bytes/1024/1024:.1f} MB 절약, Tesseract-OCR)")
    print("\n사용자 안내:")
    print(f"  1) 기존 LLMTranslator 폴더 위에 {out.name} 을 압축 해제 (덮어쓰기)")
    print("  2) Tesseract-OCR 폴더는 자동으로 그대로 유지됨")
    print("  3) LLMTranslator/python.exe 재실행")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
