"""작업 중앙 색인(jobs.json) — 재시작 목록 복원용 가벼운 포인터 저장소."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
from typing import Optional

from constants import JobStatus


@dataclass
class Job:
    id: str
    source: str
    mode: str
    status: str
    ocr_json: Optional[str] = None
    result_docx: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""


class JobStore:
    def __init__(self, index_path: Path) -> None:
        self._path = Path(index_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for d in data.get("jobs", []):
                self._jobs[d["id"]] = Job(**d)

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        payload = {"jobs": [asdict(j) for j in self._jobs.values()]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._save()
            return job

    def update(self, job_id: str, **fields) -> Job:
        with self._lock:
            j = self._jobs[job_id]
            for k, v in fields.items():
                setattr(j, k, v)
            self._save()
            return j

    def get(self, job_id: str) -> Optional[Job]:
        # 락 하에 스냅샷 복사본을 반환한다. 호출자가 받은 객체를 읽는 동안
        # 다른 스레드의 update() 가 내부 Job 을 변경해도 경합이 없다(불변 스냅샷).
        with self._lock:
            j = self._jobs.get(job_id)
            return replace(j) if j is not None else None

    def list(self) -> list[Job]:
        with self._lock:
            return [replace(j) for j in self._jobs.values()]

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._save()

    def recover(self) -> None:
        """재시작 복구: 진행 중이던 상태를 안전 지점으로 되돌린다."""
        with self._lock:
            for j in self._jobs.values():
                if j.status == JobStatus.OCR_RUNNING:
                    j.status = JobStatus.QUEUED
                elif j.status in (JobStatus.TRANSLATING, JobStatus.TRANS_QUEUED):
                    j.status = JobStatus.OCR_DONE
            self._save()
