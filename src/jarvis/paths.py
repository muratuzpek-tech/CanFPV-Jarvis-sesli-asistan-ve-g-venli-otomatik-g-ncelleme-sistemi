"""Tek kaynak: kod nerede, KULLANICI VERİSİ nerede.

v25 paketinde her modül kendi `BASE_DIR`ini `Path(__file__).parent...` ile
hesaplıyor ve `memory/`, `logs/`, `tasks/` klasörlerini KOD KLASÖRÜNÜN İÇİNE
yazıyordu. Sonuçları: (1) kullanıcının konuşma geçmişi ve görev kayıtları
dağıtım zip'ine sızıyordu, (2) uygulama "Program Files" gibi yazma izni
olmayan bir yere kurulduğunda çöküyordu, (3) güncelleme = kullanıcı verisinin
üzerine yazmak demekti.

Burada kod dizini (salt okunur) ile veri dizini (yazılabilir) ayrılır.

Veri dizini önceliği:
  1. ``JARVIS_HOME`` ortam değişkeni
  2. Proje kökünde `memory/` varsa (eski kurulumdan gelen veri) -> geriye dönük uyum
  3. Windows: %LOCALAPPDATA%\\MuratJARVIS | macOS: ~/Library/Application Support/MuratJARVIS
     | Linux: $XDG_DATA_HOME/MuratJARVIS (yoksa ~/.local/share/MuratJARVIS)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MuratJARVIS"


def package_dir() -> Path:
    """Kodun bulunduğu dizin (salt okunur kabul edilir)."""
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """Depo kökü (kurulu pakette paket dizininin iki üstü: src/jarvis -> repo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return package_dir().parent.parent


def assets_dir() -> Path:
    """Pakete gömülü görseller/ikonlar."""
    return package_dir() / "assets"


def asset(name: str) -> Path:
    return assets_dir() / name


def _platform_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    env = os.environ.get("JARVIS_HOME", "").strip()
    if env:
        path = Path(env).expanduser()
    else:
        legacy = project_root() / "memory"
        path = project_root() if legacy.is_dir() else _platform_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sub(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_dir() -> Path:
    return _sub("memory")


def logs_dir() -> Path:
    return _sub("logs")


def tasks_dir() -> Path:
    return _sub("tasks")


def config_dir() -> Path:
    """Kullanıcıya ait yapılandırma (api_keys.json, certs/) — kod dizininde DEĞİL."""
    return _sub("config")


def certs_dir() -> Path:
    return _sub("config/certs")
