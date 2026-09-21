"""Offline, read-only post-install sanity check.

The check intentionally redirects JARVIS_HOME to a temporary directory. It
creates only empty directory scaffolding there, never reads/writes a real user
configuration, and does not start a browser, backend, network client, audio,
or dashboard.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="jarvis-post-install-") as temporary_home:
        os.environ["JARVIS_HOME"] = temporary_home
        os.environ.pop("JARVIS_API_KEYS", None)
        from jarvis import __version__, paths
        from jarvis.core.secure_config import api_keys_path

        assert __version__ == "25.1.0", __version__
        package = paths.package_dir()
        home = Path(temporary_home).resolve()
        assert paths.data_dir().resolve() == home
        directories = (
            paths.memory_dir(),
            paths.logs_dir(),
            paths.tasks_dir(),
            paths.config_dir(),
            paths.certs_dir(),
        )
        for directory in directories:
            resolved = directory.resolve()
            assert resolved == home or home in resolved.parents, resolved
            assert package not in resolved.parents, resolved
        key_path = api_keys_path(for_write=True).resolve()
        assert key_path.parent == (home / "config").resolve(), key_path
        assert not key_path.exists(), "post-install check must not create an API key"
    print("POST_INSTALL_CHECK_OK (offline; temporary JARVIS_HOME)")


if __name__ == "__main__":
    main()
