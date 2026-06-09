from job_store import Job, JobStore
from constants import JobStatus, MODE_FULL


def test_add_update_persist(tmp_path):
    idx = tmp_path / "jobs.json"
    s = JobStore(idx)
    j = s.add(Job(id="j1", source=r"C:\x.pdf", mode=MODE_FULL, status=JobStatus.QUEUED))
    assert s.get("j1").status == JobStatus.QUEUED
    s.update("j1", status=JobStatus.OCR_DONE, ocr_json=r"C:\OCR결과\x.ocr.json")
    # 새 인스턴스로 재로드 → 영속 확인
    s2 = JobStore(idx)
    assert s2.get("j1").status == JobStatus.OCR_DONE
    assert s2.get("j1").ocr_json.endswith("x.ocr.json")


def test_recover_resets_running(tmp_path):
    idx = tmp_path / "jobs.json"
    s = JobStore(idx)
    s.add(Job(id="a", source="a", mode=MODE_FULL, status=JobStatus.OCR_RUNNING))
    s.add(Job(id="b", source="b", mode=MODE_FULL, status=JobStatus.TRANSLATING))
    s.recover()
    assert s.get("a").status == JobStatus.QUEUED
    assert s.get("b").status == JobStatus.OCR_DONE
