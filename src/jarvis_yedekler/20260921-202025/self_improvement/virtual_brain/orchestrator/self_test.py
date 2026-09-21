"""self_test.py — AŞAMA B için ÇEVRİMDIŞI mantık testi.

Bu betik "ANALİZ -> KOD -> TEST -> RAPOR -> DUR" adımlarının (belge §42)
TEST bölümüdür. BİLEREK gerçek core.brain_orchestrator.get_orchestrator()
'ı ÇAĞIRMAZ - o çağrı gerçek Gemini API anahtarı ister ve (Jarvis zaten
çalışmıyorsa) gerçek arka plan tick döngüsünü başlatır. Bunun yerine sahte
(mock) bir bus + sahte beyinlerle SADECE bu paketin KENDİ mantığını
(ExperimentTaskManager'ın ayrı dosyaya yazması, VirtualOrchestrator'ın
ALLOWED_BRAINS güvenlik sınırı, experiment ID üretimi) doğrular.

Gerçek research_ai/security_ai/auditor_ai'ye GERÇEKTEN bağlanan bir
"canlı duman testi" kasıtlı olarak burada YOK - bu, gerçek Jarvis
çalışırken, gerçek main.py process'i içinden ayrıca yapılmalı (bu dosya
bunun yerine geçmez).

Çalıştırma:
    cd self_improvement/virtual_brain/orchestrator
    python self_test.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.self_improvement.virtual_brain.orchestrator.experiment_task_manager import ExperimentTaskManager
from jarvis.self_improvement.virtual_brain.orchestrator.virtual_orchestrator import (
    VirtualOrchestrator, VirtualBrainSafetyError, ALLOWED_BRAINS,
)
from jarvis.paths import tasks_dir


class _FakeBrain:
    """core/message_bus.py'nin beklediği .call(message) arayüzünü taklit
    eder - gerçek Gemini/network çağrısı yapmaz."""

    def __init__(self, name: str, fixed_result: dict) -> None:
        self.NAME = name
        self._fixed_result = fixed_result

    def call(self, message: dict) -> dict:
        return {
            "message_id": message["message_id"],
            "from": self.NAME,
            "to": message["from"],
            "status": "completed",
            "result": self._fixed_result,
        }


class _FakeBus:
    """core/message_bus.MessageBus ile AYNI .send() imzası - ama sahte
    beyinlere yönlendirir, hiçbir log dosyasına yazmaz, hiçbir gerçek
    API çağrısı yapmaz."""

    def __init__(self) -> None:
        self._agents = {
            "research_ai": _FakeBrain("research_ai", {
                "agent": "research_ai", "status": "completed",
                "findings": ["sahte test bulgusu"], "sources": [], "recommendations": [],
            }),
            "security_ai": _FakeBrain("security_ai", {"risk": "low", "reason": "sahte test"}),
            "auditor_ai": _FakeBrain("auditor_ai", {"passed": True, "reason": "sahte test"}),
            # coder_ai KASITLI OLARAK eklendi - ALLOWED_BRAINS testinin
            # onu gerçekten REDDETTİĞİNİ (bus'a hiç ulaşmadan) doğrulamak için.
            "coder_ai": _FakeBrain("coder_ai", {"written": True}),
        }

    def send(self, from_agent, to_agent, task, payload=None, priority="medium") -> dict:
        brain = self._agents[to_agent]
        return brain.call({"message_id": "test", "from": from_agent, "to": to_agent,
                            "task": task, "payload": payload or {}, "priority": priority})


def run() -> bool:
    ok = True

    # 1) ExperimentTaskManager AYRI bir geçici dosyaya yazmalı, gerçek
    #    tasks/brain_tasks.json'a HİÇ dokunmamalı.
    tmp_dir = Path(tempfile.mkdtemp(prefix="vb_self_test_"))
    try:
        etm = ExperimentTaskManager(path=tmp_dir / "experiments.json")
        exp = etm.create(name="test hedefi", payload={"objective": "test hedefi"})
        assert exp["id"].startswith("EXP-"), f"beklenmeyen id formatı: {exp['id']}"
        assert exp["status"] == "pending"
        fetched = etm.get(exp["id"])
        assert fetched is not None and fetched["id"] == exp["id"]
        etm.update(exp["id"], status="completed", result="ok")
        assert etm.get(exp["id"])["status"] == "completed"
        print(f"[OK] ExperimentTaskManager temel akış çalışıyor (id={exp['id']}).")

        real_tasks_path = tasks_dir() / "brain_tasks.json"
        assert etm.path != real_tasks_path, "KRİTİK: deney dosyası gerçek brain_tasks.json ile aynı olamaz!"
        print("[OK] Deney dosyası gerçek tasks/brain_tasks.json'dan AYRI.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 2) VirtualOrchestrator + sahte bus: izinli beyinler çalışmalı.
    fake_bus = _FakeBus()
    tmp_dir2 = Path(tempfile.mkdtemp(prefix="vb_self_test2_"))
    try:
        vo = VirtualOrchestrator(bus=fake_bus)
        vo.experiments = ExperimentTaskManager(path=tmp_dir2 / "experiments.json")

        exp = vo.start_experiment("Hafıza sistemini iyileştir", hypothesis="Yeni yöntem daha hızlı olabilir")
        resp = vo.run_research_step(exp["id"], "örnek araştırma sorgusu")
        assert resp["status"] == "completed"
        assert resp["result"]["findings"] == ["sahte test bulgusu"]
        print("[OK] research_ai (izinli) üzerinden mesaj gönderme çalışıyor.")

        resp = vo.run_security_check(exp["id"], tool="coder_ai", action="modify_critical_file", target="test.py")
        assert resp["result"]["risk"] == "low"
        print("[OK] security_ai (izinli) üzerinden risk değerlendirmesi çalışıyor.")

        resp = vo.run_audit(exp["id"], "test adımı", {"status": "completed"})
        assert resp["result"]["passed"] is True
        print("[OK] auditor_ai (izinli) üzerinden denetim çalışıyor.")

        vo.finish_experiment(exp["id"], "completed", "sahte test tamamlandı")
        assert vo.experiments.get(exp["id"])["status"] == "completed"
        print("[OK] Deney yaşam döngüsü (start -> research -> security -> audit -> finish) tamamlandı.")

        # 3) GÜVENLİK SINIRI: coder_ai (allowlist DIŞI) KESİNLİKLE reddedilmeli
        #    - fake_bus'ta coder_ai kayıtlı olmasına RAĞMEN, çağrı bus'a hiç
        #    ULAŞMADAN VirtualBrainSafetyError ile durmalı.
        try:
            vo.run_security_check(exp["id"], tool="coder_ai", action="x", target="y")
            from jarvis.self_improvement.virtual_brain.orchestrator.virtual_orchestrator import send_to_real_brain
            send_to_real_brain("coder_ai", "test", {}, bus=fake_bus)
            print("[FAIL] coder_ai çağrısı REDDEDİLMEDİ - güvenlik sınırı çalışmıyor!")
            ok = False
        except VirtualBrainSafetyError:
            print("[OK] coder_ai (allowlist dışı) beklendiği gibi REDDEDİLDİ.")
    finally:
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    assert ALLOWED_BRAINS == frozenset({"research_ai", "security_ai", "auditor_ai"}), \
        "ALLOWED_BRAINS beklenmedik şekilde değişmiş!"
    print(f"[OK] ALLOWED_BRAINS beklendiği gibi: {sorted(ALLOWED_BRAINS)}")

    return ok


if __name__ == "__main__":
    success = run()
    print("\n=== SONUÇ:", "BAŞARILI" if success else "BAŞARISIZ", "===")
    sys.exit(0 if success else 1)
