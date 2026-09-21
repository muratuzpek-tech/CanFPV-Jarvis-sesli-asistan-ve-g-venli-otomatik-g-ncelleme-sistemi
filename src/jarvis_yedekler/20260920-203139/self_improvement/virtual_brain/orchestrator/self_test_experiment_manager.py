"""self_test_experiment_manager.py — AŞAMA C için ÇEVRİMDIŞI mantık testi.

self_test.py (AŞAMA B) ile AYNI ilke: gerçek core.brain_orchestrator.
get_orchestrator()'ı ÇAĞIRMAZ, gerçek Gemini/network çağrısı yapmaz.
Sahte (mock) bir bus ile ExperimentManager'ın TAM aşama zincirini
(HYPOTHESIS -> RESEARCH -> AUDIT -> SECURITY -> AWAITING_SANDBOX) uçtan
uca doğrular.

Çalıştırma:
    cd self_improvement/virtual_brain/orchestrator
    python self_test_experiment_manager.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.self_improvement.virtual_brain.orchestrator.self_test import _FakeBus
from jarvis.self_improvement.virtual_brain.orchestrator.experiment_task_manager import ExperimentTaskManager
from jarvis.self_improvement.virtual_brain.orchestrator.virtual_orchestrator import VirtualOrchestrator
from jarvis.self_improvement.virtual_brain.orchestrator import experiment_manager as em_module
from jarvis.self_improvement.virtual_brain.orchestrator.experiment_manager import ExperimentManager


def run() -> bool:
    ok = True
    tmp_dir = Path(tempfile.mkdtemp(prefix="vb_self_test_em_"))
    try:
        # hypotheses.jsonl ve reports/ gerçek self_improvement/virtual_brain
        # altına değil, geçici bir klasöre yazılsın diye modül-seviyesi
        # yolları test süresince geçiciye yönlendiriyoruz.
        original_hyp_path = em_module.HYPOTHESES_PATH
        original_reports_dir = em_module.REPORTS_DIR
        em_module.HYPOTHESES_PATH = tmp_dir / "hypotheses" / "hypotheses.jsonl"
        em_module.REPORTS_DIR = tmp_dir / "reports"

        vo = VirtualOrchestrator(bus=_FakeBus())
        vo.experiments = ExperimentTaskManager(path=tmp_dir / "experiments.json")
        mgr = ExperimentManager(vo=vo)

        exp = mgr.start("Hafıza sistemini iyileştir", "Yeni yöntem daha hızlı olabilir")
        assert exp["payload"]["stage"] == "HYPOTHESIS"
        print(f"[OK] Deney başlatıldı: {exp['id']} (stage=HYPOTHESIS)")

        assert em_module.HYPOTHESES_PATH.is_file(), "hypotheses.jsonl yazılmadı!"
        hyp_line = em_module.HYPOTHESES_PATH.read_text(encoding="utf-8").strip()
        assert exp["id"] in hyp_line
        print("[OK] Hipotez, deneyin geri kalanından BAĞIMSIZ olarak hypotheses.jsonl'a kaydedildi.")

        exp = mgr.advance(exp["id"])
        assert exp["payload"]["stage"] == "RESEARCH"
        assert exp["payload"]["research_sources"] == []  # _FakeBus research_ai sources=[] döndürüyor
        print("[OK] HYPOTHESIS -> RESEARCH ilerledi.")

        exp = mgr.advance(exp["id"])
        assert exp["payload"]["stage"] == "AUDIT"
        assert exp["payload"]["auditor_result"]["passed"] is True
        print("[OK] RESEARCH -> AUDIT ilerledi (auditor_result dolduruldu).")

        exp = mgr.advance(exp["id"])
        assert exp["payload"]["stage"] == "SECURITY"
        assert exp["payload"]["security_result"]["risk"] == "low"
        print("[OK] AUDIT -> SECURITY ilerledi (security_result dolduruldu).")

        exp = mgr.advance(exp["id"])
        assert exp["payload"]["stage"] == "AWAITING_SANDBOX"
        assert exp["status"] == "waiting_approval"
        assert "Sandbox Controller" in exp["payload"]["final_decision"]
        print("[OK] SECURITY -> AWAITING_SANDBOX ilerledi (final_decision dürüstçe 'sandbox bekleniyor' diyor).")

        report_path = em_module.REPORTS_DIR / f"{exp['id']}.md"
        assert report_path.is_file(), "Deney raporu yazılmadı!"
        report_text = report_path.read_text(encoding="utf-8")
        assert "EXPERIMENT REPORT" in report_text and exp["id"] in report_text
        print(f"[OK] §39 formatında deney raporu yazıldı: {report_path.name}")

        # Terminal aşamadan sonra advance() bir şey değiştirmemeli (idempotent).
        exp_again = mgr.advance(exp["id"])
        assert exp_again["payload"]["stage"] == "AWAITING_SANDBOX"
        print("[OK] AWAITING_SANDBOX terminal - tekrar advance() çağrısı durumu bozmuyor.")

        # run_to_awaiting_sandbox: baştan başlayan ikinci bir deneyle uçtan uca kısayol testi.
        exp2 = mgr.start("İkinci test hedefi", "İkinci hipotez")
        exp2 = mgr.run_to_awaiting_sandbox(exp2["id"])
        assert exp2["payload"]["stage"] == "AWAITING_SANDBOX"
        print(f"[OK] run_to_awaiting_sandbox() tek çağrıda tüm zinciri ilerletti ({exp2['id']}).")

    except AssertionError as e:
        print(f"[FAIL] {e}")
        ok = False
    finally:
        em_module.HYPOTHESES_PATH = original_hyp_path
        em_module.REPORTS_DIR = original_reports_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return ok


if __name__ == "__main__":
    success = run()
    print("\n=== SONUÇ:", "BAŞARILI" if success else "BAŞARISIZ", "===")
    sys.exit(0 if success else 1)
