"""memory_ai.py — MEMORY AI: Hafıza Beyni.

Görevi (bölüm 6): mevcut memory_manager.py sistemini kullanarak önemli
kararları, tamamlanan/başarısız görevleri, kullanıcı tercihlerini, proje
bilgilerini ve AI'ların geçmiş sonuçlarını hafızaya kaydetmek; diğer AI'lar
gerektiğinde bilgi isteyebilmeli.

ÖNEMLİ TASARIM NOTU: memory/memory_manager.py KASITLI OLARAK küçük ve sıkı
sınırlı (toplam ~2200 karakter, kullanıcı hakkında kimlik/tercih/proje gibi
KALICI bilgiler için) - "mevcut hafıza sistemi değiştirilmemeli" talimatına
uyularak bu dosyaya HİÇ dokunulmadı. Bu yüzden Memory AI iki katmanlı
çalışır:
  1. Takımın KENDİ detaylı görev/mesaj geçmişi -> tasks/brain_memory.json
     (ayrı, sınırsız-ölçekli bir günlük - memory_manager'ın 2200 karakter
     sınırını asla zorlamaz).
  2. SADECE gerçekten kullanıcıyla ilgili, kalıcı bir gerçek ortaya
     çıktığında (ör. "YolPaylaş projesi gelistiriliyor") mevcut
     memory_manager.remember() ile GERÇEK hafızaya, KISACA yazılır.
Diğer beyinler tüm konuşma geçmişini almaz (19. bölüm) - recall() sadece
ilgili, son ve kısa bir özet döner, token tüketimini azaltır.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from jarvis.brains.base_brain import BaseBrain, BrainError
from jarvis.paths import tasks_dir


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
BRAIN_MEMORY_PATH = tasks_dir() / "brain_memory.json"
MAX_ENTRIES = 500
_lock = threading.Lock()

SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın HAFIZA BEYNİsin (memory_ai).

GÖREVİN: Sana verilen bir olay/sonucu (görev tamamlandı, karar alındı, vb.)
KISA, ARAMA İÇİN KULLANIŞLI bir özet cümlesine dönüştürmek. Ayrıca bu
bilginin kullanıcının KALICI kişisel/proje hafızasına (isim, tercih, aktif
proje gibi) girmesi GEREKİP gerekmediğini belirt - sadece GERÇEKTEN kalıcı
ve kullanıcıyla ilgiliyse "durable": true de, gündelik/geçici bir görev
detayıysa "durable": false de.

SADECE şu JSON şemasında dön:
{"summary": "...", "durable": true|false, "durable_key": "...", "durable_category": "projects|notes"}"""


class MemoryAI(BaseBrain):
    NAME = "memory_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    # ── Takımın kendi (sınırsız) geçmişi ────────────────────────────────
    @staticmethod
    def _load_entries() -> list[dict]:
        try:
            if BRAIN_MEMORY_PATH.is_file():
                data = json.loads(BRAIN_MEMORY_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    @staticmethod
    def _save_entries(entries: list[dict]) -> None:
        BRAIN_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        entries = entries[-MAX_ENTRIES:]
        with tempfile.NamedTemporaryFile(
            "w", dir=BRAIN_MEMORY_PATH.parent, delete=False, encoding="utf-8", suffix=".tmp",
        ) as tmp:
            json.dump(entries, tmp, indent=2, ensure_ascii=False)
            temp_name = tmp.name
        Path(temp_name).replace(BRAIN_MEMORY_PATH)

    def remember_event(self, agent: str, event: str, detail: str) -> None:
        """Diğer beyinler/orchestrator, kendi başarı/başarısızlıklarını
        buraya kaydeder - LLM çağrısı GEREKTİRMEZ, her zaman çalışır."""
        with _lock:
            entries = self._load_entries()
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "agent": agent, "event": event, "detail": detail[:500],
            })
            self._save_entries(entries)

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """SADECE ilgili son kayıtları döner - tüm geçmişi değil (19. bölüm:
        token tüketimini azaltmak için sadece ihtiyaç duyulan bilgi)."""
        entries = self._load_entries()
        query_l = query.lower().strip()
        if query_l:
            matches = [e for e in entries if query_l in json.dumps(e, ensure_ascii=False).lower()]
        else:
            matches = entries
        return matches[-limit:]

    # ── BaseBrain arayüzü: bir "hatırla/kaydet" isteği ──────────────────
    def handle(self, message: dict) -> dict:
        payload = message.get("payload") or {}
        action = payload.get("action", "remember")

        if action == "recall":
            query = payload.get("query", "")
            found = self.recall(query, limit=payload.get("limit", 5))
            return self.ok(message, {"entries": found})

        # action == "remember" (varsayilan)
        agent = payload.get("agent", message.get("from", "unknown"))
        event = payload.get("event", "info")
        detail = payload.get("detail", "")
        if not detail:
            raise BrainError("memory_ai: 'detail' parametresi boş olamaz.")

        self.remember_event(agent, event, detail)

        durable_written = False
        try:
            judged = self.call_llm_json(f"OLAY: agent={agent} event={event} detay={detail[:800]}")
            if isinstance(judged, dict) and judged.get("durable"):
                from jarvis.memory.memory_manager import remember as memory_remember
                key = (judged.get("durable_key") or event)[:40]
                category = judged.get("durable_category") if judged.get("durable_category") in (
                    "projects", "notes") else "notes"
                memory_remember(key, judged.get("summary", detail)[:380], category=category)
                durable_written = True
        except BrainError:
            pass  # LLM basarisiz olsa bile olay zaten tasks/brain_memory.json'a yazildi

        self.log(f"Olay kaydedildi: agent={agent} event={event} durable={durable_written}")
        return self.ok(message, {"saved": True, "durable_written": durable_written})
