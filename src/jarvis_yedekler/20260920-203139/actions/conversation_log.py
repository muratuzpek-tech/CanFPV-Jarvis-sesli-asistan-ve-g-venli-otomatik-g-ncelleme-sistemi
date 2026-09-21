from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from jarvis.paths import memory_dir


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR      = _get_base_dir()
LOG_PATH      = memory_dir() / "conversation_log.jsonl"
API_KEYS_PATH = BASE_DIR / "config" / "api_keys.json"

MAX_LOG_BYTES      = 5 * 1024 * 1024   # 5MB'i geçince en eski yarısını at
MAX_TEXT_CHARS     = 2000              # tek bir turdan saklanacak max karakter
MAX_SUMMARY_CHARS  = 12000             # Gemini'ye gönderilecek günlük metin üst sınırı


def log_turn(role: str, text: str) -> None:
    """main.py'nin 'You: ...' / 'Jarvis: ...' loglarinin yanında çağırılır -
    ekrana yazmakla yetinme, kalıcı bir günlüğe de ekler. Hiçbir şekilde
    ana konuşma akışını bozmamalı - hata sessizce loglanır."""
    text = (text or "").strip()
    if not text:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "text": text[:MAX_TEXT_CHARS],
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _rotate_if_needed()
    except Exception as e:
        print(f"[ConversationLog] ⚠️ Yazılamadı: {e}")


def _rotate_if_needed() -> None:
    """Günlük sonsuza kadar büyümesin diye 5MB'i geçince en eski yarısını atar."""
    try:
        if not LOG_PATH.is_file() or LOG_PATH.stat().st_size <= MAX_LOG_BYTES:
            return
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        keep = lines[len(lines) // 2:]
        LOG_PATH.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    except Exception as e:
        print(f"[ConversationLog] ⚠️ Rotasyon başarısız: {e}")


def _date_range(period: str, explicit_date: str | None = None) -> tuple[datetime, datetime] | None:
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if explicit_date:
        try:
            d = datetime.strptime(explicit_date.strip(), "%Y-%m-%d")
            return d, d + timedelta(days=1)
        except ValueError:
            return None

    period = (period or "").strip().lower()
    if period == "bugun":
        return today_start, today_start + timedelta(days=1)
    if period == "dun":
        y = today_start - timedelta(days=1)
        return y, today_start
    if period == "bu_hafta":
        start = today_start - timedelta(days=today_start.weekday())
        return start, today_start + timedelta(days=1)
    if period == "gecen_hafta":
        this_week_start = today_start - timedelta(days=today_start.weekday())
        return this_week_start - timedelta(days=7), this_week_start
    return None


def _load_entries(start: datetime, end: datetime) -> list[dict]:
    if not LOG_PATH.is_file():
        return []
    out = []
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["timestamp"])
            except Exception:
                continue
            if start <= ts < end:
                out.append(e)
    except Exception as e:
        print(f"[ConversationLog] ⚠️ Okunamadı: {e}")
    return out


def _get_api_key() -> str:
    from jarvis.core.secure_config import get_gemini_api_key
    return get_gemini_api_key()


_SUMMARY_PROMPT = """Aşağıda belirli bir gün/dönem ait, kullanıcı ile Jarvis (bir sesli asistan) arasındaki gerçek konuşturma günlükü bulunmaktadır. Kullanıcıya doğal, kısa (2-5 cümle) bir Türkçe özeti ile cevap ver - transkripti olduğu gibi tekrarlama, GERÇEKÇEN özeti belirleyin: hangi konular konusuldu, varsa alınan kararlar/istekler.{topic_hint}

KONUSMA GUNLUGU:
{transcript}

OZET:"""


def recall_conversation(parameters: dict) -> str:
    """Ana giriş noktası - main.py'den bir tool olarak çağrılır.
    parameters: period ('bugun'|'dun'|'bu_hafta'|'gecen_hafta') VEYA
    date ('YYYY-MM-DD'), topic (opsiyonel, özeti belirli bir konuya odaklar)."""
    p = parameters or {}
    period = p.get("period", "")
    explicit_date = p.get("date", "")
    topic = (p.get("topic") or "").strip()

    rng = _date_range(period, explicit_date)
    if rng is None:
        return ("Hangi zaman aralığını kastettiğini anlayamadım — "
                "bugün, dün, bu hafta, geçen hafta ya da belirli bir tarih olabilir.")

    start, end = rng
    entries = _load_entries(start, end)
    if not entries:
        label = explicit_date or period
        return f"'{label}' için kayıtlı bir konuşma bulamadım — o tarihte kayıt tutulmuyor olabilir."

    transcript = "\n".join(f"{e['role']}: {e['text']}" for e in entries)[:MAX_SUMMARY_CHARS]
    topic_hint = f" Özellikle '{topic}' konusuna odaklan." if topic else ""
    prompt = _SUMMARY_PROMPT.format(topic_hint=topic_hint, transcript=transcript)

    try:
        from google import genai
        from jarvis.actions.resilience import CircuitBreaker, call_with_resilience

        breaker = CircuitBreaker(name="gemini-recall", failure_threshold=3, cooldown_seconds=60.0)
        client = genai.Client(api_key=_get_api_key())

        def _call():
            return client.models.generate_content(model="gemini-flash-latest", contents=prompt)

        from jarvis.actions.local_llm import generate_with_fallback
        summary = generate_with_fallback(
            lambda: call_with_resilience(_call, breaker=breaker, max_attempts=2, base_delay=2.0, max_delay=15.0),
            prompt_for_ollama=prompt,
            source="recall_conversation",
        ).strip()
        if summary:
            return summary
    except Exception as e:
        print(f"[ConversationLog] ⚠️ Özet başarısız: {e}")

    # Gemini başarısız olsa bile elimizdeki veriyi boş harcamayalım
    preview = "\n".join(f"{e['role']}: {e['text'][:120]}" for e in entries[-8:])
    return f"Özetleyemedim ama şu kayıtları buldum:\n{preview}"