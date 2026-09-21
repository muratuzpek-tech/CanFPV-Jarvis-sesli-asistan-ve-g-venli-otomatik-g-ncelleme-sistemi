"""Yerel, kalici, kullanici kontrollu zamanlama sistemi — SQLite tabanli.

jarvis_asistan projesinden uyarlanmistir, sonra JSON'dan SQLite'a tasinmistir
(arastirma raporu onerisi: WAL modu ile eszamanli okuma/yazma guvenligi,
atomik islemler, bozulmaya karsi dayaniklilik). Disaridan gorunen fonksiyon
imzalari (add_task, list_tasks, remove_task, pop_due_tasks, task_manager)
ONCEKI JSON surumuyle AYNI - main.py'deki entegrasyonun degismesine gerek yok.

CanFPV Jarvis'in kendi guvenli mekanizmasini (session.send_client_content,
bkz. main.py _run_proactive_mode) kullanarak, zamani gelen komutlari
GERCEKTEN Gemini'ye iletir - sadece bildirim degil, tam calisma.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from jarvis.paths import memory_dir


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DB_PATH = memory_dir() / "scheduled_tasks.db"
_OLD_JSON_PATH = memory_dir() / "scheduled_tasks.json"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    # WAL: okuyucular yazariyi bloklamaz, yazici okuyuculari bloklamaz.
    # Sadece yerel diskte calisir (ag paylasimli dosya sisteminde degil) -
    # burada sorun degil, dosya zaten yerel.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            run_at TEXT NOT NULL,
            command TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done, run_at)")
    return conn


def _migrate_from_json_if_needed() -> None:
    """Eski JSON dosyasi varsa, verileri bir kereye mahsus SQLite'a
    tasir ve JSON'u .migrated uzantisiyla yeniden adlandirir."""
    if not _OLD_JSON_PATH.exists():
        return
    import json
    try:
        rows = json.loads(_OLD_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not rows:
        _OLD_JSON_PATH.rename(_OLD_JSON_PATH.with_suffix(".json.migrated"))
        return
    conn = _connect()
    try:
        with conn:
            for row in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO tasks (id, run_at, command, done) VALUES (?, ?, ?, ?)",
                    (row.get("id", uuid.uuid4().hex[:8]), row["run_at"], row["command"],
                     1 if row.get("done") else 0),
                )
        print(f"[automation] {len(rows)} eski görev JSON'dan SQLite'a taşındı.")
    finally:
        conn.close()
    _OLD_JSON_PATH.rename(_OLD_JSON_PATH.with_suffix(".json.migrated"))


_migrate_from_json_if_needed()


def add_task(command: str, run_at: str = "", minutes_from_now: int | None = None) -> str:
    """Gorev ekler. Ya 'run_at' (kesin tarih/saat, 'YYYY-AA-GG SS:DD') ya da
    'minutes_from_now' (simdiden itibaren kac dakika sonra) verilmeli.
    minutes_from_now tercih edilir: zaman hesaplamasi burada, GUVENILIR
    sekilde (Python ile) yapilir, modele biraktirilmaz."""
    if minutes_from_now is not None:
        target = datetime.now() + timedelta(minutes=max(0, int(minutes_from_now)))
        run_at = target.strftime("%Y-%m-%d %H:%M")
    else:
        datetime.strptime(run_at, "%Y-%m-%d %H:%M")  # bicim gecersizse ValueError firlatir

    task_id = uuid.uuid4().hex[:8]
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO tasks (id, run_at, command, done) VALUES (?, ?, ?, 0)",
                (task_id, run_at, command),
            )
    finally:
        conn.close()
    return task_id


def list_tasks() -> list[dict]:
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, run_at, command, done FROM tasks ORDER BY run_at").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove_task(task_id: str) -> bool:
    conn = _connect()
    try:
        with conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0
    finally:
        conn.close()


def pop_due_tasks() -> list[dict]:
    """Zamani gelmis (ve henuz calistirilmamis) gorevleri isaretler ve
    dondurur. Bilgisayar kapaliyken gecen gorevler de (gec de olsa) yakalanir."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        with conn:
            due = conn.execute(
                "SELECT id, run_at, command FROM tasks WHERE done = 0 AND run_at <= ?",
                (now_str,),
            ).fetchall()
            if due:
                ids = [row["id"] for row in due]
                conn.executemany("UPDATE tasks SET done = 1 WHERE id = ?", [(i,) for i in ids])
        return [dict(r) for r in due]
    finally:
        conn.close()


def task_manager(parameters: dict = None, response=None, player=None, session_memory=None) -> str:
    """Sesli arayuze bagli arac: gorev ekle/listele/sil."""
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if action == "add":
        run_at = params.get("run_at", "")
        command = params.get("command", "")
        minutes_from_now = params.get("minutes_from_now")
        if not command:
            return "Görev eklemek için bir komut gerekli."
        if not run_at and minutes_from_now is None:
            return "Görev eklemek için ya 'run_at' (kesin tarih/saat) ya da 'minutes_from_now' (kaç dakika sonra) gerekli."
        try:
            task_id = add_task(command, run_at=run_at, minutes_from_now=minutes_from_now)
        except ValueError:
            return "Tarih biçimi hatalı. Örnek: 2026-12-31 18:00"
        actual = next(t["run_at"] for t in list_tasks() if t["id"] == task_id)
        if player:
            player.write_log(f"[automation] görev eklendi: {task_id} @ {actual} -> {command}")
        return f"Görev kaydedildi (kimlik: {task_id}). {actual} zamanında '{command}' otomatik çalıştırılacak."

    if action == "list":
        tasks = list_tasks()
        if not tasks:
            return "Kayıtlı otomasyon görevi yok."
        lines = [f"{t['id']} | {t['run_at']} | {t['command']} | "
                 f"{'tamamlandı' if t['done'] else 'bekliyor'}" for t in tasks]
        return "\n".join(lines)

    if action == "remove":
        task_id = params.get("task_id", "")
        if not task_id:
            return "Silmek için görev kimliği gerekli."
        return "Görev silindi." if remove_task(task_id) else "Bu kimlikte görev bulunamadı."

    return "Bilinmeyen işlem. action: add | list | remove olmalı."
