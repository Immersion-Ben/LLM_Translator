"""OCR 큐·번역 큐 2워커 + 상태머신.

- OCR 워커(1): OCR 큐 소비. full 모드는 페이지 단위로 OCR(생산자)∥번역(소비자)
  를 겹쳐 docx 생성(page_pipeline). ocr_only 모드는 OCR 후 ocr.json 저장만.
- 번역 워커(1): ocr_only 후 요청된 작업을 OCR결과 로드 → 번역 → docx.
- 두 워커가 동시에 돌아 파일 A 번역 중 파일 B OCR 진행(큐 레벨 겹침)."""
from __future__ import annotations

import queue
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from constants import JobStatus, MODE_FULL, MODE_OCR_ONLY, OCR_DIR_NAME, INPUT_DIR_NAME, RESULT_DIR_NAME
from docx import Document
from file_translator import FileTranslator
from job_store import Job, JobStore
from ocr_document import ocr_document, iter_pages, count_pages
from ocr_store import save_ocr_result, load_ocr_result, OcrResult
from page_pipeline import run_page_pipeline


def _ocr_dir(source: str) -> Path:
    src = Path(source)
    base = src.parent.parent if src.parent.name == INPUT_DIR_NAME else src.parent
    d = base / OCR_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _result_docx_path(source: str) -> Path:
    src = Path(source)
    base = src.parent.parent if src.parent.name == INPUT_DIR_NAME else src.parent
    d = base / RESULT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{src.stem}_translated.docx"


class JobManager:
    def __init__(self, store: JobStore, translator, ocr_engine,
                 on_change: Optional[Callable[[Job], None]] = None) -> None:
        self.store = store
        self.translator = translator
        self.ocr_engine = ocr_engine
        self.on_change = on_change
        self.ft = FileTranslator(translator)
        self._ocr_q: "queue.Queue" = queue.Queue()
        self._trans_q: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.store.recover()
        for j in self.store.list():
            if j.status == JobStatus.QUEUED:
                self._ocr_q.put(j.id)
            elif j.status == JobStatus.OCR_DONE and j.mode == MODE_FULL:
                self._trans_q.put(j.id)

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._ocr_worker, daemon=True),
            threading.Thread(target=self._trans_worker, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._ocr_q.put(None)
        self._trans_q.put(None)

    def submit(self, source: str, mode: str = MODE_FULL) -> str:
        jid = uuid.uuid4().hex[:12]
        self.store.add(Job(id=jid, source=source, mode=mode, status=JobStatus.QUEUED))
        self._notify(jid)
        self._ocr_q.put(jid)
        return jid

    def request_translation(self, job_id: str) -> None:
        j = self.store.get(job_id)
        if j and j.status == JobStatus.OCR_DONE:
            self.store.update(job_id, status=JobStatus.TRANS_QUEUED)
            self._notify(job_id)
            self._trans_q.put(job_id)

    def _notify(self, job_id: str) -> None:
        if self.on_change:
            j = self.store.get(job_id)
            if j:
                self.on_change(j)

    def _ocr_worker(self) -> None:
        while not self._stop.is_set():
            jid = self._ocr_q.get()
            if jid is None:
                break
            j = self.store.get(jid)
            if not j or j.status != JobStatus.QUEUED:
                continue
            try:
                self.store.update(jid, status=JobStatus.OCR_RUNNING)
                self._notify(jid)
                src = j.source
                stem = Path(src).stem
                pages_dir = _ocr_dir(src) / f"{stem}_pages"
                if j.mode == MODE_FULL:
                    self._run_full(jid, src, stem, pages_dir)
                else:  # OCR_ONLY
                    produced = ocr_document(src, self.ocr_engine, pages_dir)
                    ocr_json = save_ocr_result(_ocr_dir(src), stem, produced)
                    self.store.update(jid, status=JobStatus.OCR_DONE, ocr_json=str(ocr_json))
                    self._notify(jid)
            except Exception as e:  # noqa: BLE001
                self.store.update(jid, status=JobStatus.FAILED, error=f"{type(e).__name__}")
                self._notify(jid)

    def _run_full(self, jid: str, src: str, stem: str, pages_dir: Path) -> None:
        """full 모드: 페이지 OCR(생산자) ∥ 번역(소비자) 를 겹쳐 docx 를 만든다.

        produce(i)=다음 페이지 OCR(단일 생산자 스레드), consume(i,pr)=번역+기록
        (메인 스레드). page i 번역 대기 중 page i+1 OCR 가 진행된다."""
        doc = Document()
        cell_cache: dict = {}
        collected: list = []
        gen = iter_pages(src, self.ocr_engine, pages_dir)

        def produce(i):
            pr = next(gen)
            collected.append(pr)
            return pr

        def consume(i, pr):
            self.ft.render_page_to_doc(doc, pr, cell_cache)
            return True

        try:
            run_page_pipeline(count_pages(src), produce, consume)
        finally:
            gen.close()  # 미소진 제너레이터의 finally(파일 close) 보장

        ocr_json = save_ocr_result(_ocr_dir(src), stem, OcrResult(source=src, pages=collected))
        out = _result_docx_path(src)
        doc.save(str(out))
        self.store.update(jid, status=JobStatus.DONE,
                          ocr_json=str(ocr_json), result_docx=str(out))
        self._notify(jid)

    def _trans_worker(self) -> None:
        while not self._stop.is_set():
            jid = self._trans_q.get()
            if jid is None:
                break
            j = self.store.get(jid)
            if not j or j.status != JobStatus.TRANS_QUEUED:
                continue
            try:
                self.store.update(jid, status=JobStatus.TRANSLATING)
                self._notify(jid)
                result = load_ocr_result(Path(j.ocr_json))
                doc = Document()
                cell_cache: dict = {}
                for pr in result.pages:
                    self.ft.render_page_to_doc(doc, pr, cell_cache)
                out = _result_docx_path(j.source)
                doc.save(str(out))
                self.store.update(jid, status=JobStatus.DONE, result_docx=str(out))
                self._notify(jid)
            except Exception as e:  # noqa: BLE001
                self.store.update(jid, status=JobStatus.FAILED, error=f"{type(e).__name__}")
                self._notify(jid)
