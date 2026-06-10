# PaddleOCR 마이그레이션 — 진행상황 & 잔여작업 (2026-06-10)

> 이 PC는 재시작 시 파일이 삭제되므로, 재개 시 아래 "환경 재구성"부터 따라 하면 됩니다.
> 모든 코드는 `paddle-OCR` 브랜치(원격)에 푸시되어 있습니다.

## ✅ 완료 (커밋·푸시됨)

원래 구현 계획: `docs/superpowers/plans/2026-06-09-paddleocr-table-recognition.md` (Task 0~14)

- **Task 0~11** (이전 세션): table_grid / paddle_ocr / ocr_store / ocr_document /
  page_pipeline / job_store / job_manager 구현 + 단위 테스트. 모두 통과.
- **Task 12 — UI ↔ JobManager 연동** (`app_ui.py`):
  - `JobStore`+`PaddleTableOCR`+`JobManager` 생성·구동·종료 연동
  - PDF/이미지 → 작업 큐(OCR 표보존→번역) 경유, 텍스트 문서는 기존 동기 경로 유지
  - 모드바에 OCR 산출 방식 토글(OCR+번역 / OCR만)
  - 워커 스레드 상태변화를 `root.after` 로 마샬링 → 파일 행 반영
  - OCR만 완료 행에 `▶ 번역` 버튼, 재시작 후 작업 목록 복원, 종료 시 워커 정리
- **Task 14 — Tesseract 제거 + 번들**:
  - Tesseract 배선 완전 제거(apply_tesseract_path/설정 OCR 탭/pytesseract/
    OCR_LANG_MAP/get_ocr_lang/prepare_tesseract.py)
  - `prepare_paddleocr.py`(모델 전체 수집), `build_exe.py` 재작성(PaddleOCR
    collect-all + 모델 add-data), `requirements.txt` 추가
- **Task 13 — 실제 PaddleOCR 검증(부분)**:
  - paddlepaddle 3.3.1 / paddleocr 3.6.0 / paddlex[ocr] 3.6.1 설치
  - paddle 스모크 테스트 통과(실제 모델 추론, 합성 표 → `<table` HTML)
  - 실제 합성 표 이미지 → JobManager full 경로 → 병합표 보존 docx(DONE) 확인
  - **단위 테스트 14 passed**

## 🔌 오프라인 동작 메커니즘 (구현 완료, 번들 검증은 잔여)

- PaddleX 는 `<PADDLE_PDX_CACHE_HOME>/official_models/<모델>` 이 존재하면
  인터넷 hoster(HF/ModelScope/AIStudio)를 **전혀 호출하지 않는다**
  (없을 때만 다운로드 시도). 근거: `paddlex/inference/utils/official_models.py`
  `_get_model_local_path()` — 로컬 존재 시 early-return.
- 표 인식 파이프라인은 **wired+wireless 9개 모델 전부**를 적재한다(로그 확인):
  PP-LCNet_x1_0_doc_ori, PP-DocLayout-L, PP-LCNet_x1_0_table_cls,
  SLANeXt_wired, SLANeXt_wireless, RT-DETR-L_wired_table_cell_det,
  RT-DETR-L_wireless_table_cell_det, PP-OCRv4_server_det, PP-OCRv4_server_rec_doc.
- 따라서 `prepare_paddleocr.py` 는 `~/.paddlex/official_models` **전체**를
  `vendor/paddleocr-models/official_models/` 로 복사한다.
- 런타임(`paddle_ocr.py`)은 번들(`vendor/` 또는 frozen `_MEIPASS`)에
  `official_models/` 가 있으면 `PADDLE_PDX_CACHE_HOME` 을 그 위치로 자동 지정 →
  인터넷 없이 모든 모델 로컬 해석.

## ⏭ 잔여작업 (재개 시)

1. **모델 번들 생성** (인터넷 되는 PC, ~/.paddlex 캐시 필요)
   ```
   python prepare_paddleocr.py
   ```
   → `vendor/paddleocr-models/official_models/` 에 9개 모델(~800MB+) 복사.

2. **오프라인 동작 검증** (네트워크 차단 상태로 파이프라인 생성·인식)
   - 별도 프로세스에서 `PADDLE_PDX_CACHE_HOME=<…>/vendor/paddleocr-models`,
     `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`, `HF_HUB_OFFLINE=1`,
     죽은 프록시(`HTTP(S)_PROXY=http://127.0.0.1:9`) 로 합성 표 인식 → DONE 확인.

3. **단일 실행 배포본(exe) 빌드** — Python·패키지·모델 없이 구동
   ```
   pip install pyinstaller
   python build_exe.py            # dist\python\python.exe + LLMTranslator_v*_full.zip
   ```
   - PyInstaller onedir + `--collect-all paddle/paddleocr/paddlex` +
     `vendor/paddleocr-models` 번들. 산출 zip 을 대상 PC 에 풀어 `python.exe` 실행.
   - ⚠ paddle 포함으로 산출물이 수 GB. 빌드 10~30분. hidden-import 누락 시
     `build_exe.py` 의 `_HIDDEN_IMPORTS` 보강 필요할 수 있음.

4. **frozen 오프라인 실기 검증** — 인터넷 끊긴 PC 에서 zip 풀어 PDF/이미지 번역.

5. **실제 중국어 PDF + 사내 LLM 육안 검증** — 표 병합/번역 품질 확인(사내 오프라인망).

## 🛠 환경 재구성 (재시작 후)

```
git clone -b paddle-OCR https://github.com/Immersion-Ben/LLM_Translator.git
cd LLM_Translator
pip install -r requirements.txt          # paddle 포함 전체 의존성
# 최초 1회: 모델 자동 다운로드(~800MB, 약 8분) — 인터넷 필요
python -m pytest -q                       # 14 passed 확인(모델 캐시됨)
python main.py                            # 앱 실행
```
- config: `~/.llm_translator/config.json` (API 키 등). 없으면 첫 실행 설정창에서 입력.
- 작업 색인: `~/.llm_translator/jobs.json` (재시작 후 작업 목록 복원).
