import pytest

from stock_picker.db import Database
from stock_picker.jobs import exclusive_job


def test_job_lock_and_audit(tmp_path):
    db = Database(tmp_path / "jobs.db")
    lock = tmp_path / "job.lock"
    with exclusive_job(db, lock, "test") as outcome:
        outcome["succeeded"] = 3
        with pytest.raises(RuntimeError):
            with exclusive_job(db, lock, "second"):
                pass
    row = db.query_df("SELECT * FROM data_jobs WHERE job_type='test'").iloc[0]
    assert row.status == "success"
    assert row.succeeded == 3
    assert not lock.exists()


def test_partial_job_is_not_marked_success(tmp_path):
    db = Database(tmp_path / "jobs.db")
    with exclusive_job(db, tmp_path / "job.lock", "partial") as outcome:
        outcome["succeeded"] = 2
        outcome["failed"] = 1
    row = db.query_df("SELECT * FROM data_jobs WHERE job_type='partial'").iloc[0]
    assert row.status == "partial"


def test_stale_writer_lock_is_recovered_without_psutil_dependency(tmp_path):
    db = Database(tmp_path / "jobs.db")
    lock = tmp_path / "writer.lock"
    lock.write_text("99999999\nmissing-job", encoding="utf-8")
    with db.connect() as con:
        con.execute(
            """INSERT INTO universe_batches(
            batch_id,asset_type,market,as_of_date,started_at,status,source,source_tier
            ) VALUES('orphan','stock','A股','2026-08-14','2026-08-15T10:00:00','running','fixture','fixture')"""
        )
    with exclusive_job(db, lock, "recovered") as outcome:
        outcome["succeeded"] = 1
    assert not lock.exists()
    assert db.query_df("SELECT status FROM data_jobs WHERE job_type='recovered'").iloc[0].status == "success"
    assert db.query_df("SELECT status FROM universe_batches WHERE batch_id='orphan'").iloc[0].status == "partial"


def test_maintenance_lock_blocks_database_writer(tmp_path):
    db = Database(tmp_path / "jobs.db")
    (tmp_path / ".maintenance.lock").write_text("maintenance", encoding="utf-8")
    with pytest.raises(RuntimeError, match="维护"):
        with exclusive_job(db, tmp_path / ".writer.lock", "blocked"):
            pass
