"""언어 매핑 및 지원 파일 형식 정의."""
from __future__ import annotations

APP_NAME = "LLM Translator"
APP_EDITION = "Enhanced OCR"
# Enhanced OCR 정식 1차 릴리스. 무테두리 표 본문 중복 제거 + 좌표 기반
# 읽기순서 복원 + 입력 경로 검증(CWE-22) 반영으로 알파를 졸업한 첫 정식 버전.
APP_VERSION = "1.0.0"
APP_TITLE = f"{APP_NAME} · {APP_EDITION}  |  Samsung C&T"

# 한국어/영어 최상단 + 나머지 가나다 순. 두 dict 동일 순서 유지.
SOURCE_LANGUAGES: dict[str, str] = {
    "한국어": "Korean",
    "영어": "English",
    "네덜란드어": "Dutch",
    "독일어": "German",
    "러시아어": "Russian",
    "말레이어": "Malay",
    "베트남어": "Vietnamese",
    "스페인어": "Spanish",
    "아랍어": "Arabic",
    "이탈리아어": "Italian",
    "인도네시아어": "Indonesian",
    "일본어": "Japanese",
    "중국어(간체)": "Simplified Chinese",
    "중국어(번체)": "Traditional Chinese",
    "태국어": "Thai",
    "터키어": "Turkish",
    "포르투갈어": "Portuguese",
    "폴란드어": "Polish",
    "프랑스어": "French",
    "힌디어": "Hindi",
}

TARGET_LANGUAGES: dict[str, str] = {
    "한국어": "Korean",
    "영어": "English",
    "네덜란드어": "Dutch",
    "독일어": "German",
    "러시아어": "Russian",
    "말레이어": "Malay",
    "베트남어": "Vietnamese",
    "스페인어": "Spanish",
    "아랍어": "Arabic",
    "이탈리아어": "Italian",
    "인도네시아어": "Indonesian",
    "일본어": "Japanese",
    "중국어(간체)": "Simplified Chinese",
    "중국어(번체)": "Traditional Chinese",
    "태국어": "Thai",
    "터키어": "Turkish",
    "포르투갈어": "Portuguese",
    "폴란드어": "Polish",
    "프랑스어": "French",
    "힌디어": "Hindi",
}

# OCR 산출물 폴더(원본 옆), 번역결과(번역결과)와 동격
OCR_DIR_NAME = "OCR결과"

# 중앙 색인(재시작 목록 복원용)
JOBS_INDEX_PATH = "~/.llm_translator/jobs.json"

# 작업 상태 / 모드
class JobStatus:
    QUEUED = "QUEUED"
    OCR_RUNNING = "OCR_RUNNING"
    OCR_DONE = "OCR_DONE"
    TRANS_QUEUED = "TRANS_QUEUED"
    TRANSLATING = "TRANSLATING"
    DONE = "DONE"
    FAILED = "FAILED"

MODE_FULL = "full"
MODE_OCR_ONLY = "ocr_only"

# PaddleOCR 오프라인 모델
PADDLE_VENDOR_DIRNAME = "paddleocr-models"
# det/rec 은 경량(mobile) 모델 사용 — CPU 노트북에서 server 급 det/rec 은
# 페이지당 ~2분(실문서 ~14분)으로 비실용적, mobile 교체로 ~3.4배 단축
# (bench_ocr.py 실측 117s→34.5s, 동일 테스트 페이지에서 인식 결과 손실 없음).
# layout 은 L 유지: 페이지당 +3.5s 뿐인데 S 는 작은 표를 놓침(selftest 실패).
# 표 구조/셀 모델은 표 영역에만 실행되므로 정확도 우선으로 유지.
PADDLE_MODELS: dict[str, str] = {
    "layout_detection_model_name": "PP-DocLayout-L",
    "table_classification_model_name": "PP-LCNet_x1_0_table_cls",
    "wired_table_structure_recognition_model_name": "SLANeXt_wired",
    "wired_table_cells_detection_model_name": "RT-DETR-L_wired_table_cell_det",
    "doc_orientation_classify_model_name": "PP-LCNet_x1_0_doc_ori",
    "text_detection_model_name": "PP-OCRv5_mobile_det",
    "text_recognition_model_name": "PP-OCRv5_mobile_rec",
}

# 원본 언어(영문명, SOURCE_LANGUAGES 의 값) → 텍스트 인식(rec) 모델.
# 검출(det)/레이아웃은 문자종 무관이라 공용, rec 만 문자권별 모델이 필요하다.
# 라틴 문자권 11개 언어는 latin 통합 모델 하나로 커버. 미등재 언어는
# PADDLE_MODELS 의 기본 rec(중/영/일)으로 동작한다.
_REC_LATIN = "latin_PP-OCRv5_mobile_rec"
PADDLE_REC_BY_LANG: dict[str, str] = {
    "Korean": "korean_PP-OCRv5_mobile_rec",
    "English": "en_PP-OCRv5_mobile_rec",
    "Dutch": _REC_LATIN,
    "German": _REC_LATIN,
    "Malay": _REC_LATIN,
    "Vietnamese": _REC_LATIN,
    "Spanish": _REC_LATIN,
    "Italian": _REC_LATIN,
    "Indonesian": _REC_LATIN,
    "Turkish": _REC_LATIN,
    "Portuguese": _REC_LATIN,
    "Polish": _REC_LATIN,
    "French": _REC_LATIN,
    "Russian": "cyrillic_PP-OCRv5_mobile_rec",
    "Arabic": "arabic_PP-OCRv5_mobile_rec",
    "Japanese": "PP-OCRv5_mobile_rec",
    "Simplified Chinese": "PP-OCRv5_mobile_rec",
    "Traditional Chinese": "PP-OCRv5_mobile_rec",
    "Thai": "th_PP-OCRv5_mobile_rec",
    "Hindi": "devanagari_PP-OCRv5_mobile_rec",
}

DEFAULT_SRC = "베트남어"
DEFAULT_TGT = "한국어"

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".docx": "Word",
    ".pdf": "PDF",
    ".txt": "TXT",
    ".xlsx": "Excel",
    ".pptx": "PPT",
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".bmp": "BMP",
    ".tiff": "TIFF",
    ".tif": "TIF",
}

IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

# 번역 결과/중간 파일 저장 폴더명
RESULT_DIR_NAME = "번역결과"
EXTRACT_DIR_NAME = "텍스트추출파일"
INPUT_DIR_NAME = "번역할파일"

# 네트워크 정책
DEFAULT_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2.0  # 지수 백오프 기준 (초)

# UI 기본 스케일. 글자/위젯이 너무 작다는 피드백을 반영해 기본값을 ~2배로 키움.
# 사용자가 설정에서 변경하는 font_scale 위에 곱해진다.
UI_BASE_SCALE = 1.8
