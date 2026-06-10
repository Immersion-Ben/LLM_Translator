"""런타임 공통 설정: SSL, stdio, UTF-8."""
from __future__ import annotations

import atexit
import os
import sys

from logging_config import logger

# GUI 배포 시 None 인 stdio 를 대체하기 위해 연 os.devnull 핸들의 참조.
# 프로세스 종료 시까지 열려 있어야 하므로 with/finally 로 즉시 닫을 수 없고,
# 대신 atexit 으로 종료 시점에 반드시 해제한다 (CWE-404 자원 해제 보장).
_DEVNULL_STREAMS: list = []


def setup_runtime_environment() -> None:
    """런타임 환경 공통 설정."""
    _setup_ssl_cert_bundle()
    _fix_stdio_for_gui()
    _setup_utf8_output_for_windows()


def _setup_ssl_cert_bundle() -> None:
    """PyInstaller 번들 환경 포함 SSL 인증서 경로 설정."""
    try:
        import certifi
    except ImportError:
        return

    try:
        cert_path = certifi.where()
        if cert_path and os.path.exists(cert_path):
            os.environ["SSL_CERT_FILE"] = cert_path
            os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    except (OSError, AttributeError) as e:
        # certifi 경로 확인 실패는 비치명적이나, 원인 추적을 위해 기록한다.
        logger.warning(f"SSL-CERT: 인증서 경로 설정 실패 ({type(e).__name__})")


def _open_devnull(mode: str):
    """os.devnull 스트림을 열고 종료 시 자동 해제되도록 등록한다."""
    stream = open(os.devnull, mode)
    _DEVNULL_STREAMS.append(stream)
    atexit.register(stream.close)
    return stream


def _fix_stdio_for_gui() -> None:
    """GUI 배포 시 stdin/stdout/stderr None 방지."""
    if sys.stdout is None:
        sys.stdout = _open_devnull("w")
    if sys.stderr is None:
        sys.stderr = _open_devnull("w")
    if sys.stdin is None:
        sys.stdin = _open_devnull("r")


def _setup_utf8_output_for_windows() -> None:
    """Windows cp949 인코딩 에러 완화."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError) as e:
                # 스트림이 reconfigure 를 지원하지 않는 경우 — 비치명적, 기록만 한다.
                logger.warning(f"UTF8-{name}: reconfigure 실패 ({type(e).__name__})")
