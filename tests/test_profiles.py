from pathlib import Path
from dia_organizer import profiles

FIXT = Path(__file__).parent / "fixtures"


def test_resolve_window_to_profile():
    mapping = profiles.resolve_from_files(
        local_state=FIXT / "local_state.json",
        storable=FIXT / "storable_profile_containers.json",
    )
    assert mapping["AAAA-WIN-DEFAULT"] == "Keagan"
    assert mapping["BBBB-WIN-TOGETHER"] == "Together User"
    # Profile 7 has no open window — not in map.
    assert "Demo Together User" not in mapping.values()


def test_unknown_profile_falls_back_to_id():
    mapping = profiles.resolve_from_files(
        local_state=FIXT / "local_state.json",
        storable=FIXT / "storable_profile_containers.json",
    )
    assert "AAAA-WIN-DEFAULT" in mapping


def test_missing_files_returns_empty(tmp_path):
    mapping = profiles.resolve_from_files(
        local_state=tmp_path / "missing1.json",
        storable=tmp_path / "missing2.json",
    )
    assert mapping == {}
