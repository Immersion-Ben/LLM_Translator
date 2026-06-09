"""LLM Translator v3 진입점."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from logging_config import logger
from runtime_setup import setup_runtime_environment


def main() -> int:
    setup_runtime_environment()

    error_code: str | None = None
    error_type: str = ""

    try:
        print("🌐 LLM Translator v3 시작 중...")
        from app_ui import TranslatorApp  # 지연 import (설정 로딩 순서 보장)
        app = TranslatorApp()
        print("✅ 초기화 완료. GUI를 표시합니다.")
        app.run()
        return 0
    except ImportError as e:
        logger.error(f"SYS-01: Essential module missing: {e}")
        error_code, error_type = "SYS-01", "시스템 구성 모듈 누락"
    except ConnectionError as e:
        logger.error(f"SYS-02: Connection failed: {e}")
        error_code, error_type = "SYS-02", "서버 연결 오류"
    except RuntimeError as e:
        logger.error(f"SYS-03: Runtime failure: {e}")
        error_code, error_type = "SYS-03", "프로그램 실행 환경 오류"
    except KeyboardInterrupt:
        logger.info("SYS-INT: User interrupted")
        return 130
    except Exception as e:  # noqa: BLE001
        logger.error(f"SYS-99: Unexpected critical failure: {type(e).__name__}: {e}")
        error_code, error_type = "SYS-99", "알 수 없는 시스템 오류"

    if error_code is not None:
        print(f"\n❌ {error_type} (Code: {error_code})")
        print("상세 내용은 로그 파일(~/.llm_translator/logs/app.log)을 확인해 주세요.")
        _show_error_dialog(error_code, error_type)
        try:
            input("\nEnter를 눌러 종료하세요...")
        except EOFError:
            # 대화형 입력이 불가능한 실행 환경(예: GUI 더블클릭) — 정상 종료한다.
            logger.debug("MAIN-EOF: 대화형 입력 불가 환경, 대기 없이 종료")
    return 1


def _show_error_dialog(error_code: str, error_type: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        msg = (
            "프로그램 시작 중 오류가 발생했습니다.\n\n"
            f"오류 유형: {error_type}\n"
            f"에러 코드: {error_code}\n\n"
            "로그 파일: ~/.llm_translator/logs/app.log\n"
            "지속될 경우 관리자에게 로그를 전달해 주세요."
        )
        messagebox.showerror("LLM Translator 시스템 오류", msg)
        root.destroy()
    except (ImportError, tk.TclError):
        logger.error("GUI Error Display Failed")
    except Exception:
        logger.error("Unexpected error in GUI sequence")


if __name__ == "__main__":
    sys.exit(main())
