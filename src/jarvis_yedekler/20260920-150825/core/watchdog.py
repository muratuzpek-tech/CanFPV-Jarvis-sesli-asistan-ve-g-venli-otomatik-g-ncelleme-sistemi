"""watchdog.py — GÖREV BEKÇİSİ (FAZ 1 sağlamlaştırması).

Kullanıcı talimatı: "Task watchdog: Uzun süre ilerlemeyen görevleri tespit
etmeli" ve "Dead-task detection: 'Görev eklendi' deyip sonsuza kadar
bekleyen görevler otomatik tespit edilmeli."

core/task_manager.py'nin görev kaydı zaten her değişiklikte "updated_at"
alanını güncelliyor (bkz. TaskManager.update()) - bu modül YENİ bir alan
icat etmeden, SADECE bu mevcut alanı kullanarak iki eşiği uygular:

  * STALL_WARNING_SECONDS'ı aşan ama henüz DEAD_TASK_SECONDS'a ulaşmamış
    bir görev "stalled" (takılmış) olarak İŞARETLENİR (payload'a
    "stalled": true + "stalled_since" eklenir) ve loglanır - durumu
    DEĞİŞTİRİLMEZ, çünkü hâlâ ilerliyor olabilir (ör. yavaş bir Gemini
    çağrısı ortasında).
  * DEAD_TASK_SECONDS'ı aşan bir görev artık gerçekten ölü kabul edilir:
    core/brain_orchestrator.py'nin _tick() döngüsü SADECE pending[0]'ı
    işlediği için (bkz. o dosyanın başlık yorumu), takılı kalmış TEK bir
    görev sonsuza kadar TÜM kuyruğu bloke edebilir - bu fonksiyon böyle
    bir görevi "failed" olarak işaretleyip kuyruğu açar.

Bilerek YAPILMAYAN şey: bu modül hiçbir arka plan thread'i başlatmaz -
sadece saf, senkron bir fonksiyon (`scan_and_apply`) sunar; ne zaman
çağrılacağına (ör. her _tick() turunda bir kez) çağıran karar verir -
agent_loop.py/brain_orchestrator.py'nin "tek noktadan, tek thread'den
ilerleme" deseniyle tutarlı (bkz. brain_orchestrator.py dosya başı notu).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from jarvis.paths import logs_dir

# Görev "pending"/"running"/"waiting_approval" durumunda takılı kabul
# edilmeye başladığı eşik - bu süreden sonra SADECE işaretlenir, durumu
# değişmez (hâlâ ilerliyor olabilir).
STALL_WARNING_SECONDS = 30 * 60      # 30 dakika

# Bu süreden sonra görev artık "ölü" kabul edilir ve otomatik "failed"
# yapılır - kuyruğun sonsuza kadar bloke kalmasını önlemek için.
DEAD_TASK_SECONDS = 2 * 60 * 60      # 2 saat

# _tick()'in ilerletebileceği "aktif" durumlar - completed/failed/cancelled
# zaten terminal, watchdog'un onlarla işi yok.
_ACTIVE_STATUSES = {"pending", "running"}


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


LOGS_DIR = logs_dir()


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("jarvis.watchdog")
    if not logger.handlers:
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(LOGS_DIR / "watchdog.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        except Exception:
            pass
    return logger


_logger = _make_logger()


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def check_task(task: dict, now: datetime) -> str | None:
    """Saf fonksiyon (yan etkisi yok, test edilmesi kolay): bir görev
    kaydına bakıp 'dead' | 'stall' | None döndürür. Karar SADECE status +
    updated_at'e dayanır - başka hiçbir alana bağımlı değil."""
    if task.get("status") not in _ACTIVE_STATUSES:
        return None
    updated_at = _parse_iso(task.get("updated_at", ""))
    if updated_at is None:
        return None
    elapsed = (now - updated_at).total_seconds()
    if elapsed >= DEAD_TASK_SECONDS:
        return "dead"
    if elapsed >= STALL_WARNING_SECONDS:
        return "stall"
    return None


def scan_and_apply(task_manager, now: datetime | None = None) -> list[dict]:
    """task_manager.list()'teki HER aktif görevi tarar. 'dead' bulunanları
    otomatik 'failed' yapar (kuyruğu açar); 'stall' bulunanları sadece
    işaretler/loglar. Uygulanan aksiyonların listesini döndürür (loglama/
    test için) - hiçbir exception'ı çağırana sızdırmaz (FAZ 1'in temel
    ilkesiyle tutarlı: bir yardımcı bileşenin hatası ana motoru asla
    durdurmamalı)."""
    now = now or datetime.now()
    actions: list[dict] = []
    try:
        tasks = task_manager.list()
    except Exception as e:
        _logger.warning(f"Görev listesi okunamadı, tarama atlandı: {e}")
        return actions

    for task in tasks:
        try:
            verdict = check_task(task, now)
            if verdict is None:
                continue

            task_id = task["id"]
            name = task.get("name", "")[:80]

            if verdict == "dead":
                elapsed_h = (now - _parse_iso(task["updated_at"])).total_seconds() / 3600.0
                reason = (
                    f"Watchdog: görev {elapsed_h:.1f} saattir ilerlemedi "
                    f"(son güncelleme: {task['updated_at']}) - otomatik olarak başarısız işaretlendi."
                )
                task_manager.update(task_id, status="failed", error=reason)
                _logger.warning(f"[DEAD-TASK] '{task_id}' ({name!r}) -> failed. {reason}")
                actions.append({"task_id": task_id, "action": "marked_dead", "reason": reason})

            elif verdict == "stall":
                payload = task.get("payload") or {}
                if not payload.get("stalled"):
                    payload["stalled"] = True
                    payload["stalled_since"] = now.isoformat()
                    task_manager.update(task_id, payload=payload)
                    _logger.warning(
                        f"[STALL] '{task_id}' ({name!r}) {STALL_WARNING_SECONDS // 60} "
                        f"dakikadır ilerlemedi - işaretlendi (henüz otomatik başarısız yapılmadı)."
                    )
                    actions.append({"task_id": task_id, "action": "marked_stalled"})
        except Exception as e:
            # Tek bir görevi işlerken hata olsa bile diğer görevlerin
            # taranmasını ENGELLEMEMELİ.
            _logger.warning(f"Görev '{task.get('id', '?')}' taranırken hata: {e}")
            continue

    return actions
