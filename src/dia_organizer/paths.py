import os
from pathlib import Path


def data_home() -> Path:
    env = os.environ.get("DIA_ORGANIZER_HOME")
    return Path(env) if env else Path.home() / ".dia-organizer"


def db_path() -> Path:
    return data_home() / "db.sqlite"


def config_path() -> Path:
    return data_home() / "config.toml"


def lock_path() -> Path:
    return data_home() / "scan.lock"


def log_path() -> Path:
    return data_home() / "scan.log"


def err_path() -> Path:
    return data_home() / "scan.err"


def dia_app_support() -> Path:
    return Path.home() / "Library" / "Application Support" / "Dia"


def dia_local_state() -> Path:
    return dia_app_support() / "User Data" / "Local State"


def dia_storable_profiles() -> Path:
    return dia_app_support() / "StorableProfileContainers.json"


def ensure_data_home() -> Path:
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    return home
