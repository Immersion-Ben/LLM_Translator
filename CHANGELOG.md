# Changelog

## v1.0.0 — Enhanced OCR (2026-06-24)

알파(3.2.0-alpha)를 졸업한 첫 정식 릴리스. 무테두리 표 처리 품질과 입력 보안을 강화했다.

### 표/OCR 품질
- **무테두리 표 본문 중복·순서 교란 수정**: 표로 인식된 영역의 텍스트가
  `table_htmls`(docx 표)와 `text_blocks`(본문)에 **중복**되어 본문 순서가 뒤섞이던
  문제 해결. 표 영역 안의 텍스트는 본문에서 제외한다(`_drop_inside`).
  - 실측: 무테두리 명단표 이미지에서 본문 중복 텍스트 25개 → 0개.
- **좌표 기반 읽기순서 복원(`_reading_order`)**: 표로 잡히지 않은 무테두리 다열
  본문(예: 키-값 블록, 채점표)을 검출 원시 순서 대신 **행 우선(좌→우, 상→하)**으로
  재정렬. 좌표가 없으면 원래 순서를 안전하게 유지.

### 보안 (사내 개발보안 가이드 반영)
- **CWE-22**: OCR/PDF·이미지 진입점(`JobManager.submit`)에 `validate_input_path`
  추가 — 텍스트 경로(`translate_file`)와 대칭으로 경로 순회·제어문자·허용 외
  확장자·미존재 입력을 큐 적재 전에 차단.
- **CWE-489**: 활성 디버그 코드로 탐지된 `logger.debug` 호출을 `logger.info`/
  `logger.warning`으로 전환(`app_ui.py`, `dependencies.py`, `main.py`,
  `settings_dialog.py`).
- **CWE-476**: 추정치 NULL 검사를 단축평가 대신 명시적 중첩 `if`로 보강.

### 테스트
- 신규 단위 테스트 9개(읽기순서·중복 제거·표영역 helper·CWE-22 거부) 포함 총 26개 통과.
