from pathlib import Path
from dia_organizer import paths


def test_data_home_uses_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.data_home() == tmp_path


def test_data_home_default(monkeypatch):
    monkeypatch.delenv("DIA_ORGANIZER_HOME", raising=False)
    assert paths.data_home() == Path.home() / ".dia-organizer"


def test_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.db_path() == tmp_path / "db.sqlite"


def test_config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.config_path() == tmp_path / "config.toml"


def test_dia_user_data_default():
    expected = Path.home() / "Library" / "Application Support" / "Dia"
    assert paths.dia_app_support() == expected
