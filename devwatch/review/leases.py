"""Local execution exclusion; the OS releases locks on process death.

Lock files are never unlinked: replacing their inode could admit two writers.
This requires a local filesystem, not distributed or network-file coordination.
"""
from contextlib import contextmanager
import errno
from hashlib import sha256
import os
from pathlib import Path
import sqlite3


@contextmanager
def runtime_lock(root, *, exclusive=False):
    """Shared lifetime lease or exclusive offline maintenance, released on death.

    A separate tiny rollback-journal SQLite file supplies portable OS reader/writer
    locks. Never unlink it: all processes must coordinate on the same file.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / ".maintenance.lock", timeout=0)
    try:
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='guard'").fetchone():
                db.execute("CREATE TABLE IF NOT EXISTS guard (id INTEGER PRIMARY KEY)")
                db.commit()
            db.execute("BEGIN EXCLUSIVE" if exclusive else "BEGIN")
            db.execute("SELECT * FROM guard").fetchall()
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise
            yield False
            return
        yield True
    finally:
        db.close()


@contextmanager
def execution_lock(store_path, job_id):
    directory = store_path.with_name(store_path.name + ".leases")
    directory.mkdir(exist_ok=True)
    path = directory / (sha256(job_id.encode()).hexdigest() + ".lock")
    with path.open("a+b") as handle:
        os.set_inheritable(handle.fileno(), False)
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
