"""watchdog_self_test.py — core/watchdog.py için çevrimdışı mantık testi.

Gerçek Gemini/brains'e HİÇ dokunmaz - sadece core.task_manager.TaskManager'ı
geçici bir dosyaya yönlendirip watchdog.scan_and_apply()'ın doğru
kararları verdiğini doğrular.

Çalıştırma:
    cd core
    python watchdog_self_test.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.core.task_manager import TaskManager
from jarvis.core import watchdog


def _age_task(tm: TaskManager, task_id: str, seconds_ago: float) -> None:
    """Testte gerçekten dakikalarca beklemek yerine, updated_at'i doğrudan
    geçmişe taşımak için (sadece test amaçlı) dosyayı elle düzenler."""
    tasks = tm._load()
    for t in tasks:
        if t["id"] == task_id:
            t["updated_at"] = (datetime.now() - timedelta(seconds=seconds_ago)).isoformat()
    tm._save(tasks)


def run() -> bool:
    ok = True
    tmp_dir = Path(tempfile.mkdtemp(prefix="watchdog_self_test_"))
    try:
        tm = TaskManager(path=tmp_dir / "brain_tasks.json")

        fresh = tm.create(name="taze görev", agent="planner_ai", payload={"goal": "x"})
        stalled = tm.create(name="takılmış görev", agent="planner_ai", payload={"goal": "y"})
        dead = tm.create(name="ölü görev", agent="planner_ai", payload={"goal": "z"})
        done = tm.create(name="bitmiş görev", agent="planner_ai", payload={"goal": "w"})
        tm.update(done["id"], status="completed")

        _age_task(tm, stalled["id"], watchdog.STALL_WARNING_SECONDS + 60)
        _age_task(tm, dead["id"], watchdog.DEAD_TASK_SECONDS + 60)
        # done kasıtlı olarak eskitilmedi bile - terminal durumdaki bir
        # görev ne kadar eski olursa olsun watchdog'un işi değil.
        _age_task(tm, done["id"], watchdog.DEAD_TASK_SECONDS + 999)

        actions = watchdog.scan_and_apply(tm)
        action_ids = {(a["task_id"], a["action"]) for a in actions}

        assert (stalled["id"], "marked_stalled") in action_ids, "stalled görev işaretlenmedi!"
        assert (dead["id"], "marked_dead") in action_ids, "dead görev işaretlenmedi!"
        assert not any(tid == fresh["id"] for tid, _ in action_ids), "taze göreve DOKUNULMAMALIYDI!"
        assert not any(tid == done["id"] for tid, _ in action_ids), "terminal görev watchdog'un konusu DEĞİL!"
        print("[OK] scan_and_apply(): taze/stalled/dead/terminal görevler doğru ayırt edildi.")

        assert tm.get(dead["id"])["status"] == "failed", "dead görev 'failed' yapılmadı!"
        assert "Watchdog" in tm.get(dead["id"])["error"]
        print("[OK] Dead-task otomatik 'failed' yapıldı (kuyruk artık bloke olmayacak).")

        assert tm.get(fresh["id"])["status"] == "pending", "taze görevin durumu DEĞİŞMEMELİYDİ!"
        assert tm.get(stalled["id"])["status"] == "pending", "stalled görev SADECE işaretlenmeli, failed OLMAMALI!"
        assert tm.get(stalled["id"])["payload"].get("stalled") is True
        print("[OK] Stalled görev sadece işaretlendi, durumu bozulmadı (hâlâ ilerleyebilir).")

        # İkinci bir tarama: stalled görev tekrar 'marked_stalled' üretmemeli (idempotent).
        actions2 = watchdog.scan_and_apply(tm)
        assert not any(a["task_id"] == stalled["id"] for a in actions2), \
            "aynı stalled görev tekrar tekrar işaretlenmemeli (log gürültüsü olur)!"
        print("[OK] Tekrarlanan tarama idempotent (aynı görevi tekrar tekrar işaretlemiyor).")

    except AssertionError as e:
        print(f"[FAIL] {e}")
        ok = False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return ok


if __name__ == "__main__":
    success = run()
    print("\n=== SONUÇ:", "BAŞARILI" if success else "BAŞARISIZ", "===")
    sys.exit(0 if success else 1)
