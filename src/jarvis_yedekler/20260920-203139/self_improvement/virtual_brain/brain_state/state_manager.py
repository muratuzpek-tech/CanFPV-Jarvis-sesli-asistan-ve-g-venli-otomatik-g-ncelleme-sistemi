"""state_manager.py — SANAL BEYİN STATE SİSTEMİ (AŞAMA A).

"JARVIS — FAZ 9 Uyumlu Sanal Beyin / Digital Twin Geliştirme Promptu"
belgesinin AŞAMA A ("Virtual Brain temel klasör ve state sistemi") çıktısı.

Bu modül, Sanal Beyin'in güncel durumunu tek bir JSON dosyasında
(state.json, bu dosyayla aynı klasörde) tutar ve okuma/yazma için güvenli,
atomik bir API sunar. core/task_manager.py'deki İSPATLANMIŞ atomik-yazma
desenini (tempfile.NamedTemporaryFile + Path.replace) BİREBİR tekrar
kullanır - yeni bir mekanizma icat edilmedi (belgenin §41 "mevcut mimariye
adapte edilecek, yeni/çakışan bir sistem oluşturulmayacak" ilkesiyle
tutarlı).

KESİN SINIR (bu aşamada): bu modül SADECE bir durum deposudur. Gerçek
Jarvis Orchestrator'ını, Message Bus'ı ya da brains/*'i HENÜZ çağırmaz,
import etmez, hiçbir şekilde etkilemez. Hiçbir yerden import edilmiyor -
bu dosyayı projeye eklemek gerçek Jarvis'in davranışını değiştirmez.
Gerçek entegrasyon (core/brain_orchestrator.py ile koordinasyon), belgenin
kendi sırasına göre AŞAMA B'nin konusu ve ayrı bir kullanıcı onayı
gerektiriyor.
"""
from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent
STATE_PATH = STATE_DIR / "state.json"
_lock = threading.RLock()

# Alanlar, orijinal belgenin §34 (Brain Center UI) mockup'ıyla uyumlu:
# Status / Research / Experiments / Tests / Security / Audits /
# Pending Proposals / Latest Experiment.
DEFAULT_STATE: dict = {
    "status": "IDLE",                    # IDLE | ACTIVE
    "research_status": "IDLE",           # IDLE | RUNNING
    "experiments_count": 0,
    "tests_count": 0,
    "audits_count": 0,
    "security_last_result": None,        # ALLOW | BLOCK | REVIEW | None
    "pending_proposals": 0,
    "latest_experiment_id": None,        # ör. "EXP-20260915-004"
    "latest_experiment_result": None,
    "created_at": None,
    "updated_at": None,
}


def _atomic_write(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=STATE_DIR, delete=False, encoding="utf-8", suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(STATE_PATH)


def get_state() -> dict:
    """Mevcut Sanal Beyin durumunu döndürür. Dosya yoksa/bozuksa varsayılan
    durumu OLUŞTURUP kaydeder ve döndürür - Brain Center UI (FAZ 8) her
    zaman geçerli bir durum bulabilsin diye."""
    with _lock:
        try:
            if STATE_PATH.is_file():
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {**DEFAULT_STATE, **data}
        except Exception as e:
            print(f"[VirtualBrain] ⚠️ state.json okunamadı, varsayılana dönülüyor: {e}")

        now = datetime.now().isoformat()
        fresh = {**DEFAULT_STATE, "created_at": now, "updated_at": now}
        _atomic_write(fresh)
        return fresh


def update_state(**fields) -> dict:
    """Verilen alanları mevcut duruma uygular ve kaydeder (kısmi güncelleme
    - core/task_manager.py'nin TaskManager.update() ile aynı desen:
    sadece verilen anahtarlar değişir, gerisi korunur)."""
    with _lock:
        state = get_state()
        state.update(fields)
        state["updated_at"] = datetime.now().isoformat()
        _atomic_write(state)
        return state


def reset_state() -> dict:
    """Sanal Beyin özet sayaçlarını sıfırlar (SADECE bu state.json'u
    etkiler - knowledge/, proposals/, virtual_brain/experiments/ gibi
    kalıcı deney geçmişini SİLMEZ; belgenin §26 'başarısız denemeler
    değerlidir, silinmez' ilkesiyle çelişmemesi için kasıtlı olarak
    ayrı tutuldu)."""
    with _lock:
        now = datetime.now().isoformat()
        fresh = {**DEFAULT_STATE, "created_at": now, "updated_at": now}
        _atomic_write(fresh)
        return fresh


if __name__ == "__main__":
    import pprint
    print("Sanal Beyin - mevcut state:")
    pprint.pprint(get_state())
