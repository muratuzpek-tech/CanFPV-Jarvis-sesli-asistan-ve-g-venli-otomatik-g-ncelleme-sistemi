"""MuratJARVIS — tek bir kurulabilir Python paketi.

v25'te kod, depo kökünde birbirinden bağımsız üst düzey modüllerdi
(`actions`, `core`, `brains`, `ui`, `main`, ...). Bu, sadece "doğru klasörden
çalıştırıldığında" import edilebilen ve `pip install` edilemeyen bir yapıydı.
Artık hepsi `jarvis.*` altında.

Geriye dönük uyum: eski adla (`actions.web_search` gibi) yapılan dinamik
import'lar aşağıdaki finder sayesinde çalışmaya devam eder; böylece kendi
kodunu okuyup/yazan modüller (self_improve, entegrasyon, capability_resolver)
kırılmaz.
"""
from __future__ import annotations

import importlib
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec

__version__ = "25.1.0"

_LEGACY_TOP = (
    "actions", "brains", "core", "memory", "dashboard",
    "self_improvement", "openjarvis", "ui", "main",
)


class _LegacyLoader(Loader):
    def __init__(self, target: str) -> None:
        self._target = target

    def create_module(self, spec: ModuleSpec):
        module = importlib.import_module(self._target)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module) -> None:  # modül zaten yüklendi
        return None


class _LegacyFinder(MetaPathFinder):
    """`actions.x` -> `jarvis.actions.x` yönlendirmesi (sadece eski adlar için)."""

    def find_spec(self, fullname: str, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root not in _LEGACY_TOP or fullname.startswith("jarvis."):
            return None
        return ModuleSpec(fullname, _LegacyLoader(f"jarvis.{fullname}"))


if not any(isinstance(f, _LegacyFinder) for f in sys.meta_path):
    sys.meta_path.append(_LegacyFinder())
