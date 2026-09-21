"""virtual_orchestrator.py — SANAL BEYİN YARDIMCI ORCHESTRATOR (AŞAMA B).

"JARVIS — FAZ 9 Uyumlu Sanal Beyin / Digital Twin Geliştirme Promptu"
belgesinin §8 (Sanal Beyin Orchestrator) ve §9 (Message Bus Uyumu)
maddelerinin uygulanışı.

TASARIM — BU MODÜL NE YAPAR, NE YAPMAZ:

  * Kendi MessageBus'ını icat ETMEZ. Gerçek core.brain_orchestrator'ın
    ZATEN çalışan tekil (singleton) örneğinin gerçek, ZATEN kayıtlı
    beyinleri barındıran MessageBus'ını (`.bus`) kullanır — böylece
    beyinler iki kere tanımlanmaz, mesaj formatı ve loglama
    (logs/message_bus.jsonl) TEK bir yerde kalır (§9).

  * Gerçek Orchestrator'ı BYPASS ETMEZ: sadece onun ZATEN sağladığı
    `bus.send()` arayüzünü kullanır, `core/brain_orchestrator.py`'nin
    kendi `_tick()` döngüsüne, `tasks/brain_tasks.json`'a ya da
    onay/risk mantığına hiç dokunmaz.

  * SADECE salt-okunur/danışma niteliğindeki beyinlere mesaj göndermeye
    izin verir: research_ai (internet araştırması), security_ai (risk
    değerlendirmesi), auditor_ai (sonuç denetimi). coder_ai, executor_ai,
    planner_ai, memory_ai bu aşamada BİLEREK ALLOWLIST DIŞI bırakıldı -
    bunlar gerçek dosya değiştirir/gerçek eylem çalıştırır/gerçek
    hafızaya yazar; Sanal Beyin'in onlara erişimi ancak AŞAMA D (Sandbox
    Controller) + AŞAMA H (Proposal) + kullanıcı onayı zinciri
    kurulduktan SONRA, ayrı bir onayla açılmalı (belgenin §43 "hiçbir
    başarılı deney otomatik olarak production değişikliğine dönüşmez"
    ilkesi).

UYARI (ÖNEMLİ - test ederken dikkat): `get_real_bus()`,
`core.brain_orchestrator.get_orchestrator()` çağırır. Bu fonksiyon,
eğer gerçek Jarvis (main.py) bu process içinde ZATEN çalışmıyorsa,
GERÇEK bir BrainOrchestrator örneği YARATIR ve arka plan tick döngüsünü
(gerçek API anahtarlarıyla, gerçek tasks/brain_tasks.json üzerinde)
BAŞLATIR. Bu yüzden bu modülü main.py'den BAĞIMSIZ, tek başına
(`python virtual_orchestrator.py` gibi) çalıştırmayın/test etmeyin -
sadece gerçek Jarvis zaten ayaktayken, ondan çağrılan bir komut
içinden kullanın. Bağımsız/offline testler için bkz. self_test.py
(gerçek Orchestrator'a HİÇ dokunmaz, sahte/mock bir bus kullanır).
"""
from __future__ import annotations

import sys
from pathlib import Path

# core/, brains/ vb. gerçek Jarvis paketlerine erişebilmek için proje
# kökünü sys.path'e ekliyoruz (bu modül self_improvement/virtual_brain/
# orchestrator/ altında, proje kökü 3 seviye yukarısı).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.self_improvement.virtual_brain.orchestrator.experiment_task_manager import ExperimentTaskManager
from jarvis.self_improvement.virtual_brain.brain_state import state_manager

# §8: Sanal Beyin'in bu aşamada mesaj gönderebileceği TEK beyinler -
# hepsi salt-okunur/danışma niteliğinde (dosya değiştirmez, eylem
# çalıştırmaz, hafızaya yazmaz).
ALLOWED_BRAINS = frozenset({"research_ai", "security_ai", "auditor_ai"})


class VirtualBrainSafetyError(Exception):
    """ALLOWED_BRAINS dışında bir beyne erişim denendiğinde fırlatılır.
    Bu, koddaki bir hatadan değil, BİLİNÇLİ bir güvenlik sınırından
    kaynaklanır - bkz. dosya başı not."""


def get_real_bus():
    """Gerçek Orchestrator'ın (zaten çalışan) MessageBus'ını döndürür.
    bkz. dosya başındaki UYARI - bunu sadece gerçek Jarvis zaten
    çalışırken çağırın."""
    from jarvis.core.brain_orchestrator import get_orchestrator
    return get_orchestrator().bus


def send_to_real_brain(agent: str, task: str, payload: dict, bus=None) -> dict:
    """Gerçek bir beyne (SADECE ALLOWED_BRAINS içindeyse) mesaj gönderir.
    `bus` verilmezse get_real_bus() ile gerçek, çalışan Orchestrator'ın
    bus'ı kullanılır."""
    if agent not in ALLOWED_BRAINS:
        raise VirtualBrainSafetyError(
            f"'{agent}' bu aşamada Sanal Beyin'e KAPALI (izinli: {sorted(ALLOWED_BRAINS)}). "
            f"coder_ai/executor_ai/planner_ai/memory_ai erişimi ancak sandbox + onay zinciri "
            f"kurulduktan sonra, ayrı bir kullanıcı onayıyla açılabilir (bkz. modül dosya başı notu)."
        )
    bus = bus or get_real_bus()
    return bus.send("virtual_orchestrator", agent, task, payload=payload)


class VirtualOrchestrator:
    """§8'deki 'yardımcı orchestrator': deney başlatır, izinli beyinlere
    görev verir, sonuçları toplar, rapor için deney kaydına yazar.
    Deney YAŞAM DÖNGÜSÜ yönetimi (retry, çok adımlı plan vb.) AŞAMA C'nin
    (Experiment Manager) konusu - bu sınıf sadece TEK adımlık, doğrudan
    çağrılara odaklanır."""

    def __init__(self, bus=None) -> None:
        self._bus = bus  # None ise her çağrıda get_real_bus() kullanılır
        self.experiments = ExperimentTaskManager()

    def start_experiment(self, objective: str, hypothesis: str = "") -> dict:
        """§11: yeni bir deney kaydı açar (durum: pending)."""
        exp = self.experiments.create(
            name=objective,
            payload={"objective": objective, "hypothesis": hypothesis},
        )
        state_manager.update_state(
            experiments_count=state_manager.get_state()["experiments_count"] + 1,
            latest_experiment_id=exp["id"],
            latest_experiment_result=None,
        )
        return exp

    def run_research_step(self, experiment_id: str, query: str) -> dict:
        """Deney için gerçek research_ai'ye GERÇEK bir araştırma sorusu
        gönderir (research_ai salt-okunur - internet arar, hiçbir dosyayı
        değiştirmez, bu yüzden bu aşamada GERÇEK çağrı güvenlidir)."""
        exp = self._require_experiment(experiment_id)
        state_manager.update_state(research_status="RUNNING")
        try:
            resp = send_to_real_brain("research_ai", query, {"query": query}, bus=self._bus)
        finally:
            state_manager.update_state(research_status="IDLE")

        history = exp["payload"].setdefault("history", [])
        history.append({"type": "research", "query": query, "response": resp})
        self.experiments.update(experiment_id, payload=exp["payload"])
        return resp

    def run_security_check(self, experiment_id: str, tool: str, action: str | None, target: str) -> dict:
        """Deney için gerçek security_ai'den bir risk değerlendirmesi ister
        (security_ai da salt-okunur - sadece ALLOW/BLOCK/REVIEW döner,
        hiçbir şeyi kendisi uygulamaz)."""
        exp = self._require_experiment(experiment_id)
        resp = send_to_real_brain(
            "security_ai", "sanal beyin risk değerlendirmesi",
            {"tool": tool, "action": action, "target": target}, bus=self._bus,
        )
        result = resp.get("result", {}) if resp.get("status") == "completed" else {}
        exp["payload"]["security_level"] = result.get("risk", "high")
        history = exp["payload"].setdefault("history", [])
        history.append({"type": "security", "tool": tool, "action": action, "target": target, "response": resp})
        self.experiments.update(experiment_id, payload=exp["payload"])
        return resp

    def run_audit(self, experiment_id: str, step_description: str, agent_result) -> dict:
        """Deney sonucunu gerçek auditor_ai'ye denetletir (auditor_ai de
        salt-okunur - sadece passed/failed + gerekçe döner)."""
        exp = self._require_experiment(experiment_id)
        resp = send_to_real_brain(
            "auditor_ai", "sanal beyin deney denetimi",
            {"step_description": step_description, "agent_result": agent_result}, bus=self._bus,
        )
        result = resp.get("result", {}) if resp.get("status") == "completed" else {}
        exp["payload"]["audit_result"] = result
        history = exp["payload"].setdefault("history", [])
        history.append({"type": "audit", "step_description": step_description, "response": resp})
        self.experiments.update(experiment_id, payload=exp["payload"])
        state_manager.update_state(
            audits_count=state_manager.get_state()["audits_count"] + 1,
        )
        return resp

    def finish_experiment(self, experiment_id: str, status: str, result_summary: str) -> dict:
        if status not in ("completed", "failed", "cancelled", "rollback"):
            raise ValueError(f"finish_experiment: geçersiz durum {status!r}")
        exp = self.experiments.update(experiment_id, status=status, result=result_summary)
        state_manager.update_state(latest_experiment_result=result_summary)
        return exp

    def _require_experiment(self, experiment_id: str) -> dict:
        exp = self.experiments.get(experiment_id)
        if exp is None:
            raise KeyError(f"'{experiment_id}' id'li deney bulunamadı.")
        return exp
