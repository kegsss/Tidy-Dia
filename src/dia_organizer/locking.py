from __future__ import annotations
import contextlib
import fcntl
from dia_organizer import paths


class LockHeld(RuntimeError):
    pass


@contextlib.contextmanager
def scan_lock():
    paths.ensure_data_home()
    p = paths.lock_path()
    f = open(p, "w")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise LockHeld(f"scan lock held at {p}") from e
        yield True
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()
