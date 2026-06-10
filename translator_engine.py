"""LLM API 기반 번역 엔진. Fabrix Agent API 호출 + 청크 분할 + 재시도."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

import requests

from constants import (
    DEFAULT_SRC,
    DEFAULT_TGT,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RETRY_ATTEMPTS,
    RETRY_BACKOFF_BASE,
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
)
from logging_config import logger


class TranslationCancelled(Exception):
    """사용자 취소 요청에 의해 번역이 중단됨."""


class LLMTranslator:
    """
    LLM API 기반 번역 엔진.

    - Fabrix Agent API 호출
    - 긴 텍스트는 자동 청크 분할
    - 지수 백오프 재시도 (최대 MAX_RETRY_ATTEMPTS)
    - 취소 토큰 지원 (threading.Event)
    - 번역 모드: fast(빠른/RAG off) / deep(심화/RAG on)
    """

    # 모드별 기본 청크 크기 (사용자가 max_chunk_chars 비워두면 이 값 적용)
    CHUNK_DEFAULTS = {"fast": 8000, "deep": 5000}
    MAX_CHUNK_CHARS = 5000

    def __init__(
        self,
        config,
        cancel_event: Optional[threading.Event] = None,
        mode: Optional[str] = None,
    ) -> None:
        self.config = config
        self.source_lang = SOURCE_LANGUAGES[DEFAULT_SRC]
        self.target_lang = TARGET_LANGUAGES[DEFAULT_TGT]
        self.ready = True
        self._cancel_event = cancel_event or threading.Event()

        raw_mode = (mode or self.config.get("translation_mode", "deep")).strip().lower()
        self.mode = raw_mode if raw_mode in ("fast", "deep") else "deep"

        self._apply_chunk_size()
        self.timeout = self.config.get_int("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        self.allow_insecure_ssl = self.config.get_bool("allow_insecure_ssl", False)

    def _apply_chunk_size(self) -> None:
        """사용자 설정이 있으면 그 값, 없으면 모드별 기본값."""
        raw = self.config.get("max_chunk_chars", "").strip()
        if raw.isdigit() and int(raw) >= 500:
            self.MAX_CHUNK_CHARS = int(raw)
        else:
            self.MAX_CHUNK_CHARS = self.CHUNK_DEFAULTS.get(self.mode, 5000)

    def set_mode(self, mode: str) -> None:
        """번역 모드 전환. fast: RAG off+대용량 청크, deep: RAG on+정밀."""
        m = mode.strip().lower()
        if m not in ("fast", "deep"):
            return
        self.mode = m
        self._apply_chunk_size()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_languages(self, source_lang: str, target_lang: str) -> None:
        self.source_lang = source_lang
        self.target_lang = target_lang

    def set_cancel_event(self, event: threading.Event) -> None:
        self._cancel_event = event

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _check_cancel(self) -> None:
        if self._cancel_event.is_set():
            raise TranslationCancelled("사용자가 번역을 취소했습니다.")

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return text
        if re.match(r"^[\d\s\W]+$", text.strip()):
            return text

        self._check_cancel()

        if len(text) <= self.MAX_CHUNK_CHARS:
            return self._call_api_with_retry(text)

        chunks = self._split_text(text)
        translated_chunks: list[str] = []
        for chunk in chunks:
            self._check_cancel()
            translated_chunks.append(self._call_api_with_retry(chunk))
        return "\n\n".join(translated_chunks)

    # ------------------------------------------------------------------
    # 청크 분할
    # ------------------------------------------------------------------
    def _split_text(self, text: str) -> list[str]:
        max_chars = self.MAX_CHUNK_CHARS
        if len(text) <= max_chars:
            return [text]

        paragraphs = re.split(r"\n\s*\n", text)
        chunks = self._merge_segments(paragraphs, max_chars, separator="\n\n")

        final_chunks: list[str] = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final_chunks.append(chunk)
                continue

            lines = chunk.split("\n")
            sub_chunks = self._merge_segments(lines, max_chars, separator="\n")
            for sc in sub_chunks:
                if len(sc) <= max_chars:
                    final_chunks.append(sc)
                    continue
                sentences = re.split(r"(?<=[.!?。！？])\s+", sc)
                sent_chunks = self._merge_segments(sentences, max_chars, separator=" ")
                for sent_c in sent_chunks:
                    if len(sent_c) <= max_chars:
                        final_chunks.append(sent_c)
                    else:
                        final_chunks.extend(self._force_split(sent_c, max_chars))

        return [c for c in final_chunks if c.strip()]

    @staticmethod
    def _merge_segments(segments: list[str], max_chars: int, separator: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            if not current:
                current = seg
            elif len(current) + len(separator) + len(seg) <= max_chars:
                current += separator + seg
            else:
                chunks.append(current)
                current = seg
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _force_split(text: str, max_chars: int) -> list[str]:
        chunks: list[str] = []
        while len(text) > max_chars:
            split_at = text.rfind(" ", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            chunks.append(text[:split_at].strip())
            text = text[split_at:].strip()
        if text:
            chunks.append(text)
        return chunks

    # ------------------------------------------------------------------
    # API 호출 (재시도 + 취소 체크)
    # ------------------------------------------------------------------
    def _resolve_agent_id(self) -> str:
        """현재 모드에 맞는 Agent ID 반환. 빠른번역 미설정 시 심화번역으로 폴백."""
        if self.mode == "fast":
            fast_id = self.config.get("agent_id_fast", "").strip()
            if fast_id:
                return fast_id
            # 폴백: deep용 agent_id 사용
            return self.config.get("agent_id", "").strip()
        return self.config.get("agent_id", "").strip()

    def _build_body(self, text: str) -> dict:
        prompt = (
            f"아래 구분선 안의 내용을 {self.target_lang}로 번역해주세요. "
            f"번역된 텍스트만 출력하고, 설명이나 부연은 하지 마세요.\n\n"
            f"===번역할 내용 시작===\n"
            f"{text}\n"
            f"===번역할 내용 끝==="
        )
        agent_id = self._resolve_agent_id()
        if not agent_id:
            raise ValueError(
                "Agent ID가 비어 있습니다. 설정에서 심화번역 Agent ID를 먼저 입력해 주세요."
            )
        use_rag = self.mode != "fast"  # fast: RAG off, deep: RAG on
        return {
            "agentId": agent_id,
            "contents": [prompt],
            "isStream": False,
            "isRagOn": use_rag,
            "executeFinalAnswer": True,
            "executeRagFinalAnswer": use_rag,
            "executeRagStandaloneQuery": use_rag,
        }

    def _call_api_with_retry(self, text: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            self._check_cancel()
            try:
                return self._call_api(text)
            except TranslationCancelled:
                raise
            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as e:
                last_exc = e
                logger.error(f"API-RETRY: {type(e).__name__} (attempt {attempt}/{MAX_RETRY_ATTEMPTS})")
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", 0)
                if status in (429, 500, 502, 503, 504):
                    last_exc = e
                    logger.error(f"API-RETRY: HTTP {status} (attempt {attempt}/{MAX_RETRY_ATTEMPTS})")
                else:
                    raise

            if attempt < MAX_RETRY_ATTEMPTS:
                backoff = RETRY_BACKOFF_BASE ** attempt
                # 취소 체크하면서 대기
                waited = 0.0
                while waited < backoff:
                    self._check_cancel()
                    time.sleep(min(0.2, backoff - waited))
                    waited += 0.2

        assert last_exc is not None
        raise last_exc

    def _call_api(self, text: str) -> str:
        body = self._build_body(text)
        url = self.config.get_api_url()
        headers = self.config.get_api_headers()

        # 진단: 요청 크기/모드/agent 프리뷰 기록 (민감정보 제외)
        logger.info(
            f"API-REQ: mode={self.mode} len={len(text)} url={url} "
            f"agent={body['agentId'][:4] + '...' if body['agentId'] else '<empty>'}"
        )

        try:
            response = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
            if not self.allow_insecure_ssl:
                logger.error("API-SSL: SSL 검증 실패. (verify=False 폴백이 허용되지 않음)")
                raise
            logger.warning("API-SSL: verify=False 폴백 (사용자 승인)")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.post(
                url, json=body, headers=headers, timeout=self.timeout, verify=False
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            body_preview = (response.text or "")[:300].replace("\n", " ")
            logger.error(
                f"API-HTTP: status={response.status_code} "
                f"ct='{response.headers.get('content-type', '')}' "
                f"body[0:300]={body_preview!r}"
            )
            raise

        # 응답 파싱: Content-Type이 JSON이 아니어도 본문이 JSON이면 수용
        ct = response.headers.get("content-type", "")
        data: Optional[dict] = None
        parse_exc: Optional[Exception] = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except ValueError as e:
            parse_exc = e

        if data is None:
            body_preview = (response.text or "")[:300].replace("\n", " ")
            logger.error(
                f"API-PARSE: JSON 파싱 실패. status={response.status_code} ct='{ct}' "
                f"err={type(parse_exc).__name__ if parse_exc else 'not-dict'} "
                f"body[0:300]={body_preview!r}"
            )
            raise ValueError(
                f"API 응답을 해석할 수 없습니다 (status={response.status_code}, content-type={ct})."
            )

        result = data.get("content", "")
        if not result:
            # 흔한 오류 페이로드를 로그에 그대로 노출하여 진단 가능하게 함
            keys = list(data.keys())
            snippet = str({k: data[k] for k in keys[:8]})[:300]
            logger.error(f"API-EMPTY: content 누락. keys={keys} payload[0:300]={snippet}")
            raise ValueError(
                "API 응답에 content가 없습니다. 설정의 Agent ID와 권한, RAG 설정을 확인하세요."
            )
        return str(result).strip()
