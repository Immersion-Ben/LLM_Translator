"""보안 유틸리티: URL/이메일/경로 검증, 민감정보 마스킹, 파일 권한 설정."""
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from logging_config import logger

SENSITIVE_KEYS: tuple[str, ...] = (
    "client_key",
    "pass_key",
    "password",
    "secret",
    "token",
    "authorization",
)

ALLOWED_URL_SCHEMES = ("https", "http")


def validate_endpoint_url(url: str) -> tuple[bool, str]:
    """엔드포인트 URL이 안전한 HTTP(S) URL인지 검증."""
    if not url or not url.strip():
        return False, "URL이 비어 있습니다."

    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL 형식이 올바르지 않습니다."

    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        return False, f"허용되지 않은 스킴입니다. (https/http 만 허용, 현재: {parsed.scheme})"

    if not parsed.netloc:
        return False, "호스트가 없는 URL입니다."

    if any(ch in url for ch in ("\n", "\r", "\t")):
        return False, "URL에 제어 문자가 포함되어 있습니다."

    return True, ""


def validate_email(email: str) -> tuple[bool, str]:
    """이메일 형식 기본 검증."""
    if not email or not email.strip():
        return False, "이메일이 비어 있습니다."

    pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
    if not re.match(pattern, email.strip()):
        return False, "이메일 형식이 올바르지 않습니다."
    return True, ""


def validate_agent_id(agent_id: str) -> tuple[bool, str]:
    """Agent ID 형식 검증 (UUID 또는 영숫자·하이픈)."""
    if not agent_id or not agent_id.strip():
        return False, "Agent ID가 비어 있습니다."
    if not re.match(r"^[A-Za-z0-9\-_]+$", agent_id.strip()):
        return False, "Agent ID에 허용되지 않은 문자가 포함되어 있습니다."
    return True, ""


def mask_secret(value: str, visible: int = 4) -> str:
    """민감 값 마스킹. 처음 visible 글자만 노출."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= visible:
        return "*" * len(s)
    return s[:visible] + "*" * (len(s) - visible)


def mask_config(config: dict, sensitive_keys: Iterable[str] = SENSITIVE_KEYS) -> dict:
    """로그 출력용 config 사본 (민감 키 마스킹)."""
    masked = {}
    for k, v in config.items():
        if any(s in k.lower() for s in sensitive_keys):
            masked[k] = mask_secret(str(v) if v else "")
        else:
            masked[k] = v
    return masked


def restrict_file_permissions(path: str | Path) -> None:
    """POSIX에서 소유자만 접근 가능하도록 권한 제한.
    - 파일: 0o600 (rw-------)
    - 디렉터리: 0o700 (rwx------, 내부 접근/나열 위해 x 필요)
    Windows는 noop.
    """
    if sys.platform == "win32":
        return
    try:
        p = Path(path)
        if p.is_dir():
            os.chmod(str(p), stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        else:
            os.chmod(str(p), stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        # 권한 설정 실패는 비치명적(예: 파일시스템 미지원)이나 추적을 위해 기록한다.
        logger.warning(f"PERM: 파일 권한 설정 실패 ({type(e).__name__})")


# 번역 입력으로 허용되는 확장자 (constants.SUPPORTED_EXTENSIONS 와 동기화 유지).
ALLOWED_INPUT_EXTENSIONS: tuple[str, ...] = (
    ".docx", ".pdf", ".txt", ".xlsx", ".pptx",
    ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif",
)


def validate_input_path(filepath: str | Path) -> Path:
    """외부에서 전달된 입력 파일 경로를 검증하여 안전한 절대 Path 로 반환한다.

    경로 조작(Path Traversal, CWE-22) 및 비정상 입력을 차단한다.
    - 빈 값 / 제어 문자 / NUL 바이트 거부
    - 경로를 정규화(resolve)하여 '..' 등 상대 순회 요소 제거 후 실제 파일인지 확인
    - 사전 정의된 허용 확장자만 통과
    검증 실패 시 ValueError 를 발생시킨다.
    """
    if filepath is None or not str(filepath).strip():
        raise ValueError("입력 파일 경로가 비어 있습니다.")

    raw = str(filepath)
    if "\x00" in raw or any(ch in raw for ch in ("\n", "\r", "\t")):
        raise ValueError("입력 경로에 허용되지 않은 제어 문자가 포함되어 있습니다.")

    try:
        # resolve() 가 '..' 와 심볼릭 링크를 정규화하여 경로 순회를 무력화한다.
        resolved = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as e:
        raise ValueError(f"입력 경로를 확인할 수 없습니다 ({type(e).__name__})")

    if not resolved.is_file():
        raise ValueError("입력 경로가 실제 파일이 아닙니다.")

    if resolved.suffix.lower() not in ALLOWED_INPUT_EXTENSIONS:
        raise ValueError(f"허용되지 않은 파일 형식입니다: {resolved.suffix}")

    return resolved


def safe_output_path(base_dir: Path, filename: str) -> Path:
    """base_dir 하위로만 해결되도록 강제하여 path traversal 방지."""
    base = Path(base_dir).resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise ValueError(f"허용되지 않은 출력 경로: {filename}")
    return candidate


def is_within_text_limit(text: str, max_bytes: int = 50_000_000) -> bool:
    """UTF-8 기준 크기 상한 (기본 50MB)."""
    return len(text.encode("utf-8", errors="replace")) <= max_bytes
