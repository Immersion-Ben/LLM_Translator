"""설정 파일(JSON) 로드/저장. v3는 하드코딩된 토큰 제거 + 파일 권한 제한."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dependencies import pytesseract
from logging_config import logger
from security import (
    mask_config,
    restrict_file_permissions,
    validate_agent_id,
    validate_email,
    validate_endpoint_url,
)

CONFIG_DIR = Path.home() / ".llm_translator"
CONFIG_FILE = CONFIG_DIR / "config.json"

# v3: 민감 정보(JWT 등) 하드코딩 제거. 최초 실행 시 사용자 입력 강제.
DEFAULT_CONFIG: dict[str, str] = {
    "client_key": "",
    "pass_key": "",
    "endpoint_url": "https://nsecc-api.fabrix-s.samsungsds.com/secc/trial/api-agent",
    "agent_id": "",                  # 심화번역(RAG on) Agent ID
    "agent_id_fast": "",             # 빠른번역(RAG off) Agent ID. 비워두면 agent_id로 폴백
    "translation_mode": "deep",      # deep | fast. UI에서 즉시 전환 후 저장
    "email": "",
    "tesseract_path": "",
    "max_chunk_chars": "",           # 빈 값이면 모드 기본값(fast=8000, deep=5000)
    "timeout_seconds": "120",
    "allow_insecure_ssl": "false",   # SSL verify=False 폴백 허용 여부 (기본: 금지)
    "ui_theme": "light",              # light | dark
    "font_scale": "1.0",              # 원문/번역 패널 폰트 스케일
    "auto_open_result": "false",      # 번역 완료 후 결과 폴더 자동 열기
    "source_lang": "",                # 마지막으로 선택한 원문 언어 (UI 표시명, 빈 값=기본값 사용)
    "target_lang": "",                # 마지막으로 선택한 번역 언어 (UI 표시명, 빈 값=기본값 사용)
    "avg_secs_per_chunk_fast": "",    # 시간 추정용 EMA — 빠른번역 청크당 평균 (빈 값=기본값)
    "avg_secs_per_chunk_deep": "",    # 시간 추정용 EMA — 심화번역 청크당 평균 (빈 값=기본값)
}

REQUIRED_KEYS = ("client_key", "pass_key", "endpoint_url", "agent_id", "email")


class ConfigManager:
    """설정 파일(JSON) 로드/저장 관리."""

    def __init__(self) -> None:
        self.config: dict[str, str] = dict(DEFAULT_CONFIG)
        self._ensure_dir()
        self.load()
        self.apply_tesseract_path()

    # ------------------------------------------------------------------
    # 파일 I/O
    # ------------------------------------------------------------------
    def _ensure_dir(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        restrict_file_permissions(CONFIG_DIR)

    def load(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"CONFIG-01: config 로드 실패 ({type(e).__name__})")
            self.config = dict(DEFAULT_CONFIG)
            return

        merged = dict(DEFAULT_CONFIG)
        for k, v in saved.items():
            if isinstance(v, str):
                merged[k] = v
        self.config = merged
        logger.info(f"CONFIG-LOADED: {mask_config(self.config)}")

    def save(self) -> None:
        self._ensure_dir()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        restrict_file_permissions(CONFIG_FILE)
        logger.info("CONFIG-SAVED")

    # ------------------------------------------------------------------
    # 접근자
    # ------------------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        return self.config.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.config.get(key, "")
        if not raw:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    def get_int(self, key: str, default: int) -> int:
        raw = self.config.get(key, "")
        try:
            return int(raw) if raw.strip().isdigit() else default
        except (ValueError, AttributeError):
            return default

    def get_float(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, "") or default)
        except (ValueError, TypeError):
            return default

    def set(self, key: str, value: Any) -> None:
        self.config[key] = str(value) if value is not None else ""

    def is_configured(self) -> bool:
        return all(self.config.get(k, "").strip() for k in REQUIRED_KEYS)

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------
    def validate(self) -> list[str]:
        """설정 전체 검증. 에러 메시지 리스트 반환 (빈 리스트면 OK)."""
        errors: list[str] = []

        ok, msg = validate_endpoint_url(self.config.get("endpoint_url", ""))
        if not ok:
            errors.append(f"Endpoint URL: {msg}")

        ok, msg = validate_email(self.config.get("email", ""))
        if not ok:
            errors.append(f"Email: {msg}")

        ok, msg = validate_agent_id(self.config.get("agent_id", ""))
        if not ok:
            errors.append(f"Agent ID: {msg}")

        if not self.config.get("client_key", "").strip():
            errors.append("Client Key가 비어 있습니다.")
        if not self.config.get("pass_key", "").strip():
            errors.append("Pass Key가 비어 있습니다.")

        # 청크 크기는 비어 있으면 모드 기본값으로 처리하므로 검증 생략 가능
        raw_chunk = self.config.get("max_chunk_chars", "").strip()
        if raw_chunk:
            chunk = self.get_int("max_chunk_chars", 0)
            if chunk < 500:
                errors.append("최대 청크 크기는 500 이상이거나 비워 두어야 합니다.")

        mode = self.config.get("translation_mode", "deep").strip().lower()
        if mode not in ("fast", "deep"):
            errors.append("번역 모드는 fast 또는 deep 이어야 합니다.")

        timeout = self.get_int("timeout_seconds", 120)
        if not (5 <= timeout <= 600):
            errors.append("타임아웃은 5~600초 범위여야 합니다.")

        return errors

    # ------------------------------------------------------------------
    # API helper
    # ------------------------------------------------------------------
    def get_api_headers(self) -> dict[str, str]:
        return {
            "x-fabrix-client": self.config.get("client_key", ""),
            "x-openapi-token": self.config.get("pass_key", ""),
            "x-generative-ai-user-email": self.config.get("email", ""),
        }

    def get_api_url(self) -> str:
        base = self.config.get("endpoint_url", "").rstrip("/")
        return f"{base}/openapi/agent-chat/v1/agent-messages"

    # ------------------------------------------------------------------
    # Tesseract
    # ------------------------------------------------------------------
    def paddleocr_model_root(self):
        """번들/캐시된 PaddleOCR 모델 루트. _MEIPASS→exe폴더→vendor→~/.paddlex 순."""
        import os, sys
        from pathlib import Path
        from constants import PADDLE_VENDOR_DIRNAME
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(os.path.dirname(sys.executable)) / PADDLE_VENDOR_DIRNAME)
            mp = getattr(sys, "_MEIPASS", "")
            if mp:
                candidates.append(Path(mp) / PADDLE_VENDOR_DIRNAME)
        candidates.append(Path(__file__).resolve().parent / "vendor" / PADDLE_VENDOR_DIRNAME)
        candidates.append(Path.home() / ".paddlex" / "official_models")
        for c in candidates:
            if c.is_dir():
                return c
        return None

    def apply_tesseract_path(self) -> None:
        return  # no-op 셰임(호출부 보호, 이후 제거)
