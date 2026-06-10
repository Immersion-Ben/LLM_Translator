# LLM Translator (Samsung C&T) — v4.0.0

문서·이미지(PDF/Word/Excel/PPT/이미지)를 **오프라인 Tesseract OCR + FabriX Agent 번역**으로
처리하는 Windows 데스크톱 GUI 앱입니다. 사내 소프트웨어 개발보안 가이드 49개 항목
보안검토 결과가 반영된 버전(Tesseract 기반)입니다.

> 이전 PaddleOCR 기반 버전은 `paddle-OCR` 브랜치에 있습니다. 본 `main` 브랜치는
> 보안검토에 따라 OCR 엔진을 **Tesseract** 로 전환한 배포본입니다.

## 주요 특징
- 오프라인 OCR: Tesseract 엔진 + 언어팩을 exe 에 번들 → 인터넷 없는 사내망에서 동작
- 지원 OCR 언어: `constants.py`의 `OCR_LANG_MAP` 20개 언어 + osd (표준 tessdata)
- 한글 등 비ASCII 설치 경로에서도 OCR 동작 (`config_manager._ascii_safe_dir` 보정)
- 문서 형식: docx, pdf, txt, xlsx, pptx, png/jpg/jpeg/bmp/tiff/tif

## 런타임 요구사항
- Windows 10/11 (x64)
- 배포본(아래 빌드 산출물)은 Python 설치 불필요 (onedir 번들)
- 소스 실행 시: Python 3.13 + `pip install -r requirements.txt`

## 빌드 (배포 패키지 생성)
인터넷이 되는 PC에서 1회 빌드한 뒤, 산출물을 오프라인망으로 전달합니다.

```powershell
# 1) 의존성
pip install -r requirements.txt

# 2) Tesseract 엔진/언어팩을 vendor\Tesseract-OCR 로 구성
#    - 바이너리: UB-Mannheim Tesseract 설치본(C:\Program Files\Tesseract-OCR)
#    - 언어팩 : OCR_LANG_MAP 20개 + osd (표준 tessdata)
python prepare_tesseract.py --install "C:\Program Files\Tesseract-OCR" --tessdata <tessdata_경로>

# 3) 빌드 (PyInstaller onedir + tessdata 정리 + 풀 zip)
python build_exe.py
```

### 산출물
- `dist\LLMTranslator\LLM_translator.exe` — 실행 파일 (onedir, 약 640MB)
- `LLMTranslator_v4.0.0_full.zip` — 배포용 풀 패키지 (약 285MB)

> **재현성**: `vendor/Tesseract-OCR`(엔진+21개 언어팩, 약 433MB)는 PC 초기화 대비로
> 저장소에 **포함**되어 있습니다. 따라서 clone 후 `prepare_tesseract.py` 없이 바로
> `python build_exe.py` 로 재빌드할 수 있습니다.
>
> `dist/`, `build/`, `*.zip` 은 재빌드 가능하고 zip 단일 파일이 GitHub 100MB 제한을
> 초과하므로 저장소에서 제외됩니다(.gitignore). 빌드된 패키지 자체를 보관하려면
> GitHub Releases 에 zip 을 첨부하거나 Git LFS 를 사용하세요.

### 초기화된 PC에서 다시 빌드
```powershell
git clone https://github.com/Immersion-Ben/LLM_Translator.git
cd LLM_Translator
pip install -r requirements.txt
python build_exe.py        # vendor/ 가 이미 있으므로 바로 빌드됨
```

## 배포 / 실행
1. `LLMTranslator_v4.0.0_full.zip` 을 대상 PC에 압축 해제
2. `LLMTranslator\LLM_translator.exe` 실행
3. 최초 1회: 설정 화면에서 FabriX Agent 접속 정보(Client/Pass Key, Endpoint, Agent ID, Email) 입력

## 보안검토
- `[로우데이터_보고서]_187_LLM_번역기(1)-소프트웨어_개발보안_가이드_49개_항목_조치결과.XLSX`
  — 49개 항목 조치 결과
- 입력 경로 검증(Path Traversal 차단), 민감정보 마스킹, 설정 파일 권한 제한,
  SSL 인증서 번들, 외부 OCR 스택(paddle/torch 등) 빌드 제외 등 반영
