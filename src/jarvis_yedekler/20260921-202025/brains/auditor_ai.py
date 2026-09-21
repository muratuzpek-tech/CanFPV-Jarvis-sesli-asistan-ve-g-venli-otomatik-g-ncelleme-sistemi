"""auditor_ai.py — AUDITOR AI: Denetçi Beyin.

Görevi (bölüm 8): diğer AI'ların sonuçlarını kontrol etmek - plan mantıklı
mı, araştırma yeterli mi, kod doğru mu, test başarılı mı, sonuç istenen
görevle uyuşuyor mu. Hata varsa görevi geri gönderebilir.

Deterministik kontroller ÖNCE yapılır (kod için ast.parse zaten
coder_ai'de yapıldı ve sonuçta 'written' alanında görünür; araştırma için
boş findings listesi tespiti gibi) - Gemini'ye SADECE bu deterministik
kontroller geçtikten sonra, nihai bir "mantıklı mı" değerlendirmesi için
danışılır. Maksimum tekrar sayısı brain_orchestrator.py'de MAX_AUDIT_ROUNDS
ile sınırlanır (sonsuz coder<->auditor döngüsünü önler)."""
from __future__ import annotations

from jarvis.brains.base_brain import BaseBrain, BrainError

SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın DENETÇİ BEYNİsin (auditor_ai).

Sana bir görev tanımı ve o görevi yapan beynin ürettiği sonuç verilecek.
Görevin: sonucun GERÇEKTEN istenen görevi karşılayıp karşılamadığını
değerlendirmek. Şüpheci ol - "muhtemelen doğrudur" deme, sonucu göreve
karşı gerçekten kontrol et.

SADECE şu JSON şemasında dön:
{"passed": true|false, "reason": "...", "retry_hint": "eğer passed=false ise, ilgili beyne ne söylenmeli"}"""


class AuditorAI(BaseBrain):
    NAME = "auditor_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def handle(self, message: dict) -> dict:
        payload = message.get("payload") or {}
        step_description = payload.get("step_description", "").strip()
        agent_result = payload.get("agent_result")

        if not step_description or agent_result is None:
            raise BrainError("auditor_ai: 'step_description' ve 'agent_result' zorunlu.")

        # Deterministik on-kontroller (Gemini'ye gitmeden once ele
        # alinabilecek, net durumlar):
        if isinstance(agent_result, dict):
            if agent_result.get("status") == "failed":
                return self.ok(message, {
                    "passed": False,
                    "reason": f"Alt beyin zaten başarısız bildirdi: {agent_result.get('result')}",
                    "retry_hint": "Hata giderilip tekrar denenmeli.",
                })
            inner = agent_result.get("result", agent_result)
            if isinstance(inner, dict) and inner.get("agent") == "research_ai" and not inner.get("findings"):
                return self.ok(message, {
                    "passed": False,
                    "reason": "Araştırma sonucu boş (findings listesi boş).",
                    "retry_hint": "Farklı/daha geniş bir sorguyla tekrar araştırılmalı.",
                })

        judged = self.call_llm_json(
            f"GÖREV: {step_description}\n\nÜRETİLEN SONUÇ:\n{agent_result}"
        )
        if not isinstance(judged, dict) or "passed" not in judged:
            raise BrainError(f"auditor_ai: model beklenen şemayı döndürmedi: {judged!r}")

        self.log(f"Denetim: {step_description[:60]!r} -> passed={judged.get('passed')}")
        return self.ok(message, judged)
