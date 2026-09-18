"""Kullanicinin tekrar eden istek kaliplarini tespit eder.

Her arac cagrisini (hangi arac, hangi gun, hangi saat) SQLite'a kaydeder.
Bir arac belirli bir gun sayisinda (varsayilan 3) FARKLI gunlerde
kullanilmissa, bunu bir "kalip" olarak isaretler - sabah karsilamasinda
dogal bir sekilde hatirlatilabilir.

Gizlilik notu: sadece arac ADI ve zaman damgasi tutulur, konusma icerigi
veya kisisel veri tutulmaz.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from jarvis.paths import memory_dir


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DB_PATH = memory_dir() / "pattern_tracker.db"

# Arac adlarini kullaniciya anlamli, dogal Turkce ifadelere cevirir.
_FRIENDLY_NAMES = {
    "weather_report": "hava durumu",
    "web_search": "haber/internet araması",
    "reminder": "hatırlatıcı",
    "task_manager": "zamanlanmış görev",
    "youtube_video": "YouTube video",
    "open_app": "uygulama açma",
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            call_date TEXT NOT NULL,
            call_hour INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_date ON tool_calls(tool_name, call_date)")
    return conn


def log_tool_call(tool_name: str) -> None:
    """Bir arac cagrisini kaydeder. Hata durumunda sessizce gecer -
    bu, ana asistan akisini ASLA bozmamali (dekoratif bir ozellik)."""
    try:
        now = datetime.now()
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO tool_calls (tool_name, call_date, call_hour) VALUES (?, ?, ?)",
                    (tool_name, now.strftime("%Y-%m-%d"), now.hour),
                )
        finally:
            conn.close()
    except Exception:
        pass


def detect_patterns(min_days: int = 3, lookback_days: int = 14) -> list[str]:
    """Son `lookback_days` gun icinde, en az `min_days` FARKLI gunde
    kullanilmis araclari, dogal Turkce aciklamalar olarak dondurur."""
    try:
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT tool_name, COUNT(DISTINCT call_date) as day_count,
                       ROUND(AVG(call_hour)) as avg_hour
                FROM tool_calls
                WHERE call_date >= ?
                GROUP BY tool_name
                HAVING day_count >= ?
                ORDER BY day_count DESC
            """, (cutoff, min_days)).fetchall()
        finally:
            conn.close()

        results = []
        for row in rows:
            friendly = _FRIENDLY_NAMES.get(row["tool_name"], row["tool_name"])
            hour = int(row["avg_hour"]) if row["avg_hour"] is not None else None
            if hour is not None:
                results.append(f"{friendly} (genellikle saat {hour:02d} civarında, son {lookback_days} günde {row['day_count']} farklı gün)")
            else:
                results.append(f"{friendly} (son {lookback_days} günde {row['day_count']} farklı gün)")
        return results
    except Exception:
        return []
