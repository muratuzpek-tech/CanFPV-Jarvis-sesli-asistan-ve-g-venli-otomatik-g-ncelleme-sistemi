"""v25'ten devralınan betik tarzı testleri gerçek pytest sonucuna dönüştürür.

Devralınan `test_*.py` dosyaları fonksiyon içermiyor; tüm doğrulamaları modül
seviyesinde `assert` ile yapıyor. pytest bunları import edip "0 test" raporluyordu,
yani bir dosya sessizce kaybolsa kimse fark etmezdi. Burada her biri ayrı bir
süreçte çalıştırılıp adlandırılmış bir test sonucu üretir.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = sorted(
    p.name for p in TESTS_DIR.glob("test_*.py")
    if p.name != Path(__file__).name
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_legacy_script(script: str, tmp_path: Path) -> None:
    env = {**os.environ, "JARVIS_HOME": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, str(TESTS_DIR / script)],
        capture_output=True, text=True, timeout=300, env=env,
        cwd=TESTS_DIR.parent,
    )
    assert result.returncode == 0, f"{script} başarısız:\n{result.stdout}\n{result.stderr}"
