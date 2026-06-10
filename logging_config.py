"""로깅 구성: 회전 파일 로그 + 민감정보 마스킹 필터."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".llm_translator" / "logs"
LOG_FILE = LOG_DIR / "app.log"
MAX_BYTES = 2_000_000  # 2MB
BACKUP_COUNT = 5

# Bearer 토큰, JWT, 긴 영숫자 시퀀스 마스킹 패턴
_SENSITIVE_PATTERNS = (
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.=]+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"eyJ[A-Za-z0-9\-_\.=]{20,}"), "<JWT-MASKED>"),
    (re.compile(r"\"(client_key|pass_key|password|token|secret)\"\s*:\s*\"[^\"]+\"", re.IGNORECASE),
     r'"\1": "<MASKED>"'),
)


class _RedactFilter(logging.Filter):
    """로그 메시지의 민감정보를 마스킹."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except (TypeError, ValueError):
            # 메시지 포매팅(%-format) 실패 시 마스킹을 건너뛰고 통과시킨다.
            return True
        for pattern, replacement in _SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True


def _build_logger() -> logging.Logger:
    lg = logging.getLogger("llm_translator3")
    lg.setLevel(logging.INFO)

    if lg.handlers:
        return lg

    lg.addFilter(_RedactFilter())

    # 콘솔 핸들러 (ERROR 이상)
    console = logging.StreamHandler()
    console.setLevel(logging.ERROR)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    lg.addHandler(console)

    # 파일 핸들러 (INFO 이상, 회전 로그)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        lg.addHandler(file_handler)
    except OSError:
        # 파일 로그 실패는 비치명적 (GUI로 계속 동작)
        lg.addHandler(logging.NullHandler())

    lg.propagate = False
    return lg


logger = _build_logger()
