"""vendor/paddleocr-models/ 구성: ~/.paddlex/official_models 에서 확정 모델만 복사.

사내 오프라인망 배포를 위해, 인터넷이 되는 PC에서 앱을 1회 구동(또는 스모크 테스트)해
모델을 캐시한 뒤 이 스크립트로 vendor 폴더에 모아 둔다. build_exe.py 가 이 폴더를
exe 에 번들한다.

  python prepare_paddleocr.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from constants import PADDLE_MODELS, PADDLE_VENDOR_DIRNAME

SRC = Path.home() / ".paddlex" / "official_models"
DEST = Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME


def main() -> int:
    if not SRC.is_dir():
        print(f"[오류] 캐시 모델 폴더가 없습니다: {SRC}")
        print("       먼저 앱을 1회 구동하거나 `python -m pytest tests/test_paddle_ocr.py` 로")
        print("       모델을 내려받아 캐시한 뒤 다시 실행하세요.")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for name in sorted(set(PADDLE_MODELS.values())):
        src = SRC / name
        if src.is_dir():
            shutil.copytree(src, DEST / name, dirs_exist_ok=True)
            copied.append(name)
        else:
            missing.append(name)

    total = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    print(f"[완료] {len(copied)}개 모델 → {DEST} ({total / 1024 / 1024:.1f} MB)")
    for name in copied:
        print(f"   + {name}")
    if missing:
        print(f"  [경고] 누락(먼저 1회 구동해 캐시 필요): {', '.join(missing)}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
