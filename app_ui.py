"""TranslatorApp GUI. v3: 드래그앤드롭, 개별 파일 관리, 취소, 재시도, 단축키, 테마."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from config_manager import ConfigManager
from constants import (
    APP_NAME,
    APP_TITLE,
    APP_VERSION,
    DEFAULT_SRC,
    DEFAULT_TGT,
    IMAGE_EXTENSIONS,
    JOBS_INDEX_PATH,
    JobStatus,
    MODE_FULL,
    MODE_OCR_ONLY,
    SOURCE_LANGUAGES,
    SUPPORTED_EXTENSIONS,
    TARGET_LANGUAGES,
    UI_BASE_SCALE,
)
from dependencies import DND_AVAILABLE, DND_FILES, TkinterDnD
from file_translator import FileTranslator
from job_manager import JobManager
from job_store import JobStore
from logging_config import logger
from paddle_ocr import PaddleTableOCR
from settings_dialog import SettingsDialog
from time_estimator import (
    Estimate,
    TimeEstimator,
    format_estimate_label,
    format_estimate_range,
    format_secs,
)
from translator_engine import LLMTranslator, TranslationCancelled


# ---------------------------------------------------------------------------
# 테마 팔레트 (Google Translate 스타일 + 다크모드)
# ---------------------------------------------------------------------------
LIGHT = {
    "BG": "#f5f5f5",
    "CARD": "#ffffff",
    "TOP_BAR": "#4285f4",
    "TOP_BAR_FG": "#ffffff",
    "PRIMARY": "#4285f4",
    "PRIMARY_DARK": "#3367d6",
    "PRIMARY_LIGHT": "#d2e3fc",
    "TEXT": "#202124",
    "TEXT_SEC": "#5f6368",
    "TEXT_HINT": "#9aa0a6",
    "BORDER": "#dadce0",
    "DIVIDER": "#e8eaed",
    "SUCCESS": "#0d904f",
    "WARNING": "#f9ab00",
    "ERROR": "#d93025",
    "LOG_BG": "#f8f9fa",
}

DARK = {
    "BG": "#202124",
    "CARD": "#2d2e31",
    "TOP_BAR": "#1a73e8",
    "TOP_BAR_FG": "#ffffff",
    "PRIMARY": "#8ab4f8",
    "PRIMARY_DARK": "#669df6",
    "PRIMARY_LIGHT": "#1e3a5f",
    "TEXT": "#e8eaed",
    "TEXT_SEC": "#bdc1c6",
    "TEXT_HINT": "#9aa0a6",
    "BORDER": "#3c4043",
    "DIVIDER": "#3c4043",
    "SUCCESS": "#81c995",
    "WARNING": "#fdd663",
    "ERROR": "#f28b82",
    "LOG_BG": "#28292c",
}


# 파일 상태
STATUS_PENDING = "대기"
STATUS_RUNNING = "진행 중"
STATUS_OCR_DONE = "OCR완료"
STATUS_DONE = "완료"
STATUS_FAILED = "실패"
STATUS_CANCELLED = "취소됨"

STATUS_COLORS = {
    STATUS_PENDING: ("#e8eaed", "#5f6368"),
    STATUS_RUNNING: ("#d2e3fc", "#1967d2"),
    STATUS_OCR_DONE: ("#fef7e0", "#b06000"),
    STATUS_DONE: ("#ceead6", "#0d904f"),
    STATUS_FAILED: ("#fad2cf", "#c5221f"),
    STATUS_CANCELLED: ("#fef7e0", "#b06000"),
}

# JobManager 상태(JobStatus) → UI 파일 상태 매핑
_JOB_STATUS_DISPLAY = {
    JobStatus.QUEUED: STATUS_PENDING,
    JobStatus.OCR_RUNNING: STATUS_RUNNING,
    JobStatus.OCR_DONE: STATUS_OCR_DONE,
    JobStatus.TRANS_QUEUED: STATUS_RUNNING,
    JobStatus.TRANSLATING: STATUS_RUNNING,
    JobStatus.DONE: STATUS_DONE,
    JobStatus.FAILED: STATUS_FAILED,
}


class TranslatorApp:
    """LLM Translator v3 — Google Translate inspired, extended UX."""

    STEPS = ["파일 선택", "텍스트 추출", "번역 중", "완료"]

    def __init__(self) -> None:
        if DND_AVAILABLE and TkinterDnD is not None:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        # Windows DPI awareness: blurry/잘린 화면 완화
        self._enable_dpi_awareness()

        self.config = ConfigManager()
        self.palette = LIGHT if self.config.get("ui_theme") != "dark" else DARK
        self._font_scale = self.config.get_float("font_scale", 1.0)
        # 적응형 스케일링용: 현재 적용된 폰트 스케일과 리사이즈 디바운스 핸들 ID
        self._current_scale = UI_BASE_SCALE * self._font_scale
        # 픽셀 단위 위젯(top bar, 카드 높이 등) 산정용 — 시작 시점에 한 번만 잡는다
        self._ui_scale = self._current_scale
        self._resize_after_id: Optional[str] = None

        self.root.title(APP_TITLE)
        self._apply_responsive_geometry()
        self._init_fonts()
        self.root.configure(bg=self.palette["BG"])

        if not self.config.is_configured():
            self.root.update()
            dlg = SettingsDialog(self.root, self.config, first_run=True)
            if not dlg.wait():
                self.root.destroy()
                sys.exit(0)
            # 첫 실행에서 설정 저장 후 테마 다시 반영
            self.palette = LIGHT if self.config.get("ui_theme") != "dark" else DARK
            self.root.configure(bg=self.palette["BG"])

        # 번역 엔진 + 취소 이벤트
        self._cancel_event = threading.Event()
        self.translator = LLMTranslator(self.config, cancel_event=self._cancel_event)
        self.file_translator = FileTranslator(self.translator)
        self.time_estimator = TimeEstimator(self.config)

        # 상태
        self.selected_files: list[str] = []
        self.file_rows: dict[str, dict] = {}  # path -> {frame, status_var, status_lbl}
        self.file_status: dict[str, str] = {}
        self.file_estimates: dict[str, Estimate] = {}  # path -> Estimate (None=추정중)
        self.is_translating = False
        self._current_step = 0
        self._results_output_dir: Optional[str] = None
        self.mode_var = tk.StringVar(
            value=self.config.get("translation_mode") or "deep"
        )
        # OCR 산출 방식: full(OCR+번역) / ocr_only(OCR만 먼저)
        self.ocr_output_mode = tk.StringVar(value=MODE_FULL)

        # ---- OCR/번역 작업 큐 (PDF·이미지는 JobManager 경유) ----
        # path↔job 매핑과 완료 신호용 이벤트. _run_translation 스레드가 OCR 작업
        # 완료를 기다릴 때 사용한다(완료는 워커 스레드 → _on_job_change 로 통지).
        self._job_by_path: dict[str, str] = {}   # source path -> job id
        self._job_events: dict[str, threading.Event] = {}  # job id -> 완료 신호
        self._job_store = JobStore(Path(JOBS_INDEX_PATH).expanduser())
        self._ocr_engine = PaddleTableOCR(model_root=self.config.paddleocr_model_root())
        self.jobs = JobManager(self._job_store, self.translator, self._ocr_engine,
                               on_change=self._on_job_change)
        self.jobs.start()

        self._build_ui()
        self._bind_shortcuts()
        if DND_AVAILABLE:
            self._enable_drag_drop()

        # 종료 시 워커 정리
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 재시작 후 이전 작업 목록 복원
        self._restore_jobs()

    # -------- DPI / geometry 헬퍼 ----------------------------------------
    @staticmethod
    def _enable_dpi_awareness() -> None:
        """Windows에서 Per-Monitor DPI 인식 활성화. 실패해도 치명적 아님."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            # SetProcessDpiAwareness(2) == PER_MONITOR_DPI_AWARE
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                ctypes.windll.user32.SetProcessDPIAware()
        except (OSError, AttributeError) as e:
            # DPI 인식 설정 실패는 비치명적(구형 Windows 등) — 기록만 한다.
            logger.debug(f"DPI-AWARE: 설정 실패 ({type(e).__name__})")

    def _apply_responsive_geometry(self) -> None:
        """현재 화면 크기의 약 85% 로 자동 조정. 작은 화면에서도 잘리지 않게."""
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except tk.TclError:
            sw, sh = 1366, 768

        # 화면 크기에 비례한 초기 윈도우. 상하한만 잡아서 과하게 커지지 않도록.
        prefer_w = max(960, min(int(sw * 0.78), int(1120 * self._ui_scale)))
        prefer_h = max(680, min(int(sh * 0.82), int(820 * self._ui_scale)))
        width = min(prefer_w, int(sw * 0.95))
        height = min(prefer_h, int(sh * 0.92))

        # 중앙 정렬
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # 최소 크기: 절대 최소값 — 작게 줄여도 동작 (사용자가 자유롭게 리사이즈)
        self.root.minsize(720, 520)
        # 명시적으로 가변 크기 활성화
        self.root.resizable(True, True)

        # Tk 스케일링: DPI 기반 보정만 적용. UI 스케일은 명명 폰트로 처리.
        try:
            dpi = self.root.winfo_fpixels("1i")  # px per inch
            dpi_scale = max(0.85, min(1.5, dpi / 96.0))
            self.root.tk.call("tk", "scaling", dpi_scale)
        except tk.TclError:
            # 일부 환경에서 tk scaling 미지원 — 기본 스케일로 진행한다.
            logger.debug("DPI-SCALE: tk scaling 적용 실패")

    # ===================================================================
    # 적응형 폰트 시스템
    # ===================================================================
    # 적응형 스케일 클램프 범위 (지나치게 작거나 크지 않도록)
    _SCALE_MIN = 0.85
    _SCALE_MAX = 2.4

    # 명명 폰트 사양: key → (family, base_size, weight)
    # base_size 는 "디자인 기준 크기"이며, 적응형 스케일이 곱해져 실제 크기가 된다.
    _FONT_SPECS: dict = {
        "xs":     ("Segoe UI", 7,  "normal"),
        "xs_b":   ("Segoe UI", 7,  "bold"),
        "sm":     ("Segoe UI", 8,  "normal"),
        "sm_b":   ("Segoe UI", 8,  "bold"),
        "base":   ("Segoe UI", 9,  "normal"),
        "base_b": ("Segoe UI", 9,  "bold"),
        "md":     ("Segoe UI", 10, "normal"),
        "md_b":   ("Segoe UI", 10, "bold"),
        "lg":     ("Segoe UI", 11, "normal"),
        "lg_b":   ("Segoe UI", 11, "bold"),
        "xl":     ("Segoe UI", 14, "bold"),
        "icon":   ("Segoe UI", 16, "normal"),
        "mono":   ("Consolas", 8,  "normal"),
    }

    def _calc_adaptive_scale(self, window_width: int) -> float:
        """창 너비에 비례한 폰트 스케일.

        REF 너비(=시작 시점의 창 너비) 일 때 정확히 UI_BASE_SCALE × font_scale.
        창을 키우면 비례해서 폰트도 커지고, 줄이면 작아진다 (클램프 적용).
        """
        ref = getattr(self, "_scale_ref_width", 1120)
        if window_width < 200:
            window_width = ref
        ratio = window_width / ref
        raw = UI_BASE_SCALE * self._font_scale * ratio
        return max(self._SCALE_MIN, min(self._SCALE_MAX, raw))

    def _init_fonts(self) -> None:
        """tk.font.Font 객체를 생성. 시작 시점의 창 너비를 REF 로 잡아 기본 = 1.8x."""
        try:
            init_w = self.root.winfo_width()
            if init_w < 200:
                init_w = int(self.root.geometry().split("x", 1)[0])
        except (tk.TclError, ValueError, IndexError):
            init_w = 1120
        # REF 를 시작 너비로 설정 → 디스플레이 해상도와 무관하게
        # 시작 시점에 항상 동일한 1.8x 비율을 보장
        self._scale_ref_width = max(800, init_w)
        self._current_scale = self._calc_adaptive_scale(init_w)

        self.fonts: dict[str, tkfont.Font] = {}
        for key, (family, size, weight) in self._FONT_SPECS.items():
            self.fonts[key] = tkfont.Font(
                name=f"app_{key}",
                family=family,
                size=max(7, int(size * self._current_scale)),
                weight=weight,
            )

    def _apply_adaptive_scale(self) -> None:
        """현재 창 너비를 읽어 모든 명명 폰트의 사이즈를 갱신."""
        try:
            w = self.root.winfo_width()
        except tk.TclError:
            return
        if w < 200:
            return
        new_scale = self._calc_adaptive_scale(w)
        # 변동폭이 너무 작으면 갱신 생략 (불필요한 리렌더 방지)
        if abs(new_scale - self._current_scale) < 0.02:
            return
        self._current_scale = new_scale
        for key, (_family, base_size, _weight) in self._FONT_SPECS.items():
            self.fonts[key].configure(size=max(7, int(base_size * new_scale)))

    def _on_root_configure(self, event) -> None:
        """root <Configure> 이벤트: 디바운스 후 적응형 스케일 적용."""
        if event.widget is not self.root:
            return
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except (tk.TclError, ValueError):
                # 이미 취소/실행된 after 콜백 — 무시 가능하나 추적을 위해 기록한다.
                logger.debug("RESIZE: after_cancel 무시 가능한 예외")
        self._resize_after_id = self.root.after(120, self._apply_adaptive_scale)

    # ===================================================================
    # UI 구성
    # ===================================================================
    def _build_ui(self) -> None:
        p = self.palette
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", font=self.fonts["lg"])
        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor=p["DIVIDER"],
            background=p["PRIMARY"],
            thickness=max(6, int(6 * self._ui_scale)),
        )
        style.configure(
            "File.Horizontal.TProgressbar",
            troughcolor=p["DIVIDER"],
            background=p["SUCCESS"],
            thickness=max(3, int(3 * self._ui_scale)),
        )

        # ttk.Combobox 펼침 리스트(Listbox)는 별도 위젯이라 옵션 DB에 명시 등록 필요.
        # 명명 폰트(self.fonts["lg"])를 참조하므로 적응형 리사이즈에 자동 반영된다.
        self.root.option_add("*TCombobox*Listbox.font", self.fonts["lg"])

        self._build_top_bar()
        self._build_language_bar()
        self._build_mode_bar()

        # 하단(상태바)을 먼저 packing하여 항상 최하단 고정
        self._build_status_bar()

        # 하단 컨트롤(스텝/진행/액션/로그) — 아래에서부터 쌓기
        bottom = tk.Frame(self.root, bg=p["BG"], padx=20, pady=0)
        bottom.pack(side="bottom", fill="x")
        self._build_step_bar(bottom)
        self._build_progress_bar(bottom)
        self._build_action_row(bottom)
        self._build_log_section(bottom)

        # body: 나머지 수직 공간. 원문/번역 패널이 필요에 따라 수축
        body = tk.Frame(self.root, bg=p["BG"], padx=20, pady=0)
        body.pack(side="top", fill=tk.BOTH, expand=True)

        self._build_file_bar(body)
        self._build_file_list(body)

        panels = tk.Frame(body, bg=p["BG"])
        panels.pack(fill=tk.BOTH, expand=True, pady=(8, 4))
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)
        panels.rowconfigure(0, weight=1)

        self._build_source_panel(panels)
        self._build_translated_panel(panels)

    # -- Top Bar ----------------------------------------------------------
    def _build_top_bar(self) -> None:
        p = self.palette
        bar = tk.Frame(self.root, bg=p["TOP_BAR"], height=int(52 * self._ui_scale))
        bar.pack(fill="x")
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg=p["TOP_BAR"], padx=20)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text=APP_NAME, font=self.fonts["xl"],
                 fg=p["TOP_BAR_FG"], bg=p["TOP_BAR"]).pack(side="left", pady=8)
        tk.Label(inner, text=f"v{APP_VERSION}  ·  Powered by FabriX Agent",
                 font=self.fonts["base"], fg="#b3cefb", bg=p["TOP_BAR"]).pack(
            side="left", padx=(10, 0), pady=8)

        right = tk.Frame(inner, bg=p["TOP_BAR"])
        right.pack(side="right", pady=8)

        tk.Label(right, text="PI Team & AX Dev Group",
                 font=self.fonts["base"], fg="#d2e3fc", bg=p["TOP_BAR"]).pack(
            side="left", padx=(0, 12))

        for label, cmd in (("⚙ 설정 (F1)", self._open_settings),
                           ("🌓 테마", self._toggle_theme)):
            tk.Button(right, text=label, font=self.fonts["base"],
                      bg="#5a9bf6", fg=p["TOP_BAR_FG"],
                      activebackground=p["PRIMARY_DARK"],
                      activeforeground=p["TOP_BAR_FG"],
                      relief="flat", bd=0, cursor="hand2",
                      padx=12, pady=2, command=cmd).pack(side="left", padx=(4, 0))

    # -- Language Bar -----------------------------------------------------
    def _build_language_bar(self) -> None:
        p = self.palette
        bar = tk.Frame(self.root, bg=p["CARD"])
        bar.pack(fill="x", padx=20, pady=(10, 0))
        tk.Frame(self.root, bg=p["BORDER"], height=1).pack(fill="x", padx=20)

        inner = tk.Frame(bar, bg=p["CARD"], pady=8)
        inner.pack(fill="x")
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=0)
        inner.columnconfigure(2, weight=1)

        # \uc800\uc7a5\ub41c \uc5b8\uc5b4 \uc120\ud0dd\uac12 \ubcf5\uc6d0. \uc0ac\ub77c\uc9c4/\uc624\ud0c0 \ud0a4\ub294 \uae30\ubcf8\uac12\uc73c\ub85c \ud3f4\ubc31.
        saved_src = self.config.get("source_lang")
        saved_tgt = self.config.get("target_lang")
        init_src = saved_src if saved_src in SOURCE_LANGUAGES else DEFAULT_SRC
        init_tgt = saved_tgt if saved_tgt in TARGET_LANGUAGES else DEFAULT_TGT

        src_f = tk.Frame(inner, bg=p["CARD"])
        src_f.grid(row=0, column=0, sticky="w", padx=(20, 0))
        tk.Label(src_f, text="Source", font=self.fonts["sm"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(anchor="w")
        self.src_lang_var = tk.StringVar(value=init_src)
        src_combo = ttk.Combobox(src_f, textvariable=self.src_lang_var,
                                 values=list(SOURCE_LANGUAGES.keys()),
                                 state="readonly", width=18,
                                 font=self.fonts["lg"])
        src_combo.pack(anchor="w", pady=(2, 0))
        src_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)

        tk.Button(inner, text="\u21c4", font=self.fonts["icon"],
                  bg=p["CARD"], fg=p["PRIMARY"],
                  activebackground=p["PRIMARY_LIGHT"],
                  relief="flat", bd=0, cursor="hand2", padx=8,
                  command=self._swap_languages).grid(row=0, column=1, padx=20)

        tgt_f = tk.Frame(inner, bg=p["CARD"])
        tgt_f.grid(row=0, column=2, sticky="w")
        tk.Label(tgt_f, text="Target", font=self.fonts["sm"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(anchor="w")
        self.tgt_lang_var = tk.StringVar(value=init_tgt)
        tgt_combo = ttk.Combobox(tgt_f, textvariable=self.tgt_lang_var,
                                 values=list(TARGET_LANGUAGES.keys()),
                                 state="readonly", width=18,
                                 font=self.fonts["lg"])
        tgt_combo.pack(anchor="w", pady=(2, 0))
        tgt_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)

        # \uc2dc\uc791 \uc2dc\uc810 translator \uc5d4\uc9c4\uc5d0 \ubcf5\uc6d0\ub41c \uc5b8\uc5b4 \uc989\uc2dc \ubc18\uc601 (\uc800\uc7a5\uc740 \ubcc0\uacbd \uc2dc\uc5d0\ub9cc)
        self.translator.set_languages(
            SOURCE_LANGUAGES.get(init_src, "Vietnamese"),
            TARGET_LANGUAGES.get(init_tgt, "Korean"),
        )
        self._ocr_engine.set_language(SOURCE_LANGUAGES.get(init_src, "Vietnamese"))

    # -- Mode Bar (빠른번역 / 심화번역) ----------------------------------
    def _build_mode_bar(self) -> None:
        p = self.palette
        bar = tk.Frame(self.root, bg=p["CARD"])
        bar.pack(fill="x", padx=20, pady=(6, 0))
        tk.Frame(self.root, bg=p["BORDER"], height=1).pack(fill="x", padx=20)

        inner = tk.Frame(bar, bg=p["CARD"], pady=8)
        inner.pack(fill="x", padx=20)

        tk.Label(inner, text="⚡ 번역 모드", font=self.fonts["lg_b"],
                 fg=p["TEXT"], bg=p["CARD"]).pack(side="left")

        # 카드 스타일 라디오 버튼 — 큰 클릭 영역 + 명확한 선택 표시
        self._mode_buttons: dict[str, tk.Radiobutton] = {}
        for value, label in (
            ("fast", "⚡  빠른번역  (RAG 미사용, 대용량 청크)"),
            ("deep", "🔍  심화번역  (RAG 사용, 정밀 번역)"),
        ):
            btn = tk.Radiobutton(
                inner, text=label,
                variable=self.mode_var, value=value,
                font=self.fonts["lg_b"], indicatoron=False,
                activebackground=p["PRIMARY_LIGHT"],
                activeforeground=p["PRIMARY"],
                selectcolor=p["PRIMARY_LIGHT"],
                relief="solid", bd=1,
                highlightthickness=0,
                padx=16, pady=8,
                cursor="hand2",
                command=self._on_mode_changed,
            )
            btn.pack(side="left", padx=(12, 0))
            self._mode_buttons[value] = btn

        # 변수 변경 시 fg/bg를 동기화 (선택/비선택 시각 차이를 명확히)
        self.mode_var.trace_add("write", lambda *_: self._refresh_mode_buttons())
        self._refresh_mode_buttons()

        self._mode_hint_var = tk.StringVar(value=self._mode_hint_text())
        tk.Label(inner, textvariable=self._mode_hint_var, font=self.fonts["sm"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(side="right")

        # PDF/이미지 OCR 산출 방식 (full=OCR+번역 / ocr_only=OCR만 먼저)
        ocr_box = tk.Frame(inner, bg=p["CARD"])
        ocr_box.pack(side="right", padx=(0, 16))
        tk.Label(ocr_box, text="📄 PDF/이미지:", font=self.fonts["sm_b"],
                 fg=p["TEXT_SEC"], bg=p["CARD"]).pack(side="left", padx=(0, 6))
        for value, label in (
            (MODE_FULL, "OCR+번역"),
            (MODE_OCR_ONLY, "OCR만"),
        ):
            tk.Radiobutton(
                ocr_box, text=label, variable=self.ocr_output_mode, value=value,
                font=self.fonts["sm"], indicatoron=False,
                activebackground=p["PRIMARY_LIGHT"], activeforeground=p["PRIMARY"],
                selectcolor=p["PRIMARY_LIGHT"], relief="solid", bd=1,
                highlightthickness=0, padx=8, pady=2, cursor="hand2",
                fg=p["TEXT_SEC"], bg=p["CARD"],
            ).pack(side="left", padx=(2, 0))

    def _refresh_mode_buttons(self) -> None:
        """라디오 버튼 색상을 현재 선택값에 맞춰 갱신."""
        p = self.palette
        selected = self.mode_var.get()
        for value, btn in getattr(self, "_mode_buttons", {}).items():
            if value == selected:
                btn.configure(fg=p["PRIMARY"], bg=p["PRIMARY_LIGHT"])
            else:
                btn.configure(fg=p["TEXT_SEC"], bg=p["CARD"])

    def _mode_hint_text(self) -> str:
        mode = self.mode_var.get()
        if mode == "fast":
            chunk = self.config.get("max_chunk_chars") or "8000"
            return f"현재: 빠른번역 · 청크 {chunk}"
        chunk = self.config.get("max_chunk_chars") or "5000"
        return f"현재: 심화번역 · 청크 {chunk}"

    def _on_mode_changed(self) -> None:
        if self.is_translating:
            messagebox.showinfo("안내", "번역 중에는 모드를 변경할 수 없습니다.")
            # 되돌리기
            self.mode_var.set(self.config.get("translation_mode") or "deep")
            return
        mode = self.mode_var.get()
        self.config.set("translation_mode", mode)
        try:
            self.config.save()
        except OSError as e:
            logger.error(f"CONFIG-SAVE: mode save 실패 {type(e).__name__}")
        self.translator.set_mode(mode)
        self._mode_hint_var.set(self._mode_hint_text())
        label = "빠른번역" if mode == "fast" else "심화번역"
        self._log(f"⚡ 번역 모드 변경: {label}", "info")
        # 모드 변경 → 청크 크기 달라짐 → 추정값 무효화 후 재계산
        if self.selected_files:
            self.file_estimates.clear()
            self._refresh_file_list()
            self._update_total_estimate()
            self._kick_off_estimation(list(self.selected_files))

    # -- File Bar ---------------------------------------------------------
    def _build_file_bar(self, parent) -> None:
        p = self.palette
        bar = tk.Frame(parent, bg=p["CARD"],
                       highlightbackground=p["BORDER"], highlightthickness=1)
        bar.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(bar, bg=p["CARD"], padx=14, pady=8)
        inner.pack(fill="x")

        tk.Label(inner, text="파일", font=self.fonts["md_b"],
                 fg=p["TEXT"], bg=p["CARD"]).pack(side="left")
        self.file_count = tk.StringVar(value="0")
        tk.Label(inner, textvariable=self.file_count, font=self.fonts["sm_b"],
                 fg=p["PRIMARY"], bg=p["PRIMARY_LIGHT"], padx=6, pady=1).pack(
            side="left", padx=(8, 0))

        hint = "드래그앤드롭 지원" if DND_AVAILABLE else "+ 버튼으로 파일 추가"
        tk.Label(inner, text=hint, font=self.fonts["base"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(side="left", padx=(12, 0))

        tk.Button(inner, text="🗑 전체 지우기", font=self.fonts["sm"],
                  fg=p["TEXT_SEC"], bg=p["CARD"],
                  activebackground=p["DIVIDER"], relief="flat", bd=0,
                  cursor="hand2", padx=6,
                  command=self._clear_files).pack(side="right", padx=(4, 0))

        self.btn_select = tk.Button(
            inner, text="+ 파일 추가 (Ctrl+O)", font=self.fonts["base_b"],
            fg=p["PRIMARY"], bg=p["PRIMARY_LIGHT"],
            activebackground="#b6d4fe", relief="flat", bd=0,
            cursor="hand2", padx=12, pady=2, command=self._select_files,
        )
        self.btn_select.pack(side="right")

        # 총 예상 시간 (선택된 파일들의 추정값 합계)
        self.total_estimate_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.total_estimate_var,
                 font=self.fonts["base_b"],
                 fg=p["PRIMARY"], bg=p["CARD"]).pack(side="right", padx=(8, 12))

    def _build_file_list(self, parent) -> None:
        p = self.palette
        self.file_list_card = tk.Frame(parent, bg=p["CARD"],
                                       highlightbackground=p["BORDER"],
                                       highlightthickness=1,
                                       height=int(110 * self._ui_scale))
        self.file_list_card.pack(fill="x", pady=(6, 0))
        self.file_list_card.pack_propagate(False)

        header = tk.Frame(self.file_list_card, bg=p["CARD"], padx=10, pady=4)
        header.pack(fill="x")
        tk.Label(header, text="선택된 파일 목록", font=self.fonts["sm_b"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(side="left")

        canvas = tk.Canvas(self.file_list_card, bg=p["CARD"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self.file_list_card, orient="vertical",
                                 command=canvas.yview, width=8)
        self.file_list_inner = tk.Frame(canvas, bg=p["CARD"])
        self.file_list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.file_list_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        scrollbar.pack(side="right", fill="y")

        self._empty_label = tk.Label(
            self.file_list_inner,
            text="   파일을 추가하거나 창으로 드래그 해주세요." if DND_AVAILABLE
                 else "   아직 선택된 파일이 없습니다. + 버튼으로 추가하세요.",
            font=self.fonts["base"], fg=p["TEXT_HINT"], bg=p["CARD"], anchor="w",
        )
        self._empty_label.pack(fill="x", pady=6)

    # -- Source / Translated Panels --------------------------------------
    def _build_panel(self, parent, side: str, title: str, placeholder: str) -> tuple:
        p = self.palette
        padx = (0, 5) if side == "left" else (5, 0)
        col = 0 if side == "left" else 1
        card = tk.Frame(parent, bg=p["CARD"],
                        highlightbackground=p["BORDER"], highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=padx)

        header = tk.Frame(card, bg=p["CARD"], padx=14, pady=8)
        header.pack(fill="x")
        tk.Label(header, text=title, font=self.fonts["md_b"],
                 fg=p["TEXT"], bg=p["CARD"]).pack(side="left")
        label_var = tk.StringVar(value="")
        tk.Label(header, textvariable=label_var, font=self.fonts["base"],
                 fg=p["TEXT_HINT"], bg=p["CARD"]).pack(side="left", padx=(8, 0))

        def _copy():
            widget.config(state="normal")
            text = widget.get("1.0", "end-1c")
            widget.config(state="disabled")
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self._log("📋 클립보드에 복사했습니다.", "info")

        tk.Button(header, text="📋 복사", font=self.fonts["sm"],
                  fg=p["TEXT_SEC"], bg=p["CARD"],
                  activebackground=p["DIVIDER"], relief="flat", bd=0,
                  cursor="hand2", command=_copy).pack(side="right")

        tk.Frame(card, bg=p["DIVIDER"], height=1).pack(fill="x")

        text_frame = tk.Frame(card, bg=p["CARD"])
        text_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(text_frame, width=8)
        scrollbar.pack(side="right", fill="y")

        widget = tk.Text(text_frame, font=self.fonts["md"],
                        bg=p["CARD"], fg=p["TEXT"],
                        relief="flat", wrap="word", padx=14, pady=10,
                        insertbackground=p["TEXT"],
                        selectbackground=p["PRIMARY_LIGHT"],
                        bd=0, highlightthickness=0, state="disabled",
                        yscrollcommand=scrollbar.set)
        widget.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=widget.yview)

        widget.tag_configure("filename", font=self.fonts["base_b"],
                            foreground=p["PRIMARY"] if side == "left" else p["SUCCESS"])
        widget.tag_configure("separator", foreground=p["DIVIDER"])

        ph = tk.Label(widget, text=placeholder, font=self.fonts["md"],
                      fg=p["TEXT_HINT"], bg=p["CARD"], justify="center")
        ph.place(relx=0.5, rely=0.5, anchor="center")
        return widget, label_var, ph

    def _build_source_panel(self, parent) -> None:
        self.source_text, self.src_label, self._source_placeholder = self._build_panel(
            parent, "left", "원문 텍스트",
            "파일 처리가 시작되면\n추출된 원문이 여기에 표시됩니다",
        )

    def _build_translated_panel(self, parent) -> None:
        self.translated_text, self.tgt_label, self._translated_placeholder = self._build_panel(
            parent, "right", "번역 결과",
            "번역이 완료되면\n결과가 여기에 표시됩니다",
        )

    # -- Step Bar ---------------------------------------------------------
    def _build_step_bar(self, parent) -> None:
        p = self.palette
        self.step_frame = tk.Frame(parent, bg=p["BG"])
        self.step_frame.pack(fill="x", pady=(0, 6))

        self.step_dots: list[tk.Canvas] = []
        self.step_labels: list[tk.Label] = []
        self.step_connectors: list[tk.Frame] = []

        dot_size = int(26 * self._ui_scale)
        for i, name in enumerate(self.STEPS):
            if i > 0:
                conn = tk.Frame(self.step_frame, bg=p["DIVIDER"], height=2)
                conn.pack(side="left", fill="x", expand=True,
                          pady=(0, int(14 * self._ui_scale)))
                self.step_connectors.append(conn)

            col = tk.Frame(self.step_frame, bg=p["BG"])
            col.pack(side="left")

            dot = tk.Canvas(col, width=dot_size, height=dot_size,
                            bg=p["BG"], highlightthickness=0)
            dot.pack()
            self.step_dots.append(dot)

            lbl = tk.Label(col, text=name, font=self.fonts["xs"],
                           fg=p["TEXT_HINT"], bg=p["BG"])
            lbl.pack(pady=(1, 0))
            self.step_labels.append(lbl)

        self._set_step(0)

    def _draw_dot(self, canvas, state: str, number: int) -> None:
        p = self.palette
        canvas.delete("all")
        s = self._ui_scale
        x0, y0 = int(2 * s), int(2 * s)
        x1, y1 = int(24 * s), int(24 * s)
        cx, cy = int(13 * s), int(13 * s)
        if state == "done":
            canvas.create_oval(x0, y0, x1, y1, fill=p["SUCCESS"], outline="")
            canvas.create_text(cx, cy, text="\u2713", fill="white",
                               font=self.fonts["lg_b"])
        elif state == "active":
            canvas.create_oval(x0, y0, x1, y1, fill=p["PRIMARY"], outline="")
            canvas.create_text(cx, cy, text=str(number), fill="white",
                               font=self.fonts["base_b"])
        else:
            canvas.create_oval(x0, y0, x1, y1, fill="", outline=p["BORDER"], width=2)
            canvas.create_text(cx, cy, text=str(number), fill=p["TEXT_HINT"],
                               font=self.fonts["base"])

    def _set_step(self, step_index: int) -> None:
        p = self.palette
        self._current_step = step_index
        for i, (dot, lbl) in enumerate(zip(self.step_dots, self.step_labels)):
            if i < step_index:
                self._draw_dot(dot, "done", i + 1)
                lbl.config(fg=p["SUCCESS"])
            elif i == step_index:
                self._draw_dot(dot, "active", i + 1)
                lbl.config(fg=p["PRIMARY"])
            else:
                self._draw_dot(dot, "inactive", i + 1)
                lbl.config(fg=p["TEXT_HINT"])
        for i, conn in enumerate(self.step_connectors):
            conn.config(bg=p["SUCCESS"] if i < step_index else p["DIVIDER"])

    # -- Progress Bar -----------------------------------------------------
    def _build_progress_bar(self, parent) -> None:
        p = self.palette
        prog = tk.Frame(parent, bg=p["BG"])
        prog.pack(fill="x", pady=(0, 6))

        top = tk.Frame(prog, bg=p["BG"])
        top.pack(fill="x")
        self.progress_text = tk.StringVar(value="준비됨")
        tk.Label(top, textvariable=self.progress_text, font=self.fonts["base"],
                 fg=p["TEXT_SEC"], bg=p["BG"]).pack(side="left")
        self.pct_label = tk.StringVar(value="")
        tk.Label(top, textvariable=self.pct_label, font=self.fonts["base_b"],
                 fg=p["PRIMARY"], bg=p["BG"]).pack(side="right")

        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(prog, variable=self.progress_var, maximum=100,
                        style="Blue.Horizontal.TProgressbar").pack(fill="x", pady=(3, 0))

        # 현재 파일 내부 진행률
        self.file_progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(prog, variable=self.file_progress_var, maximum=100,
                        style="File.Horizontal.TProgressbar").pack(fill="x", pady=(2, 0))

        self.progress_detail = tk.StringVar(value="")
        tk.Label(prog, textvariable=self.progress_detail, font=self.fonts["sm"],
                 fg=p["TEXT_HINT"], bg=p["BG"], anchor="w").pack(fill="x", pady=(2, 0))

    # -- Action Row -------------------------------------------------------
    def _build_action_row(self, parent) -> None:
        p = self.palette
        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", pady=(0, 6))

        self.btn_translate = tk.Button(
            row, text="▶  번역 시작 (Ctrl+Enter)", font=self.fonts["lg_b"],
            bg=p["PRIMARY"], fg=p["TOP_BAR_FG"],
            activebackground=p["PRIMARY_DARK"],
            activeforeground=p["TOP_BAR_FG"], relief="flat", cursor="hand2",
            bd=0, pady=8, command=self._start_translation,
        )
        self.btn_translate.pack(side="left", fill="x", expand=True)
        self.btn_translate.bind("<Enter>", lambda e: self.btn_translate.config(bg=p["PRIMARY_DARK"]))
        self.btn_translate.bind("<Leave>", lambda e: self.btn_translate.config(bg=p["PRIMARY"]))

        self.btn_cancel = tk.Button(
            row, text="■ 취소", font=self.fonts["md_b"],
            bg=p["CARD"], fg=p["ERROR"], activebackground=p["DIVIDER"],
            relief="flat", cursor="hand2", bd=0, padx=16, pady=8,
            state="disabled", command=self._cancel_translation,
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

        self.btn_retry = tk.Button(
            row, text="↻ 실패 재시도", font=self.fonts["md"],
            bg=p["CARD"], fg=p["TEXT_SEC"], activebackground=p["DIVIDER"],
            relief="flat", cursor="hand2", bd=0, padx=12, pady=8,
            state="disabled", command=self._retry_failed,
        )
        self.btn_retry.pack(side="left", padx=(4, 0))

        self.btn_open_result = tk.Button(
            row, text="📂 결과 폴더", font=self.fonts["md"],
            bg=p["CARD"], fg=p["TEXT_SEC"], activebackground=p["DIVIDER"],
            relief="flat", cursor="hand2", bd=0, padx=12, pady=8,
            state="disabled", command=self._open_result_folder,
        )
        self.btn_open_result.pack(side="left", padx=(4, 0))

    # -- Log Section ------------------------------------------------------
    def _build_log_section(self, parent) -> None:
        p = self.palette
        log_card = tk.Frame(parent, bg=p["LOG_BG"],
                            highlightbackground=p["BORDER"], highlightthickness=1)
        log_card.pack(fill="x")

        header = tk.Frame(log_card, bg=p["LOG_BG"], padx=10, pady=4)
        header.pack(fill="x")
        tk.Label(header, text="로그", font=self.fonts["sm_b"],
                 fg=p["TEXT_HINT"], bg=p["LOG_BG"]).pack(side="left")
        tk.Button(header, text="지우기", font=self.fonts["sm"],
                  fg=p["TEXT_HINT"], bg=p["LOG_BG"],
                  activebackground=p["DIVIDER"], relief="flat", bd=0,
                  cursor="hand2", command=self._clear_log).pack(side="right")

        self.log_text = tk.Text(log_card, height=3, font=self.fonts["mono"],
                                bg=p["LOG_BG"], fg=p["TEXT_SEC"],
                                relief="flat", wrap="word", padx=10, pady=2,
                                bd=0, highlightthickness=0)
        self.log_text.pack(fill="x")
        self.log_text.tag_configure("success", foreground=p["SUCCESS"])
        self.log_text.tag_configure("error", foreground=p["ERROR"])
        self.log_text.tag_configure("info", foreground=p["PRIMARY"])
        self.log_text.tag_configure("warn", foreground=p["WARNING"])
        self.log_text.tag_configure("dim", foreground=p["TEXT_HINT"])

    # -- Status Bar -------------------------------------------------------
    def _build_status_bar(self) -> None:
        p = self.palette
        bar = tk.Frame(self.root, bg=p["CARD"],
                       highlightbackground=p["BORDER"], highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value=self._default_status())
        tk.Label(bar, textvariable=self.status_var, font=self.fonts["sm"],
                 fg=p["TEXT_HINT"], bg=p["CARD"], anchor="w",
                 padx=14, pady=3).pack(fill="x")

    def _default_status(self) -> str:
        dnd = "드래그앤드롭 ✓" if DND_AVAILABLE else "드래그앤드롭 ✗"
        return f"{APP_NAME} v{APP_VERSION}  |  Samsung C&T PI Team & AX Dev Group  |  {dnd}"

    # ===================================================================
    # 이벤트 / 단축키
    # ===================================================================
    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda e: self._select_files())
        self.root.bind("<Control-O>", lambda e: self._select_files())
        self.root.bind("<Control-Return>", lambda e: self._start_translation())
        self.root.bind("<F1>", lambda e: self._open_settings())
        self.root.bind("<Control-l>", lambda e: self._clear_log())
        self.root.bind("<Escape>", lambda e: self._cancel_translation())
        # 창 리사이즈 시 폰트 적응형 갱신 (디바운스)
        self.root.bind("<Configure>", self._on_root_configure)

    def _enable_drag_drop(self) -> None:
        if not DND_AVAILABLE or DND_FILES is None:
            return
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, AttributeError, RuntimeError) as e:
            logger.error(f"DND-INIT: {type(e).__name__}")

    def _on_drop(self, event) -> None:
        raw = event.data or ""
        # tkinterdnd2 파일 경로 파싱 (공백 포함 경로는 중괄호로 감싸짐)
        import re
        paths = re.findall(r"\{([^}]+)\}|(\S+)", raw)
        flat = [a or b for a, b in paths]
        added: list[str] = []
        for f in flat:
            if os.path.isfile(f) and Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                if f not in self.selected_files:
                    self.selected_files.append(f)
                    added.append(f)
        if added:
            self._refresh_file_list()
            self._log(f"{len(added)}개 파일 추가됨 (드래그앤드롭)", "info")
            self._set_step(0)
            self._kick_off_estimation(added)

    # ===================================================================
    # 텍스트 패널 헬퍼
    # ===================================================================
    def _append_source(self, text: str, tag: Optional[str] = None) -> None:
        self._source_placeholder.place_forget()
        self.source_text.config(state="normal")
        if tag:
            self.source_text.insert(tk.END, text, tag)
        else:
            self.source_text.insert(tk.END, text)
        self.source_text.see(tk.END)
        self.source_text.config(state="disabled")

    def _append_translated(self, text: str, tag: Optional[str] = None) -> None:
        self._translated_placeholder.place_forget()
        self.translated_text.config(state="normal")
        if tag:
            self.translated_text.insert(tk.END, text, tag)
        else:
            self.translated_text.insert(tk.END, text)
        self.translated_text.see(tk.END)
        self.translated_text.config(state="disabled")

    def _clear_panels(self) -> None:
        self.source_text.config(state="normal")
        self.source_text.delete("1.0", tk.END)
        self.source_text.config(state="disabled")
        self._source_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        self.translated_text.config(state="normal")
        self.translated_text.delete("1.0", tk.END)
        self.translated_text.config(state="disabled")
        self._translated_placeholder.place(relx=0.5, rely=0.5, anchor="center")

    # ===================================================================
    # Event Handlers
    # ===================================================================
    def _open_settings(self) -> None:
        if self.is_translating:
            messagebox.showinfo("안내", "번역 중에는 설정을 변경할 수 없습니다.")
            return
        dlg = SettingsDialog(self.root, self.config, first_run=False)
        if dlg.wait():
            self._log("설정이 업데이트되었습니다.", "info")
            # 엔진 재구성
            self._cancel_event.clear()
            self.translator = LLMTranslator(self.config, cancel_event=self._cancel_event)
            self.file_translator = FileTranslator(self.translator)
            # JobManager 의 번역기도 새 설정으로 교체
            self.jobs.translator = self.translator
            self.jobs.ft = FileTranslator(self.translator)
            self._ocr_engine = PaddleTableOCR(model_root=self.config.paddleocr_model_root())
            self.jobs.ocr_engine = self._ocr_engine
            # 엔진 재생성 후 현재 선택 언어 재반영 (없으면 기본값으로 리셋됨)
            self._on_lang_changed()
            # 테마/폰트 재적용이 필요하면 안내 (재시작 권장)
            new_theme = self.config.get("ui_theme")
            new_scale = self.config.get_float("font_scale", 1.0)
            if (self.palette is LIGHT and new_theme == "dark") or \
               (self.palette is DARK and new_theme != "dark") or \
               abs(new_scale - self._font_scale) > 0.01:
                messagebox.showinfo("안내", "테마/폰트 변경은 프로그램 재시작 후 완전히 반영됩니다.")

    def _toggle_theme(self) -> None:
        current = self.config.get("ui_theme") or "light"
        new_theme = "dark" if current == "light" else "light"
        self.config.set("ui_theme", new_theme)
        self.config.save()
        messagebox.showinfo("테마 변경됨",
                            f"테마를 {new_theme}로 변경했습니다.\n재시작 시 완전히 적용됩니다.")

    def _swap_languages(self) -> None:
        src = self.src_lang_var.get()
        tgt = self.tgt_lang_var.get()
        src_keys = {v: k for k, v in SOURCE_LANGUAGES.items()}
        tgt_keys = {v: k for k, v in TARGET_LANGUAGES.items()}
        tgt_lang = TARGET_LANGUAGES.get(tgt, "")
        src_lang = SOURCE_LANGUAGES.get(src, "")
        if tgt_lang in src_keys and src_lang in tgt_keys:
            self.src_lang_var.set(src_keys[tgt_lang])
            self.tgt_lang_var.set(tgt_keys[src_lang])
            self._on_lang_changed()

    def _on_lang_changed(self, event=None) -> None:
        src = self.src_lang_var.get()
        tgt = self.tgt_lang_var.get()
        self.translator.set_languages(
            SOURCE_LANGUAGES.get(src, "Vietnamese"),
            TARGET_LANGUAGES.get(tgt, "Korean"),
        )
        self._ocr_engine.set_language(SOURCE_LANGUAGES.get(src, "Vietnamese"))
        self.src_label.set(src)
        self.tgt_label.set(tgt)
        self._log(f"언어: {src} → {tgt}", "info")

        # 마지막 선택값을 저장 — 다음 실행 시 자동 복원
        prev_src = self.config.get("source_lang")
        prev_tgt = self.config.get("target_lang")
        if prev_src != src or prev_tgt != tgt:
            self.config.set("source_lang", src)
            self.config.set("target_lang", tgt)
            try:
                self.config.save()
            except OSError as e:
                logger.error(f"CONFIG-SAVE: language save 실패 {type(e).__name__}")

    def _select_files(self) -> None:
        if self.is_translating:
            return
        ext_list = " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS)
        files = filedialog.askopenfilenames(
            title="번역할 파일 선택",
            filetypes=[("지원 파일", ext_list), ("모든 파일", "*.*")],
        )
        added: list[str] = []
        for f in files or ():
            if f not in self.selected_files:
                self.selected_files.append(f)
                added.append(f)
        if added:
            self._refresh_file_list()
            self._log(f"{len(added)}개 파일 추가됨", "info")
            self._set_step(0)
            self._kick_off_estimation(added)

    def _clear_files(self) -> None:
        if self.is_translating:
            return
        self.selected_files.clear()
        self.file_status.clear()
        self.file_estimates.clear()
        self._refresh_file_list()
        self._update_total_estimate()
        self._set_step(0)
        self._clear_panels()
        self.btn_retry.configure(state="disabled")
        self.btn_open_result.configure(state="disabled")

    def _remove_file(self, filepath: str) -> None:
        if self.is_translating:
            return
        if filepath in self.selected_files:
            self.selected_files.remove(filepath)
        self.file_status.pop(filepath, None)
        self.file_estimates.pop(filepath, None)
        self._refresh_file_list()
        self._update_total_estimate()

    # -------- 시간 추정 (백그라운드) ------------------------------------
    def _kick_off_estimation(self, files: list[str]) -> None:
        """주어진 파일들을 백그라운드 스레드에서 추정. UI 는 root.after 로 갱신."""
        if not files:
            return
        threading.Thread(
            target=self._estimate_files_bg,
            args=(list(files),),
            daemon=True,
        ).start()

    def _estimate_files_bg(self, files: list[str]) -> None:
        mode = self.mode_var.get()
        chunk_size = getattr(self.translator, "MAX_CHUNK_CHARS", 5000)
        for fp in files:
            # 사용자가 추정 도중 파일을 제거했을 가능성 체크
            if fp not in self.selected_files:
                continue
            est = self.time_estimator.estimate(fp, mode, chunk_size)
            self.file_estimates[fp] = est
            self.root.after(0, self._on_estimate_done, fp)

    def _on_estimate_done(self, filepath: str) -> None:
        if filepath not in self.selected_files:
            return
        # 행을 통째로 다시 그리는 대신 전체 리프레시 (로직 단순화)
        self._refresh_file_list()
        self._update_total_estimate()

    def _update_total_estimate(self) -> None:
        if not hasattr(self, "total_estimate_var"):
            return
        # 완료된(에러 아닌) 추정값만 합산. 추정 중 파일 수도 같이 표기.
        total = 0.0
        pending = 0
        for fp in self.selected_files:
            est = self.file_estimates.get(fp)
            if est is None:
                pending += 1
                continue
            if est.error:
                continue
            total += est.est_seconds
        if total <= 0 and pending == 0:
            self.total_estimate_var.set("")
            return
        parts = []
        if total > 0:
            parts.append(f"⏱ 총 예상: ~{format_secs(total)}")
        if pending > 0:
            parts.append(f"({pending}개 추정중)")
        self.total_estimate_var.set("  ".join(parts))

    def _refresh_file_list(self) -> None:
        p = self.palette
        # 기존 위젯 제거
        for child in self.file_list_inner.winfo_children():
            child.destroy()

        self.file_count.set(str(len(self.selected_files)))

        if not self.selected_files:
            tk.Label(self.file_list_inner,
                     text="   파일을 추가하거나 창으로 드래그 해주세요." if DND_AVAILABLE
                          else "   아직 선택된 파일이 없습니다.",
                     font=self.fonts["base"], fg=p["TEXT_HINT"],
                     bg=p["CARD"], anchor="w").pack(fill="x", pady=6)
            return

        for fp in self.selected_files:
            self._build_file_row(fp)

    def _build_file_row(self, filepath: str) -> None:
        p = self.palette
        row = tk.Frame(self.file_list_inner, bg=p["CARD"])
        row.pack(fill="x", padx=6, pady=1)

        name = Path(filepath).name
        ext = Path(filepath).suffix.lower().lstrip(".")
        status = self.file_status.get(filepath, STATUS_PENDING)

        # 확장자 뱃지
        tk.Label(row, text=f" {ext.upper()} ", font=self.fonts["xs_b"],
                 fg=p["PRIMARY"], bg=p["PRIMARY_LIGHT"], padx=4).pack(side="left", padx=(2, 6))

        # 파일명
        tk.Label(row, text=name, font=self.fonts["base"],
                 fg=p["TEXT"], bg=p["CARD"], anchor="w").pack(side="left", fill="x", expand=True)

        # 상태 뱃지 (오른쪽 끝)
        bg, fg = STATUS_COLORS.get(status, STATUS_COLORS[STATUS_PENDING])
        tk.Label(row, text=f" {status} ", font=self.fonts["xs"],
                 fg=fg, bg=bg, padx=6).pack(side="right", padx=(4, 0))

        # 제거 버튼 (상태 뱃지 왼쪽)
        tk.Button(row, text="✕", font=self.fonts["sm"],
                  fg=p["TEXT_HINT"], bg=p["CARD"],
                  activebackground=p["DIVIDER"], relief="flat", bd=0,
                  cursor="hand2", padx=4,
                  command=lambda f=filepath: self._remove_file(f)).pack(side="right")

        # OCR만 완료된 작업에는 '번역 시작' 버튼 노출 (사용자가 원할 때 번역 큐 투입)
        if status == STATUS_OCR_DONE and filepath in self._job_by_path:
            tk.Button(row, text="▶ 번역", font=self.fonts["xs_b"],
                      fg=p["PRIMARY"], bg=p["PRIMARY_LIGHT"],
                      activebackground="#b6d4fe", relief="flat", bd=0,
                      cursor="hand2", padx=8,
                      command=lambda f=filepath: self._translate_ocr_job(f)).pack(
                side="right", padx=(4, 0))

        # 예상 시간 뱃지 (제거 버튼 왼쪽). 추정 결과에 따라 텍스트/색 다르게.
        est = self.file_estimates.get(filepath)
        if est is None:
            badge_text = "추정중…"
            badge_fg = p["TEXT_HINT"]
        elif est.error:
            badge_text = ""
            badge_fg = p["TEXT_HINT"]
        else:
            badge_text = format_estimate_label(est)
            # confidence 에 따라 색감 살짝 다르게
            badge_fg = p["TEXT_SEC"] if est.confidence == "high" else p["TEXT_HINT"]
        if badge_text:
            tk.Label(row, text=badge_text, font=self.fonts["xs"],
                     fg=badge_fg, bg=p["CARD"], padx=8).pack(side="right", padx=(4, 0))

    def _start_translation(self, files_override: Optional[list[str]] = None) -> None:
        if self.is_translating:
            return

        queue = files_override if files_override is not None else self.selected_files
        if not queue:
            messagebox.showwarning("파일 없음", "먼저 번역할 파일을 선택해 주세요.")
            return

        errors = self.config.validate()
        if errors:
            messagebox.showerror("설정 오류",
                                 "설정에 문제가 있습니다:\n\n" + "\n".join(f"· {e}" for e in errors))
            return

        src = self.src_lang_var.get()
        tgt = self.tgt_lang_var.get()
        if SOURCE_LANGUAGES.get(src) == TARGET_LANGUAGES.get(tgt):
            messagebox.showwarning("언어 오류", "원본 언어와 번역 언어가 동일합니다.")
            return

        self._on_lang_changed()
        self.is_translating = True
        self._cancel_event.clear()

        # 상태 초기화
        for fp in queue:
            self.file_status[fp] = STATUS_PENDING
        self._refresh_file_list()

        self.btn_translate.configure(state="disabled", bg="#93c5fd", cursor="arrow")
        self.btn_select.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_retry.configure(state="disabled")
        self.btn_open_result.configure(state="disabled")

        self._clear_log()
        self._clear_panels()

        threading.Thread(target=self._run_translation, args=(list(queue),),
                         daemon=True).start()

    def _cancel_translation(self) -> None:
        if not self.is_translating:
            return
        if messagebox.askyesno("취소 확인", "현재 번역을 취소하시겠습니까?"):
            self._cancel_event.set()
            self._log("⏹  취소 요청을 보냈습니다. 현재 파일이 끝나면 중단됩니다.", "warn")

    def _retry_failed(self) -> None:
        failed = [f for f, s in self.file_status.items() if s == STATUS_FAILED]
        if not failed:
            return
        self._start_translation(files_override=failed)

    def _open_result_folder(self) -> None:
        if not self._results_output_dir:
            return
        path = self._results_output_dir
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except (OSError, subprocess.SubprocessError) as e:
            self._log(f"폴더 열기 실패: {type(e).__name__}", "error")

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)

    # ===================================================================
    # 번역 실행 (백그라운드 스레드)
    # ===================================================================
    def _run_translation(self, queue: list[str]) -> None:
        total = len(queue)
        results = {"ok": 0, "fail": 0, "cancelled": 0, "outputs": []}

        for idx, fp in enumerate(queue):
            if self._cancel_event.is_set():
                self.file_status[fp] = STATUS_CANCELLED
                results["cancelled"] += 1
                continue

            name = Path(fp).name
            ext = Path(fp).suffix.lower()

            self.file_status[fp] = STATUS_RUNNING
            self.root.after(0, self._refresh_file_list)

            self._log(f"[{idx+1}/{total}] {name}", "info")
            self._update_progress(idx / total * 100, f"처리 중: {name}",
                                  f"{idx+1}/{total} 파일")
            self.root.after(0, lambda: self.file_progress_var.set(0))

            is_ocr = ext in IMAGE_EXTENSIONS or ext == ".pdf"
            self.root.after(0, lambda: self._set_step(1 if is_ocr else 2))

            if idx > 0:
                sep = f"\n{'─'*40}\n\n"
                self.root.after(0, lambda s=sep: self._append_source(s, "separator"))
                self.root.after(0, lambda s=sep: self._append_translated(s, "separator"))
            self.root.after(0, lambda n=name: self._append_source(f"[ {n} ]\n\n", "filename"))
            self.root.after(0, lambda n=name: self._append_translated(f"[ {n} ]\n\n", "filename"))

            def on_extract(text: str, _name=name) -> None:
                self.root.after(0, lambda t=text: self._append_source(t + "\n"))

            def on_translate(text: str, _name=name) -> None:
                self.root.after(0, lambda t=text: self._append_translated(t + "\n"))

            # PDF/이미지는 OCR(표 보존) → 작업 큐(JobManager) 경유로 처리한다.
            # 텍스트 문서(docx/txt/xlsx/pptx)만 기존 동기 경로로 직접 번역.
            if is_ocr:
                self._run_ocr_job(fp, idx, total, results)
                self.root.after(0, self._refresh_file_list)
                continue

            file_start = time.time()
            try:
                def cb(cur: int, tot: int, msg: str) -> None:
                    file_pct = (cur / max(tot, 1)) * 100
                    overall = (idx / total + cur / max(tot, 1) / total) * 100
                    self._update_progress(overall, name, msg)
                    self.root.after(0, lambda v=file_pct: self.file_progress_var.set(v))
                    if "OCR" in msg or "추출" in msg:
                        self.root.after(0, lambda: self._set_step(1))
                    elif "번역" in msg or "translat" in msg.lower() or "FabriX" in msg:
                        self.root.after(0, lambda: self._set_step(2))

                out = self.file_translator.translate_file(
                    fp, cb, on_extract=on_extract, on_translate=on_translate
                )
                results["ok"] += 1
                results["outputs"].append(out)
                self.file_status[fp] = STATUS_DONE
                # 실측 시간으로 모드별 평균 갱신 (OCR 시간은 별도 가중치이므로 제외)
                duration = time.time() - file_start
                est = self.file_estimates.get(fp)
                # CWE-476: dict.get() 이 None 을 반환할 수 있으므로 명시적으로 검사한다.
                if est is not None and est.chunks > 0 and duration > 0:
                    api_secs = max(0.0,
                                   duration - est.ocr_pages * self.time_estimator.OCR_PER_PAGE_S)
                    self.time_estimator.update_avg(
                        self.mode_var.get(), api_secs, est.chunks
                    )
                self._log(f"  ✓ 완료 → {Path(out).name} ({format_secs(duration)})",
                          "success")
            except TranslationCancelled:
                results["cancelled"] += 1
                self.file_status[fp] = STATUS_CANCELLED
                self._log("  ⏹ 취소됨", "warn")
            except FileNotFoundError:
                results["fail"] += 1
                self.file_status[fp] = STATUS_FAILED
                self._log("  ✗ 파일을 찾을 수 없음 (ERR-01)", "error")
            except PermissionError:
                results["fail"] += 1
                self.file_status[fp] = STATUS_FAILED
                self._log("  ✗ 권한 거부 (ERR-02)", "error")
            except (ConnectionError, TimeoutError):
                results["fail"] += 1
                self.file_status[fp] = STATUS_FAILED
                self._log("  ✗ 네트워크 오류 (ERR-03)", "error")
            except Exception as e:
                results["fail"] += 1
                self.file_status[fp] = STATUS_FAILED
                self._log(f"  ✗ {type(e).__name__}: {e}", "error")
                logger.error(f"UNEXPECTED: {traceback.format_exc()}")

            self.root.after(0, self._refresh_file_list)

            if self._cancel_event.is_set():
                # 남은 파일은 취소 상태 기록
                for remaining in queue[idx + 1:]:
                    if self.file_status.get(remaining) in (None, STATUS_PENDING):
                        self.file_status[remaining] = STATUS_CANCELLED
                        results["cancelled"] += 1
                self.root.after(0, self._refresh_file_list)
                break

        self.root.after(0, lambda: self._set_step(3))
        self._update_progress(100, "완료",
                              f"성공 {results['ok']}  |  실패 {results['fail']}  |  취소 {results['cancelled']}")
        self.root.after(0, lambda: self.file_progress_var.set(0))
        self._log(f"종료 | 성공 {results['ok']}  실패 {results['fail']}  취소 {results['cancelled']}",
                  "info")

        if results["outputs"]:
            self._results_output_dir = str(Path(results["outputs"][0]).parent)
            self.root.after(0, lambda: self.btn_open_result.configure(state="normal"))

        has_failed = any(s == STATUS_FAILED for s in self.file_status.values())
        if has_failed:
            self.root.after(0, lambda: self.btn_retry.configure(state="normal"))

        summary = (f"번역 완료!\n\n"
                   f"성공: {results['ok']}\n"
                   f"실패: {results['fail']}\n"
                   f"취소: {results['cancelled']}")
        if self._results_output_dir:
            summary += f"\n\n결과 폴더:\n  {self._results_output_dir}"
        self.root.after(0, lambda: messagebox.showinfo("완료", summary))

        if (self.config.get_bool("auto_open_result")
                and self._results_output_dir
                and results["ok"] > 0):
            self.root.after(100, self._open_result_folder)

        self.root.after(0, self._reset_ui)

    # ===================================================================
    # OCR/번역 작업 큐 (PDF·이미지) — JobManager 연동
    # ===================================================================
    def _run_ocr_job(self, fp: str, idx: int, total: int, results: dict) -> None:
        """PDF/이미지 1건을 JobManager 에 제출하고 완료까지 대기.

        OCR+번역(full) 이면 DONE 까지, OCR만(ocr_only) 이면 OCR_DONE 까지 기다린다.
        완료 통지는 워커 스레드 → _on_job_change → (메인스레드) _apply_job_change 가
        이벤트를 set 하므로, 여기서는 이벤트로 깨어나 중앙 색인의 상태를 재확인한다."""
        name = Path(fp).name
        mode = self.ocr_output_mode.get() or MODE_FULL
        ev = threading.Event()
        file_start = time.time()
        jid = self.jobs.submit(fp, mode)
        self._job_by_path[fp] = jid
        self._job_events[jid] = ev

        if mode == MODE_OCR_ONLY:
            terminal = {JobStatus.OCR_DONE, JobStatus.DONE, JobStatus.FAILED}
        else:
            terminal = {JobStatus.DONE, JobStatus.FAILED}

        try:
            while True:
                if self._cancel_event.is_set():
                    self.file_status[fp] = STATUS_CANCELLED
                    results["cancelled"] += 1
                    self._log("  ⏹ 취소됨 (현재 작업은 백그라운드에서 마무리됩니다)", "warn")
                    return
                job = self._job_store.get(jid)
                st = job.status if job else JobStatus.FAILED
                self._ocr_progress(idx, total, name, st)
                if st in terminal:
                    break
                ev.wait(0.3)
                ev.clear()
        finally:
            self._job_events.pop(jid, None)

        if st == JobStatus.DONE:
            results["ok"] += 1
            if job and job.result_docx:
                results["outputs"].append(job.result_docx)
            self.file_status[fp] = STATUS_DONE
            dur = time.time() - file_start
            out_name = Path(job.result_docx).name if job and job.result_docx else name
            self._log(f"  ✓ 완료 → {out_name} ({format_secs(dur)})", "success")
        elif st == JobStatus.OCR_DONE:
            results["ok"] += 1
            self.file_status[fp] = STATUS_OCR_DONE
            self._log("  ✓ OCR 완료 (번역 대기) — 목록의 '▶ 번역' 으로 번역 시작", "success")
        else:  # FAILED
            results["fail"] += 1
            self.file_status[fp] = STATUS_FAILED
            err = (job.error if job else "") or ""
            self._log(f"  ✗ OCR/번역 실패 ({err or 'ERR'})", "error")

    def _ocr_progress(self, idx: int, total: int, name: str, status: str) -> None:
        frac = {
            JobStatus.QUEUED: 0.05, JobStatus.OCR_RUNNING: 0.4,
            JobStatus.OCR_DONE: 0.6, JobStatus.TRANS_QUEUED: 0.65,
            JobStatus.TRANSLATING: 0.85, JobStatus.DONE: 1.0,
            JobStatus.FAILED: 1.0,
        }.get(status, 0.1)
        overall = (idx / total + frac / total) * 100
        self._update_progress(overall, name, f"OCR 작업: {status}")
        self.root.after(0, lambda v=frac * 100: self.file_progress_var.set(v))
        if status in (JobStatus.TRANSLATING, JobStatus.TRANS_QUEUED):
            self.root.after(0, lambda: self._set_step(2))
        else:
            self.root.after(0, lambda: self._set_step(1))

    def _on_job_change(self, job) -> None:
        """워커 스레드에서 호출 — tkinter 메인 스레드로 마샬링."""
        try:
            self.root.after(0, lambda j=job: self._apply_job_change(j))
        except RuntimeError:
            # 앱 종료 중 tk 가 소멸된 경우 — 무시
            pass

    def _apply_job_change(self, job) -> None:
        """(메인 스레드) 작업 상태 변화를 파일 행에 반영하고 대기 스레드를 깨운다."""
        ev = self._job_events.get(job.id)
        if ev is not None:
            ev.set()
        self._job_by_path.setdefault(job.source, job.id)
        if job.source in self.selected_files:
            self.file_status[job.source] = _JOB_STATUS_DISPLAY.get(
                job.status, STATUS_PENDING)
            self._refresh_file_list()
        if job.status == JobStatus.DONE and job.result_docx:
            self._results_output_dir = str(Path(job.result_docx).parent)
            try:
                self.btn_open_result.configure(state="normal")
            except tk.TclError:
                pass

    def _translate_ocr_job(self, fp: str) -> None:
        """OCR만 완료된 작업을 번역 큐에 투입(목록의 '▶ 번역' 버튼)."""
        jid = self._job_by_path.get(fp)
        if not jid:
            return
        self.jobs.request_translation(jid)
        self.file_status[fp] = STATUS_RUNNING
        self._refresh_file_list()
        self._log(f"▶ 번역 요청: {Path(fp).name}", "info")

    def _restore_jobs(self) -> None:
        """재시작 후 중앙 색인에서 이전 작업을 목록에 복원."""
        restored = 0
        for job in self._job_store.list():
            self._job_by_path.setdefault(job.source, job.id)
            if job.source in self.selected_files:
                continue
            if not os.path.isfile(job.source):
                continue
            self.selected_files.append(job.source)
            self.file_status[job.source] = _JOB_STATUS_DISPLAY.get(
                job.status, STATUS_PENDING)
            restored += 1
        if restored:
            self._refresh_file_list()
            self._log(f"이전 작업 {restored}건 복원됨", "info")

    def _on_close(self) -> None:
        """창 종료 — 진행 중 작업을 멈추고 워커 정리."""
        try:
            self._cancel_event.set()
            self.jobs.stop()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()

    def _update_progress(self, pct: float, text: str, detail: str = "") -> None:
        pct = min(pct, 100)
        self.root.after(0, lambda: self.progress_var.set(pct))
        self.root.after(0, lambda: self.progress_text.set(text))
        self.root.after(0, lambda: self.progress_detail.set(detail))
        self.root.after(0, lambda: self.pct_label.set(f"{int(pct)}%" if pct > 0 else ""))

    def _reset_ui(self) -> None:
        self.is_translating = False
        self.btn_translate.configure(state="normal",
                                     bg=self.palette["PRIMARY"], cursor="hand2")
        self.btn_select.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.status_var.set(
            f"{self._default_status()}  |  마지막 실행: "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )

    def _log(self, msg: str, tag: Optional[str] = None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.root.after(0, lambda: self._append_log(f"[{ts}] {msg}\n", tag))

    def _append_log(self, line: str, tag: Optional[str] = None) -> None:
        if tag:
            self.log_text.insert(tk.END, line, tag)
        else:
            self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    def run(self) -> None:
        self.root.mainloop()
