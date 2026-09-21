"""base_brain_self_test.py — timeout + heartbeat için çevrimdışı mantık testi.

Gerçek Gemini/Ollama'ya HİÇ dokunmaz - sadece _run_with_timeout()'ın
gerçekten sabit sürede vazgeçtiğini ve BaseBrain.heartbeat()'in
status/_state_changed_at'i doğru izlediğini doğrular. Sahte bir
BaseBrain alt sınıfı kullanır (handle() gerçek bir Gemini çağrısı YAPMAZ).

Çalıştırma:
    cd brains
    python base_brain_self_test.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.brains.base_brain import BaseBrain, BrainError, _run_with_timeout


class _FakeBrain(BaseBrain):
    NAME = "fake_test_brain"
    SYSTEM_PROMPT = "test"

    def handle(self, message: dict) -> dict:
        action = (message.get("payload") or {}).get("action", "ok")
        if action == "sleep":
            time.sleep(0.3)
        if action == "raise":
            raise BrainError("kasıtlı test hatası")
        return self.ok(message, {"echo": True})


def run() -> bool:
    ok = True

    # 1) _run_with_timeout: hızlı fonksiyon sorunsuz döner.
    result = _run_with_timeout(lambda: 1 + 1, timeout=2.0)
    assert result == 2
    print("[OK] _run_with_timeout(): hızlı çağrı normal şekilde sonuç döndürüyor.")

    # 2) _run_with_timeout: yavaş fonksiyon TimeoutError ile KESİLİYOR (sonsuza
    #    kadar beklemiyor) - kullanıcının '1. Timeout sistemi' talebinin özeti.
    def _slow():
        time.sleep(5.0)
        return "asla buraya varmamalı (test çok erken bitmeli)"

    start = time.monotonic()
    try:
        _run_with_timeout(_slow, timeout=0.5)
        print("[FAIL] Yavaş çağrı TimeoutError fırlatmadı!")
        ok = False
    except TimeoutError:
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Timeout çok geç geldi ({elapsed:.1f}s) - sonsuza kadar bekleme riski hâlâ var!"
        print(f"[OK] Yavaş çağrı {elapsed:.2f}sn içinde TimeoutError ile kesildi (5sn beklenmedi).")

    # 3) heartbeat(): idle -> running -> idle geçişleri ve süre izleme.
    brain = _FakeBrain()
    hb = brain.heartbeat()
    assert hb["status"] == "idle" and hb["name"] == "fake_test_brain"
    print(f"[OK] Başlangıç heartbeat: {hb}")

    time.sleep(0.2)
    hb2 = brain.heartbeat()
    assert hb2["seconds_in_state"] >= 0.2, "seconds_in_state zamanla artmıyor!"
    print(f"[OK] Aynı durumda geçen süre doğru artıyor: {hb2['seconds_in_state']}s")

    resp = brain.call({"message_id": "m1", "from": "test", "task": "ok", "payload": {"action": "ok"}})
    assert resp["status"] == "completed"
    hb3 = brain.heartbeat()
    assert hb3["status"] == "idle", "başarılı bir call() sonrası durum 'idle' olmalı!"
    assert hb3["seconds_in_state"] < 0.5, "call() sonrası _state_changed_at güncellenmedi!"
    print("[OK] call() sonrası heartbeat 'idle'a döndü ve süre sıfırlandı.")

    resp_err = brain.call({"message_id": "m2", "from": "test", "task": "raise", "payload": {"action": "raise"}})
    assert resp_err["status"] == "failed"
    hb4 = brain.heartbeat()
    assert hb4["status"] == "error" and hb4["last_error"] == "kasıtlı test hatası"
    print("[OK] Hatalı bir call() sonrası heartbeat 'error' durumunu ve mesajını doğru yansıtıyor.")

    return ok


if __name__ == "__main__":
    success = run()
    print("\n=== SONUÇ:", "BAŞARILI" if success else "BAŞARISIZ", "===")
    sys.exit(0 if success else 1)
