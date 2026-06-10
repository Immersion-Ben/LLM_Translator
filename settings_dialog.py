"""설정 입력 다이얼로그. v3: 탭 구조, 비밀번호 마스킹, 실시간 검증."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from config_manager import CONFIG_FILE, ConfigManager
from constants import UI_BASE_SCALE
from dependencies import pytesseract
from logging_config import logger
from security import validate_agent_id, validate_email, validate_endpoint_url


class SettingsDialog:
    """API 및 OCR / 고급 설정 다이얼로그."""

    # 적응형 폰트 시스템 — 다이얼로그 너비에 비례해 폰트 크기 조정.
    # BOOST 1.6: 메인 앱 대비 설정 다이얼로그 텍스트를 추가로 키운다.
    _FONT_BOOST = 1.6
    _SCALE_MIN = 0.9
    _SCALE_MAX = 3.2
    # base_size 는 디자인 기준값. 최종 = base_size × (현재 너비 / REF) × BOOST
    # 기본 오픈 시 BOOST(1.6) × 1.0 = 1.6x base 가 렌더링 사이즈.
    _FONT_SPECS: dict = {
        "header":  ("맑은 고딕", 19, "bold"),   # ~30pt
        "section": ("맑은 고딕", 15, "bold"),   # ~24pt — LabelFrame 헤더, 탭 안 섹션 제목
        "field":   ("맑은 고딕", 15, "normal"), # ~24pt — 필드 라벨 / 체크박스 / 콤보 / 버튼
        "hint":    ("맑은 고딕", 13, "normal"), # ~21pt — 보조 설명, 경고
        "input":   ("Consolas",  15, "normal"), # ~24pt — Entry 입력값
        "tab":     ("맑은 고딕", 15, "bold"),   # ~24pt — Notebook 탭 제목
    }

    def __init__(self, parent, config_manager: ConfigManager, first_run: bool = False) -> None:
        self.config = config_manager
        self.result = False
        self._first_run = first_run

        self.dialog = tk.Toplevel(parent)
        title_prefix = "초기 설정 — 최초 실행" if first_run else "설정"
        self.dialog.title(f"⚙ {title_prefix}")

        # 다이얼로그 기본 크기. 메인 앱 ui_scale × 1.4 정도면 큰 폰트가 들어간다.
        try:
            user_scale = float(config_manager.get("font_scale") or 1.0)
        except (TypeError, ValueError):
            user_scale = 1.0
        ui_scale = UI_BASE_SCALE * user_scale
        # 큰 base 폰트(15~19pt × BOOST 1.6) 가 들어갈 공간 확보
        dlg_boost = 1.65

        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        dlg_w = min(int(620 * ui_scale * dlg_boost), int(sw * 0.95))
        dlg_h = min(int(680 * ui_scale * dlg_boost), int(sh * 0.92))

        self.dialog.geometry(f"{dlg_w}x{dlg_h}")
        self.dialog.resizable(True, True)
        self.dialog.minsize(720, 560)
        self.dialog.configure(bg="#f0f4f8")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 적응형 스케일 초기 기준값 = 다이얼로그 오픈 폭. 이 폭일 때 BOOST(1.5)배 적용.
        self._scale_ref_width = max(800, dlg_w)
        self._current_scale = self._FONT_BOOST
        self._resize_after_id: Optional[str] = None
        self._init_fonts()

        self._entries: dict[str, tk.StringVar] = {}
        self._show_secret: dict[str, tk.BooleanVar] = {}
        self._build_ui(first_run)

        self.dialog.update_idletasks()
        x = max(0, (sw - dlg_w) // 2)
        y = max(0, (sh - dlg_h) // 2)
        self.dialog.geometry(f"+{x}+{y}")

        # 다이얼로그 리사이즈 시 폰트 적응형 갱신
        self.dialog.bind("<Configure>", self._on_dialog_configure)

        # ESC로 닫기 (첫 실행 제외)
        if not first_run:
            self.dialog.bind("<Escape>", lambda e: self.dialog.destroy())

    # ------------------------------------------------------------------
    # 적응형 폰트
    # ------------------------------------------------------------------
    def _calc_scale(self, width: int) -> float:
        if width < 200:
            width = self._scale_ref_width
        ratio = width / self._scale_ref_width
        raw = ratio * self._FONT_BOOST
        return max(self._SCALE_MIN, min(self._SCALE_MAX, raw))

    def _init_fonts(self) -> None:
        scale = self._calc_scale(self._scale_ref_width)
        self._current_scale = scale
        self.fonts: dict[str, tkfont.Font] = {}
        for key, (family, size, weight) in self._FONT_SPECS.items():
            # 명시적 name 미지정 → 다이얼로그 재오픈 시 충돌 없이 유니크하게 생성
            self.fonts[key] = tkfont.Font(
                family=family,
                size=max(8, int(size * scale)),
                weight=weight,
            )

    def _apply_adaptive(self) -> None:
        try:
            w = self.dialog.winfo_width()
        except tk.TclError:
            return
        if w < 200:
            return
        new_scale = self._calc_scale(w)
        if abs(new_scale - self._current_scale) < 0.02:
            return
        self._current_scale = new_scale
        for key, (_family, base_size, _weight) in self._FONT_SPECS.items():
            self.fonts[key].configure(size=max(8, int(base_size * new_scale)))

    def _on_dialog_configure(self, event) -> None:
        if event.widget is not self.dialog:
            return
        if self._resize_after_id is not None:
            try:
                self.dialog.after_cancel(self._resize_after_id)
            except (tk.TclError, ValueError):
                # 이미 취소/실행된 after 콜백 — 무시 가능하나 추적을 위해 기록한다.
                logger.debug("CFG-RESIZE: after_cancel 무시 가능한 예외")
        self._resize_after_id = self.dialog.after(120, self._apply_adaptive)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, first_run: bool) -> None:
        # ttk 위젯의 기본 폰트도 명명 폰트로 지정 — 다이얼로그 리사이즈 시 자동 적응.
        style = ttk.Style()
        style.configure("TButton", font=self.fonts["field"])
        style.configure("TLabel", font=self.fonts["field"])
        style.configure("TCheckbutton", font=self.fonts["field"])
        style.configure("TCombobox", font=self.fonts["field"])
        style.configure("TEntry", font=self.fonts["input"])
        style.configure("TNotebook.Tab",
                        font=self.fonts["tab"], padding=(14, 8))
        style.configure("TLabelframe.Label", font=self.fonts["section"])

        # ttk.Combobox 의 펼친 드롭다운(내부 Listbox)은 별도 옵션이라
        # 옵션 DB 에 명시적으로 등록해야 큰 폰트가 적용된다.
        self.dialog.option_add("*TCombobox*Listbox.font", self.fonts["field"])

        main = ttk.Frame(self.dialog, padding=18)
        main.pack(fill=tk.BOTH, expand=True)

        if first_run:
            header = "🔧 처음 실행입니다. API 정보를 입력해 주세요."
            sub = "입력한 정보는 로컬(~/.llm_translator/config.json)에 저장됩니다."
        else:
            header = "⚙ 설정 변경"
            sub = f"설정 파일: {CONFIG_FILE}"

        ttk.Label(main, text=header, font=self.fonts["header"],
                  background="#f0f4f8").pack(anchor="w")
        ttk.Label(main, text=sub, font=self.fonts["hint"],
                  background="#f0f4f8", foreground="#94a3b8").pack(anchor="w", pady=(0, 10))

        # 탭 노트북
        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True, pady=(0, 10))

        api_tab = ttk.Frame(notebook, padding=10)
        ocr_tab = ttk.Frame(notebook, padding=10)
        adv_tab = ttk.Frame(notebook, padding=10)
        notebook.add(api_tab, text="🔑 API")
        notebook.add(ocr_tab, text="🔍 OCR")
        notebook.add(adv_tab, text="⚙ 고급")

        self._build_api_tab(api_tab)
        self._build_ocr_tab(ocr_tab)
        self._build_advanced_tab(adv_tab)

        # 하단 버튼
        btn_row = ttk.Frame(main)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="💾 저장", command=self._save).pack(side="right", padx=(5, 0))
        if not first_run:
            ttk.Button(btn_row, text="취소", command=self.dialog.destroy).pack(side="right")

        ttk.Label(main,
                  text="💡 민감한 값은 파일 권한이 제한되어 저장됩니다 (POSIX: chmod 600).",
                  font=self.fonts["hint"], foreground="#64748b",
                  background="#f0f4f8").pack(anchor="w", pady=(6, 0))

    # -- API tab ---------------------------------------------------------
    def _build_api_tab(self, parent) -> None:
        ttk.Label(parent, text="Fabrix Agent API 접속 정보",
                  font=self.fonts["section"]).pack(anchor="w", pady=(0, 6))

        fields = [
            ("client_key", "Client Key", True),
            ("pass_key", "Pass Key (Bearer 포함)", True),
            ("endpoint_url", "Endpoint URL", False),
            ("agent_id", "Agent ID (심화번역)", False),
            ("agent_id_fast", "Agent ID (빠른번역, 선택)", False),
            ("email", "Email", False),
        ]

        for key, label, is_secret in fields:
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f"{label}:", font=self.fonts["field"],
                      width=26, anchor="w").pack(side="left")

            var = tk.StringVar(value=self.config.get(key))
            self._entries[key] = var

            entry = ttk.Entry(row, textvariable=var, font=self.fonts["input"])
            if is_secret:
                entry.configure(show="●")

            entry.pack(side="left", fill="x", expand=True)

            if is_secret:
                show_var = tk.BooleanVar(value=False)
                self._show_secret[key] = show_var

                def _toggle(e=entry, v=show_var):
                    e.configure(show="" if v.get() else "●")

                ttk.Checkbutton(row, text="표시", variable=show_var,
                                command=_toggle).pack(side="left", padx=(4, 0))

        ttk.Label(
            parent,
            text="💡 빠른번역 Agent ID는 선택입니다. 비워두면 심화번역 Agent ID로 자동 폴백됩니다.",
            font=self.fonts["hint"], foreground="#64748b",
        ).pack(anchor="w", pady=(8, 0))

    # -- OCR tab ---------------------------------------------------------
    def _build_ocr_tab(self, parent) -> None:
        ttk.Label(parent, text="Tesseract OCR 설정 (이미지/PDF OCR용)",
                  font=self.fonts["section"]).pack(anchor="w", pady=(0, 6))

        ttk.Label(parent,
                  text="Tesseract 실행 파일 경로 (예: C:\\Program Files\\Tesseract-OCR\\tesseract.exe)",
                  font=self.fonts["hint"], foreground="#64748b").pack(anchor="w", pady=(0, 5))

        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.tess_var = tk.StringVar(value=self.config.get("tesseract_path"))
        ttk.Entry(row, textvariable=self.tess_var, font=self.fonts["input"]).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="📂 찾기", command=self._browse_tesseract).pack(
            side="left", padx=(5, 0))

        if pytesseract is None:
            ttk.Label(parent,
                      text="⚠ pytesseract 패키지가 설치되지 않아 OCR 기능을 사용할 수 없습니다.",
                      font=self.fonts["hint"], foreground="#ef4444").pack(anchor="w", pady=(8, 0))

        ttk.Label(parent,
                  text="💡 실행 파일과 동일 폴더의 Tesseract-OCR/tesseract.exe 가 있으면 자동 감지됩니다.",
                  font=self.fonts["hint"], foreground="#64748b").pack(anchor="w", pady=(10, 0))

    # -- Advanced tab ----------------------------------------------------
    def _build_advanced_tab(self, parent) -> None:
        ttk.Label(parent, text="청크 / 네트워크 / UI",
                  font=self.fonts["section"]).pack(anchor="w", pady=(0, 6))

        # 청크 크기
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="최대 청크 크기 (글자):", font=self.fonts["field"],
                  width=22, anchor="w").pack(side="left")
        self.chunk_var = tk.StringVar(value=self.config.get("max_chunk_chars") or "")
        ttk.Entry(row, textvariable=self.chunk_var, font=self.fonts["input"], width=10).pack(side="left")
        ttk.Label(row, text="  (비우면 모드 기본값 적용: 빠른=8000, 심화=5000)",
                  font=self.fonts["hint"], foreground="#64748b").pack(side="left", padx=(5, 0))

        # 타임아웃
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="API 타임아웃 (초):", font=self.fonts["field"],
                  width=22, anchor="w").pack(side="left")
        self.timeout_var = tk.StringVar(value=self.config.get("timeout_seconds") or "120")
        ttk.Entry(row, textvariable=self.timeout_var, font=self.fonts["input"], width=10).pack(side="left")
        ttk.Label(row, text="  (5~600, 기본 120)", font=self.fonts["hint"],
                  foreground="#64748b").pack(side="left", padx=(5, 0))

        # SSL 정책
        ssl_frame = ttk.LabelFrame(parent, text="🔐 보안 — SSL 인증", padding=8)
        ssl_frame.pack(fill="x", pady=(10, 6))
        self.allow_insecure_var = tk.BooleanVar(value=self.config.get_bool("allow_insecure_ssl"))
        ttk.Checkbutton(
            ssl_frame,
            text="SSL 검증 실패 시 verify=False 폴백 허용 (권장하지 않음)",
            variable=self.allow_insecure_var,
        ).pack(anchor="w")
        ttk.Label(
            ssl_frame,
            text="회사 네트워크 SSL 인증서 문제로 접속이 안 될 때만 체크하세요.",
            font=self.fonts["hint"], foreground="#ef4444",
        ).pack(anchor="w", pady=(4, 0))

        # UI 옵션
        ui_frame = ttk.LabelFrame(parent, text="🎨 UI", padding=8)
        ui_frame.pack(fill="x", pady=(4, 0))

        row = ttk.Frame(ui_frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="테마:", font=self.fonts["field"],
                  width=18, anchor="w").pack(side="left")
        self.theme_var = tk.StringVar(value=self.config.get("ui_theme") or "light")
        ttk.Combobox(row, textvariable=self.theme_var, values=("light", "dark"),
                     state="readonly", width=10,
                     font=self.fonts["field"]).pack(side="left")

        row = ttk.Frame(ui_frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="폰트 배율:", font=self.fonts["field"],
                  width=18, anchor="w").pack(side="left")
        self.font_scale_var = tk.StringVar(value=self.config.get("font_scale") or "1.0")
        ttk.Combobox(
            row, textvariable=self.font_scale_var,
            values=("0.5", "0.7", "0.85", "1.0", "1.15", "1.3",
                    "1.5", "1.75", "2.0", "2.5", "3.0"),
            state="readonly", width=10,
            font=self.fonts["field"],
        ).pack(side="left")
        ttk.Label(row, text="  (1.0 = 기본 ~2배 크기, 더 키우려면 ↑)",
                  font=self.fonts["hint"], foreground="#64748b").pack(
            side="left", padx=(5, 0))

        row = ttk.Frame(ui_frame)
        row.pack(fill="x", pady=2)
        self.auto_open_var = tk.BooleanVar(value=self.config.get_bool("auto_open_result"))
        ttk.Checkbutton(row, text="번역 완료 후 결과 폴더 자동 열기",
                        variable=self.auto_open_var).pack(anchor="w")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _browse_tesseract(self) -> None:
        path = filedialog.askopenfilename(
            title="Tesseract 실행 파일 선택",
            filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")],
        )
        if path:
            self.tess_var.set(path)

    def _save(self) -> None:
        # 필수 입력 (agent_id_fast는 선택)
        required = {
            "client_key": "Client Key",
            "pass_key": "Pass Key",
            "endpoint_url": "Endpoint URL",
            "agent_id": "Agent ID (심화번역)",
            "email": "Email",
        }
        for key, label in required.items():
            if not self._entries[key].get().strip():
                messagebox.showwarning("입력 필요", f"{label}을(를) 입력해 주세요.",
                                       parent=self.dialog)
                return

        # URL/Email/Agent ID 형식 검증
        url_ok, url_msg = validate_endpoint_url(self._entries["endpoint_url"].get())
        if not url_ok:
            messagebox.showwarning("Endpoint URL 오류", url_msg, parent=self.dialog)
            return

        email_ok, email_msg = validate_email(self._entries["email"].get())
        if not email_ok:
            messagebox.showwarning("Email 오류", email_msg, parent=self.dialog)
            return

        agent_ok, agent_msg = validate_agent_id(self._entries["agent_id"].get())
        if not agent_ok:
            messagebox.showwarning("Agent ID (심화) 오류", agent_msg, parent=self.dialog)
            return

        # 빠른번역 Agent ID는 선택. 입력된 경우에만 형식 검증.
        fast_raw = self._entries["agent_id_fast"].get().strip()
        if fast_raw:
            fast_ok, fast_msg = validate_agent_id(fast_raw)
            if not fast_ok:
                messagebox.showwarning("Agent ID (빠른) 오류", fast_msg, parent=self.dialog)
                return

        # 청크 크기: 빈 값 허용 (모드 기본값 사용)
        chunk_val = self.chunk_var.get().strip()
        if chunk_val and not (chunk_val.isdigit() and int(chunk_val) >= 500):
            messagebox.showwarning(
                "입력 오류",
                "청크 크기는 비워 두거나 500 이상의 숫자여야 합니다.",
                parent=self.dialog,
            )
            return

        # 타임아웃
        timeout_val = self.timeout_var.get().strip()
        if not (timeout_val.isdigit() and 5 <= int(timeout_val) <= 600):
            messagebox.showwarning("입력 오류", "타임아웃은 5~600초 범위여야 합니다.",
                                   parent=self.dialog)
            return

        # SSL 경고 더블체크
        if self.allow_insecure_var.get():
            if not messagebox.askyesno(
                "보안 경고",
                "SSL 검증 비활성화는 중간자 공격(MITM)에 취약합니다.\n"
                "회사 네트워크 환경에서만 제한적으로 허용하시겠습니까?",
                parent=self.dialog,
                icon="warning",
            ):
                return

        # 저장
        for key, var in self._entries.items():
            self.config.set(key, var.get().strip())
        self.config.set("tesseract_path", self.tess_var.get().strip())
        self.config.set("max_chunk_chars", chunk_val)
        self.config.set("timeout_seconds", timeout_val)
        self.config.set("allow_insecure_ssl", "true" if self.allow_insecure_var.get() else "false")
        self.config.set("ui_theme", self.theme_var.get())
        self.config.set("font_scale", self.font_scale_var.get())
        self.config.set("auto_open_result", "true" if self.auto_open_var.get() else "false")

        self.config.save()
        self.config.apply_tesseract_path()
        self.result = True
        self.dialog.destroy()

    def wait(self) -> bool:
        self.dialog.wait_window()
        return self.result
