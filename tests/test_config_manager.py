import json

import config_manager


def _configure_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    legacy_path = tmp_path / "legacy_config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(config_manager, "LEGACY_CONFIG_FILE", str(legacy_path))
    return config_path, legacy_path


def test_load_config_handles_corrupt_json(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text("{bad json", encoding="utf-8")
    cm = config_manager.ConfigManager()
    prefs = cm.get_preferences()
    assert "download_path" in prefs
    assert cm.get_profiles()


def test_load_config_migrates_legacy(tmp_path, monkeypatch):
    config_path, legacy_path = _configure_paths(tmp_path, monkeypatch)
    legacy_path.write_text(
        json.dumps({"preferences": {"download_path": "C:\\Downloads"}, "profiles": {}}),
        encoding="utf-8",
    )
    cm = config_manager.ConfigManager()
    assert cm.get_preferences().get("download_path") == "C:\\Downloads"
    assert config_path.exists()


def test_normalize_prefs_missing_keys(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text(json.dumps({"preferences": {"download_path": "C:\\X"}, "profiles": {}}), encoding="utf-8")
    cm = config_manager.ConfigManager()
    prefs = cm.get_preferences()
    assert prefs.get("download_path") == "C:\\X"
    assert "web_ui_port" in prefs


def test_get_profiles_returns_copy(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text(
        json.dumps({
            "preferences": {},
            "profiles": {"p1": {"name": "Original", "type": "local", "url": "C:\\X", "user": "", "password": ""}},
            "default_profile": "p1",
        }),
        encoding="utf-8",
    )
    cm = config_manager.ConfigManager()
    profiles = cm.get_profiles()
    profiles["p1"]["name"] = "Mutated"

    assert cm.get_profile("p1")["name"] == "Original"


def test_load_config_repairs_blank_default_profile(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text(
        json.dumps({
            "preferences": {},
            "profiles": {"p1": {"name": "Local", "type": "local", "url": "C:\\X", "user": "", "password": ""}},
            "default_profile": "",
        }),
        encoding="utf-8",
    )

    cm = config_manager.ConfigManager()

    assert cm.get_default_profile_id() == "p1"


def test_load_config_repairs_invalid_default_profile(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text(
        json.dumps({
            "preferences": {},
            "profiles": {
                "p1": {"name": "One", "type": "local", "url": "C:\\One", "user": "", "password": ""},
                "p2": {"name": "Two", "type": "local", "url": "C:\\Two", "user": "", "password": ""},
            },
            "default_profile": "missing",
        }),
        encoding="utf-8",
    )

    cm = config_manager.ConfigManager()

    assert cm.get_default_profile_id() == "p1"


def test_delete_default_profile_selects_remaining_profile(tmp_path, monkeypatch):
    config_path, _ = _configure_paths(tmp_path, monkeypatch)
    config_path.write_text(
        json.dumps({
            "preferences": {},
            "profiles": {
                "p1": {"name": "One", "type": "local", "url": "C:\\One", "user": "", "password": ""},
                "p2": {"name": "Two", "type": "local", "url": "C:\\Two", "user": "", "password": ""},
            },
            "default_profile": "p1",
        }),
        encoding="utf-8",
    )
    cm = config_manager.ConfigManager()

    cm.delete_profile("p1")

    assert cm.get_default_profile_id() == "p2"
