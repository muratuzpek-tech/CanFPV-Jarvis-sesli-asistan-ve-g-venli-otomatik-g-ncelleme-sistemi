"""Jarvis'in kendi kendini kontrol etmesini saglayan saglik taramasi.

Tek bir sesli komutla ("kendini kontrol et"), en sik karsilasilan sorunlarin
(Ollama kapali, mikrofon sinyal vermiyor, hafiza dosyasi bozuk, kod
dosyalarinda sozdizimi hatasi, internet baglantisi yok) hepsini saniyeler
icinde tarar ve TEK bir ozet rapor dondurur.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()


def _check_ollama() -> tuple[bool, str]:
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        if models:
            return True, f"Ollama çalışıyor, {len(models)} model yüklü ({', '.join(models[:3])})"
        return True, "Ollama çalışıyor ama hiç model indirilmemiş"
    except Exception as e:
        return False, f"Ollama'ya ulaşılamıyor ({type(e).__name__}) — 'ollama serve' çalışıyor mu kontrol et"


def _check_microphone() -> tuple[bool, str]:
    try:
        import sounddevice as sd
        import numpy as np

        EXCLUDE = ("cable", "ses eşleştiricisi", "sound mapper", "mapper", "vb-audio")
        devices = sd.query_devices()
        candidates = [i for i, d in enumerate(devices)
                      if d.get("max_input_channels", 0) > 0
                      and not any(x in d.get("name", "").lower() for x in EXCLUDE)]
        if not candidates:
            return False, "Kullanılabilir mikrofon cihazı bulunamadı"

        device = candidates[0]
        duration = 1.0
        recording = sd.rec(int(duration * 16000), samplerate=16000, channels=1,
                            dtype="int16", device=device)
        sd.wait()
        peak = int(np.abs(recording).max())
        name = devices[device]["name"]
        if peak < 50:
            return False, f"Mikrofon ('{name}') sessiz görünüyor (seviye: {peak}) — konuşurken tekrar dene"
        return True, f"Mikrofon ('{name}') sinyal alıyor (seviye: {peak})"
    except Exception as e:
        return False, f"Mikrofon kontrolü başarısız: {type(e).__name__}: {e}"


def _check_memory() -> tuple[bool, str]:
    try:
        from memory.memory_manager import load_memory
        mem = load_memory()
        total_facts = sum(len(v) for v in mem.values() if isinstance(v, dict))
        return True, f"Hafıza dosyası okunabiliyor, {total_facts} kayıtlı bilgi var"
    except Exception as e:
        return False, f"Hafıza dosyası okunamıyor: {type(e).__name__}: {e}"


def _check_python_files() -> tuple[bool, str]:
    import ast
    broken = []
    checked = 0
    for py_file in list(BASE_DIR.glob("*.py")) + list((BASE_DIR / "actions").glob("*.py")) + list((BASE_DIR / "core").glob("*.py")):
        checked += 1
        try:
            ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            broken.append(f"{py_file.name} (satır {e.lineno})")
    if broken:
        return False, f"{len(broken)}/{checked} dosyada sözdizimi hatası: {', '.join(broken[:3])}"
    return True, f"{checked} Python dosyasının tamamı sözdizimi olarak geçerli"


def _check_internet() -> tuple[bool, str]:
    try:
        import requests
        requests.head("https://www.google.com", timeout=3)
        return True, "İnternet bağlantısı çalışıyor"
    except Exception:
        return False, "İnternet bağlantısı yok veya çok yavaş"


def health_check(parameters: dict = None, response=None, player=None) -> str:
    """Tum kontrolleri calistirip TEK bir ozet Turkce rapor dondurur."""
    checks = [
        ("Ollama", _check_ollama),
        ("Mikrofon", _check_microphone),
        ("Hafıza", _check_memory),
        ("Kod dosyaları", _check_python_files),
        ("İnternet", _check_internet),
    ]

    results = []
    all_ok = True
    for label, fn in checks:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"Kontrol sırasında beklenmeyen hata: {e}"
        all_ok = all_ok and ok
        icon = "✅" if ok else "⚠️"
        results.append(f"{icon} {label}: {detail}")
        if player:
            player.write_log(f"[HealthCheck] {icon} {label}: {detail}")

    header = "Tüm sistemler yolunda." if all_ok else "Bazı sorunlar tespit edildi:"
    return header + "\n" + "\n".join(results)
