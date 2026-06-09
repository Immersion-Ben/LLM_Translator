"""언어 매핑 및 지원 파일 형식 정의."""
from __future__ import annotations

APP_NAME = "LLM Translator"
APP_VERSION = "3.1.0"
APP_TITLE = f"{APP_NAME}  |  Samsung C&T"

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

# OCR 언어 코드 매핑 (pytesseract용)
OCR_LANG_MAP: dict[str, str] = {
    "Vietnamese": "vie",
    "English": "eng",
    "Japanese": "jpn",
    "Korean": "kor",
    "Simplified Chinese": "chi_sim",
    "Traditional Chinese": "chi_tra",
    "Thai": "tha",
    "Indonesian": "ind",
    "French": "fra",
    "German": "deu",
    "Spanish": "spa",
    "Russian": "rus",
    "Arabic": "ara",
    "Hindi": "hin",
    "Portuguese": "por",
    "Italian": "ita",
    "Turkish": "tur",
    "Polish": "pol",
    "Dutch": "nld",
    "Malay": "msa",
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
