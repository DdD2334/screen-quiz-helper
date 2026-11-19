# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

from config import Config, app_dir


def test_missing_file_autogen(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config.load(p)
    assert p.exists()
    assert cfg.is_first_run is True
    assert cfg.model.json_mode == "auto"
    assert cfg.hotkeys["copy_answers"] == "shift+alt+c"
    assert cfg.capture.max_image_side == 2048


def test_load_save_load_idempotent(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config.load(p)
    cfg.model.api_key = "sk-test-12345678"
    cfg.save(p)
    cfg2 = Config.load(p)
    assert cfg.to_dict() == cfg2.to_dict()
    assert cfg2.is_first_run is False


def test_old_config_compat(tmp_path):
    old = {
        "hotkeys": {"capture_fullscreen": "shift+alt+s"},
        "model": {
            "provider": "openai", "api_key": "PASTE_YOUR_API_KEY_HERE",
            "timeout_seconds": 30, "min_interval_seconds": 45,
            "extra": {"_note": "x", "api_version": "2024-08-01"},
            "_presets": {"openai": {}}, "_note": "y",
        },
        "capture": {"debounce_ms": 1000, "region_overlay": True},
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.model.api_key == ""
    assert "_note" not in cfg.model.extra
    assert cfg.model.extra["api_version"] == "2024-08-01"
    cfg.save(p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "_presets" not in raw["model"] and "_note" not in raw["model"]
    assert "region_overlay" not in raw["capture"]


def test_frozen_path(tmp_path, monkeypatch):
    exe = tmp_path / "dist" / "screen-quiz-helper.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert app_dir() == exe.parent.resolve()


def test_source_path():
    assert app_dir() == Path(__file__).resolve().parent.parent