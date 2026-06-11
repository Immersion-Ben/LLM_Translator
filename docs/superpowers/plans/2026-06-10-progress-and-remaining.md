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

## ✅ 잔여작업 1~4 완료 (2026-06-10 오후, 커밋 01bc66c~b4dd103)

1. ~~모델 번들 생성~~ — `vendor/paddleocr-models/official_models/` 9개 모델(1.28GB).
2. ~~오프라인 동작 검증~~ — 네트워크 차단(죽은 프록시+HF_HUB_OFFLINE) 상태에서
   합성 표 인식 DONE. 이 과정에서 발견·수정한 결함 2건:
   - **한글(비ASCII) 경로 결함**: paddle C++ 이 비ASCII 경로의 모델 파일을 못 열어
     "parse error … empty input" 발생. → `paddle_ocr._ascii_safe_dir` 가 8.3 short
     path 또는 ASCII 위치(Public/ProgramData) 대상별 해시 junction 으로 자동 우회.
   - **frozen 의존성 메타데이터 결함**: paddlex `require_extra('ocr')` 가
     의존성 dist-info 를 importlib.metadata 로 검사 → `build_exe._paddle_dep_metadata`
     가 paddlex/paddleocr 직접 의존성(50개)을 동적 추출해 `--copy-metadata` 번들.
3. ~~exe 빌드~~ — `dist\python\` 2.1GB, `LLMTranslator_v3.1.0-alpha_full.zip` 1.28GB.
4. ~~frozen 오프라인 구동 검증(로컬)~~ — 네트워크 차단 + `python.exe --selftest-ocr`
   → ExitCode 0 / OK, GUI 부팅 확인. 단위 테스트 17 passed.

추가: `--selftest-ocr` 자가진단 모드 신설(결과: 종료코드 + ~/.llm_translator/
selftest_ocr.txt), 버전 3.1.0-alpha.

## ✅ 잔여작업 0 완료 (2026-06-11, v3.1.1-alpha)

**수정**: `iter_pages` 의 text-layer 분기 + `pdf_text_extractor` 파라미터 +
`job_manager._pdf_text` 제거 → OCR 경로(OCR만/OCR+번역)는 항상 강제 OCR.
`kind:"text"` 소비 경로(file_translator.render_page_to_doc / ocr_store.kind)는
기존 ocr.json 호환 위해 유지. TDD: `test_text_layer_pdf_is_force_ocred`
(job_manager 레벨, RED 에서 OCR 0회 호출 재현) → 18 passed.

**검증** (2026-06-11):
- 합성 디지털 표 PDF(텍스트 레이어 有) → JobManager OCR_ONLY → kind="ocr",
  표 HTML 셀 내용 정확 (소스 레벨, 실모델).
- **Test.pdf(번체 중국어, 텍스트 레이어 有)** → 강제 OCR → 표 1개·셀 63개,
  중국어 셀/본문 60블록 정상 추출. (일부 간체 인식·행 병합은 모델 특성, 육안검증 대상)
- 재빌드: `dist\python\` + `LLMTranslator_v3.1.1-alpha_full.zip` (1275.8MB).
- 차단망 frozen selftest: 죽은 프록시 + HF_HUB_OFFLINE 에서 `python.exe
  --selftest-ocr` → ExitCode 0 / OK, 모델 9개 전부 번들 내부 해석.

## ~~🐞 잔여작업 0 — 텍스트 레이어 PDF 가 표 보존 OCR 을 우회하는 문제~~ (완료, 위 참조)

**증상** (2026-06-10 저녁 발견): "OCR만" 으로 디지털 PDF(test.pdf, 표 포함)를 돌리면
작업이 즉시 OCR_DONE 으로 끝나고, 산출 JSON 에 표가 평문으로 뭉개진
`kind:"text"` 페이지만 남는다. PaddleOCR 은 아예 실행되지 않음(pipeline ready 로그 없음).

**원인** (확정, 고장 아님): `ocr_document.iter_pages` 의 분류 규칙 —
페이지 텍스트 레이어가 10자 이상이면 OCR 을 건너뛰고 텍스트를 그대로 yield
(`ocr_document.py:50` 부근 `if len(txt.strip()) >= 10:`). 스캔 PDF 최적화로 넣은
분기가 표 있는 디지털 PDF 에서 표 보존 목적을 무력화.

**결정된 수정 방향 (사용자 확정)**: **항상 강제 OCR** — OCR 경로(OCR만/OCR+번역
모두)에서는 텍스트 레이어를 무시하고 모든 페이지를 PaddleOCR 로 처리한다.

**구현 메모**:
1. `iter_pages` 의 text-layer 분기(49~52행) 제거 — `pdf_text_extractor` 파라미터와
   호출부(job_manager/page_pipeline 의 인자 전달)도 함께 정리.
2. 관련 테스트 갱신: text 분기를 검증하는 기존 테스트가 있으면 강제 OCR 기대로 변경,
   "텍스트 레이어 있는 PDF 도 kind=ocr" 테스트 추가 (TDD).
3. `kind:"text"` 를 소비하는 하류(번역 단계/render_page_to_doc)가 있는지 확인 후
   dead path 정리 여부 결정.
4. 수정 후: `pytest` → `python build_exe.py` 재빌드 → 차단망 selftest + test.pdf
   재실행으로 표 HTML 산출 확인 → zip 재배포.

## ⏭ 남은 실기 검증 (사용자 수행)

1. **frozen 오프라인 실기 검증** — 인터넷 끊긴 PC 에서 zip 을 풀고
   `python.exe --selftest-ocr` 실행 → `~/.llm_translator/selftest_ocr.txt` 가 OK 면
   OCR 스택 정상. 이후 GUI 로 PDF/이미지 번역.
2. **실제 중국어 PDF + 사내 LLM 육안 검증** — 표 병합/번역 품질 확인(사내 오프라인망).

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
