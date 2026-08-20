from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import os
import uuid

from .db import Database


def _pid_exists(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


@contextmanager
def exclusive_job(db: Database, lock_path: Path, job_type: str):
    """Cross-process exclusive lock with an auditable job record."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    maintenance_lock = lock_path.parent / ".maintenance.lock"
    if maintenance_lock.exists():
        raise RuntimeError("数据库正在备份或恢复维护，数据任务暂不启动")
    descriptor = None
    job_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, f"{os.getpid()}\n{job_id}".encode())
    except FileExistsError as error:
        stale = False
        stale_job_id = None
        try:
            lines = lock_path.read_text(encoding="utf-8").splitlines()
            pid = int(lines[0])
            stale_job_id = lines[1] if len(lines) > 1 else None
            stale = not _pid_exists(pid)
        except Exception:
            stale = (datetime.now().timestamp() - lock_path.stat().st_mtime) > 6 * 3600
        if stale:
            if stale_job_id:
                with db.connect() as con:
                    con.execute(
                        """UPDATE data_jobs SET finished_at=?,status='failed',
                        message=COALESCE(message,'进程异常终止，已回收陈旧写锁')
                        WHERE job_id=? AND status='running'""",
                        (datetime.now().isoformat(timespec="seconds"), stale_job_id),
                    )
                    con.execute(
                        """UPDATE universe_batches SET finished_at=?,status='partial',
                        message=COALESCE(message || '；','') || '所属写进程异常终止，批次已回收'
                        WHERE status='running'""",
                        (datetime.now().isoformat(timespec="seconds"),),
                    )
            lock_path.unlink(missing_ok=True)
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()}\n{job_id}".encode())
        else:
            raise RuntimeError("已有数据更新任务在运行，请等待其完成后再试") from error
    with db.connect() as con:
        con.execute(
            "INSERT INTO data_jobs(job_id,job_type,started_at,status) VALUES (?,?,?,'running')",
            (job_id, job_type, datetime.now().isoformat(timespec="seconds")),
        )
    outcome = {"succeeded": 0, "failed": 0, "message": None}
    try:
        yield outcome
        final_status = "partial" if outcome["failed"] else "success"
        with db.connect() as con:
            con.execute(
                "UPDATE data_jobs SET finished_at=?,status=?,succeeded=?,failed=?,message=? WHERE job_id=?",
                (datetime.now().isoformat(timespec="seconds"), final_status, outcome["succeeded"], outcome["failed"], outcome["message"], job_id),
            )
    except Exception as error:
        with db.connect() as con:
            con.execute(
                "UPDATE data_jobs SET finished_at=?,status='failed',succeeded=?,failed=?,message=? WHERE job_id=?",
                (datetime.now().isoformat(timespec="seconds"), outcome["succeeded"], outcome["failed"], str(error)[:500], job_id),
            )
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
