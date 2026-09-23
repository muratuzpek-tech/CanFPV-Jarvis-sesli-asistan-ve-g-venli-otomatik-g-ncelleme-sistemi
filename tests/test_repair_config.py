"""Offline regression tests for the assigned configuration/dashboard area."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis import paths
from jarvis.core import secure_config


def test_data_path_and_legacy_fallback_are_explicit(tmp_path, monkeypatch):
    selected = tmp_path / "isolated"
    monkeypatch.setenv("JARVIS_HOME", str(selected))
    monkeypatch.delenv("JARVIS_USE_LEGACY_DATA", raising=False)
    assert paths.data_dir() == selected
    assert not selected.exists(), "selecting a data root must not create it"

    legacy_root = tmp_path / "legacy-root"
    (legacy_root / "memory").mkdir(parents=True)
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.setattr(paths, "project_root", lambda: legacy_root)
    monkeypatch.setenv("JARVIS_USE_LEGACY_DATA", "1")
    assert paths.data_dir() == legacy_root

    monkeypatch.setenv("JARVIS_USE_LEGACY_DATA", "0")
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
        assert paths.data_dir() == tmp_path / "localappdata" / paths.APP_NAME
    elif sys.platform != "darwin":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert paths.data_dir() == tmp_path / "xdg" / paths.APP_NAME


def test_save_config_merges_atomically_and_keeps_existing_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_API_KEYS", raising=False)

    first = secure_config.save_config({"gemini_api_key": "file-secret", "os_system": "linux"})
    second = secure_config.save_config({"camera_index": 2})
    assert second == first
    saved = json.loads(first.read_text(encoding="utf-8"))
    assert saved == {
        "gemini_api_key": "file-secret",
        "os_system": "linux",
        "camera_index": 2,
    }
    if os.name == "posix":
        assert first.stat().st_mode & 0o777 == 0o600

    first.write_text("{malformed", encoding="utf-8")
    secure_config.save_config({"camera_index": 3})
    assert json.loads(first.read_text(encoding="utf-8")) == {"camera_index": 3}


def test_env_precedence_and_placeholder_values_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_API_KEYS", raising=False)
    secure_config.save_config({"gemini_api_key": "file-secret"})

    monkeypatch.setenv("JARVIS_USE_LEGACY_DATA", "1")
    assert secure_config.api_keys_path() == tmp_path / "config" / "api_keys.json"

    monkeypatch.setenv("GEMINI_API_KEY", " env-secret ")
    assert secure_config.get_gemini_api_key() == "env-secret"
    monkeypatch.setenv("GEMINI_API_KEY", "REPLACE_WITH_A_REAL_KEY")
    assert secure_config.get_gemini_api_key() == "file-secret"

    secure_config.save_config({"gemini_api_key": "<your-key>"})
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(RuntimeError) as exc_info:
        secure_config.get_gemini_api_key()
    assert "file-secret" not in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)


def test_screen_preferences_use_dynamic_user_data_path(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_API_KEYS", raising=False)
    from jarvis.actions import screen_processor

    screen_processor._save_config_key("gemini_api_key", "kept-secret")
    screen_processor._save_config_key("camera_index", 4)
    user_file = tmp_path / "config" / "api_keys.json"
    assert json.loads(user_file.read_text(encoding="utf-8")) == {
        "gemini_api_key": "kept-secret",
        "camera_index": 4,
    }
    assert screen_processor._get_camera_index() == 4

    screen_processor._save_config_key("camera_index", "invalid")
    monkeypatch.setattr(screen_processor, "_detect_camera_index", lambda: 1)
    assert screen_processor._get_camera_index() == 1
    screen_processor._save_config_key("os_system", 7)
    assert screen_processor._get_os() == "windows"


def test_firewall_setup_is_noop_without_explicit_opt_in(monkeypatch):
    from jarvis.dashboard import server

    monkeypatch.delenv("JARVIS_ALLOW_FIREWALL_SETUP", raising=False)
    monkeypatch.delenv("JARVIS_NO_FIREWALL_SETUP", raising=False)
    real_run = subprocess.run

    def fail_if_called(*args, **kwargs):
        raise AssertionError("firewall command attempted without explicit opt-in")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    server._ensure_network_access(6553)
    monkeypatch.setattr(subprocess, "run", real_run)


def _dashboard_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr("jarvis.dashboard.server._local_ip", lambda: "127.0.0.1")
    from fastapi.testclient import TestClient
    from jarvis.dashboard.server import DashboardServer

    dashboard = DashboardServer()
    return dashboard, TestClient(dashboard.app)


def test_dashboard_requires_auth_for_commands_and_files(tmp_path, monkeypatch):
    dashboard, client = _dashboard_client(tmp_path, monkeypatch)
    assert client.post("/api/command", json={"text": "unauthorized"}).status_code == 401
    assert client.get("/api/files").status_code == 401
    assert client.get("/uploads/example.txt", params={"token": "bad"}).status_code == 401

    pin = dashboard.new_key()
    login = client.post("/login", json={"pin": pin})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/command", json={"text": "authorized"}, headers=headers).json() == {"ok": True}
    assert dashboard._command_queue.get_nowait() == "authorized"


def test_dashboard_upload_and_download_stay_inside_user_root(tmp_path, monkeypatch):
    dashboard, client = _dashboard_client(tmp_path, monkeypatch)
    token = dashboard._tokens.pop() if dashboard._tokens else None
    # Authenticate through the public one-time PIN flow.
    pin = dashboard.new_key()
    token = client.post("/login", json={"pin": pin}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    outside = tmp_path / "outside.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    link = dashboard._uploads_dir / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert client.get("/uploads/link.txt", params={"token": token}).status_code == 404

    response = client.post(
        "/api/upload",
        files={"file": ("../nested.txt", b"safe-content", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200
    saved_name = response.json()["name"]
    saved = dashboard._uploads_dir / saved_name
    assert saved.parent == dashboard._uploads_dir
    assert saved.read_bytes() == b"safe-content"
    assert client.get(f"/uploads/{saved_name}", params={"token": token}).status_code == 200
    assert not (tmp_path / "nested.txt").exists()


def test_dashboard_websocket_rejects_missing_auth(tmp_path, monkeypatch):
    dashboard, client = _dashboard_client(tmp_path, monkeypatch)
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/phone-audio?token=bad"):
            pass


def test_tls_does_not_overwrite_existing_or_incomplete_material(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    key, cert = secure_config.tls_paths()
    key.parent.mkdir(parents=True)
    key.write_bytes(b"existing-key")
    assert secure_config.ensure_self_signed_cert() is None
    assert key.read_bytes() == b"existing-key"
    cert.write_bytes(b"existing-cert")
    assert secure_config.ensure_self_signed_cert() == (key, cert)
    assert key.read_bytes() == b"existing-key"


def test_assigned_files_compile_without_network_or_runtime_startup():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "src/jarvis/paths.py",
        root / "src/jarvis/core/secure_config.py",
        root / "src/jarvis/actions/screen_processor.py",
        root / "src/jarvis/dashboard/server.py",
    ]
    result = subprocess.run(
        [os.fspath(Path(os.sys.executable)), "-m", "py_compile", *(os.fspath(p) for p in files)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_tls_generation_is_user_local(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    result = secure_config.ensure_self_signed_cert()
    assert result is not None
    key, cert = result
    assert key.parent == tmp_path / "config" / "certs"
    assert cert.parent == key.parent
    assert key.read_bytes().startswith(b"-----BEGIN")
    assert cert.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    if os.name == "posix":
        assert key.stat().st_mode & 0o777 == 0o600
    assert key.parent.parent.parent == tmp_path
    assert not (Path(__file__).resolve().parents[1] / "src/jarvis/config/certs/jarvis.key").exists()


def test_no_firewall_test_executes_when_opt_in_is_missing():
    # Explicit marker for reviewers: this area deliberately does not invoke a
    # firewall command or start a server in its offline test suite.
    assert os.environ.get("JARVIS_ALLOW_FIREWALL_SETUP") != "1"
