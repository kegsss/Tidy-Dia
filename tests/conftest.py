# tests/conftest.py
import os
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_data_dir(monkeypatch, tmp_path):
    """Redirect ~/.dia-organizer to a temp dir for the duration of a test."""
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    return tmp_path
