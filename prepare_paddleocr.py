"""vendor/paddleocr-models/official_models/ 구성: PaddleX 캐시 모델 전체 복사.

사내 오프라인망 배포를 위해, 인터넷이 되는 PC에서 앱을 1회 구동(또는
`python -m pytest tests/test_paddle_ocr.py`)해 모델을 캐시한 뒤 이 스크립트로
vendor 폴더에 모아 둔다. build_exe.py 가 이 폴더를 exe 에 번들하고, 런타임은
PADDLE_PDX_CACHE_HOME 을 이 위치로 지정해 인터넷 없이 모델을 로드한다.

표 인식 파이프라인(TableRecognitionPipelineV2)은 wired/wireless 양쪽 표 모델을
모두 적재하므로, 특정 모델만이 아니라 캐시된 official_models 전체를 복사한다.

  python prepare_paddleocr.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from constants import PADDLE_VENDOR_DIRNAME

SRC = Path.home() / ".paddlex" / "official_models"
# 런타임 PADDLE_PDX_CACHE_HOME 가 <vendor>/paddleocr-models 를 가리키므로,
# 모델은 그 아래 official_models/ 에 위치해야 한다.
DEST_ROOT = Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME
DEST = DEST_ROOT / "official_models"


def main() -> int:
    if not SRC.is_dir():
        print(f"[오류] 캐시 모델 폴더가 없습니다: {SRC}")
        print("       먼저 앱을 1회 구동하거나 `python -m pytest tests/test_paddle_ocr.py` 로")
        print("       모델을 내려받아 캐시한 뒤 다시 실행하세요.")
        return 1

    models = sorted(p for p in SRC.iterdir() if p.is_dir())
    if not models:
        print(f"[오류] 캐시에 모델이 없습니다: {SRC}")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in models:
        shutil.copytree(src, DEST / src.name, dirs_exist_ok=True)
        copied.append(src.name)

    total = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    print(f"[완료] {len(copied)}개 모델 → {DEST} ({total / 1024 / 1024:.1f} MB)")
    for name in copied:
        print(f"   + {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
