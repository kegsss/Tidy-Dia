import pytest
from dia_organizer import locking


def test_acquire_then_release(tmp_data_dir):
    with locking.scan_lock() as got:
        assert got is True


def test_second_acquire_blocks(tmp_data_dir):
    with locking.scan_lock():
        with pytest.raises(locking.LockHeld):
            with locking.scan_lock():
                pass
