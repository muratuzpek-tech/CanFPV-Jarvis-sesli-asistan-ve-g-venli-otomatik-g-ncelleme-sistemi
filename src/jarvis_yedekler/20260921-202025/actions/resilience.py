"""
Paylasilan LLM dayaniklilik katmani.

Arastirma raporundan uyarlanmistir: hata siniflandirmasi + jitter'li
backoff + devre kesici (circuit breaker). dev_agent.py ve code_helper.py
gibi Gemini/Ollama cagiran her yerde ayni tutarli davranisi saglar.

Kullanim:
    from jarvis.actions.resilience import call_with_resilience, CircuitBreaker

    breaker = CircuitBreaker(name="gemini")
    result = call_with_resilience(
        lambda: model.generate_content(prompt),
        breaker=breaker,
    )
"""
from __future__ import annotations

import json
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from jarvis.paths import memory_dir


# --- Hata siniflandirmasi -----------------------------------------------

TERMINAL_CODES  = {400, 401, 403}          # asla retry etme
RETRYABLE_CODES = {429, 500, 502, 503, 504, 529}
FALLBACK_CODES  = {404}                    # model kullanimdan kaldirilmis


def _extract_status_code(exc: Exception) -> int | None:
    """Istisna metninden HTTP durum kodunu cikarmaya calisir (Gemini/OpenAI
    SDK'lari genelde 'XXX ...' formatinda mesaj metni doner)."""
    text = str(exc)
    match = re.search(r"\b([1-5]\d{2})\b", text)
    if match:
        return int(match.group(1))
    for attr in ("status_code", "code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def classify_error(exc: Exception) -> str:
    """'terminal' | 'retryable' | 'fallback' | 'unknown' dondurur."""
    code = _extract_status_code(exc)
    if code in TERMINAL_CODES:
        return "terminal"
    if code in FALLBACK_CODES:
        return "fallback"
    if code in RETRYABLE_CODES:
        return "retryable"
    return "unknown"


# --- Devre kesici (circuit breaker) --------------------------------------

@dataclass
class CircuitBreaker:
    """Ardisik hatalardan sonra bir servisi gecici olarak 'acik devre'ye
    alir - surekli basarisiz olan bir servise istek yagdirmayi onler."""
    name: str
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            # sogutma suresi doldu, tekrar denemeye izin ver (half-open)
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            print(f"[Resilience] ⚡ Devre kesici açıldı: '{self.name}' "
                  f"{self.failure_threshold} ardışık hatadan sonra "
                  f"{self.cooldown_seconds:.0f}sn devre dışı.")


# --- Tekrarlayan hata takibi ("error_log") -------------------------------
#
# Downloads'ta bulunan eski self_heal_v35_fixed.py'den ilham alinmistir:
# ayni hata (kaynak + hata tipi) ust uste REPEAT_THRESHOLD kez gorulurse,
# kod yazip calistirmak yerine SADECE GUVENLI, VERI-TABANLI bir onlem
# uygulanir (ör. bekleme suresini artir). Boylece agent_loop gibi otonom
# bir sistem "rastgele bir sonraki adimi dene" yerine, GERCEKTEN tekrar
# eden sorunlari hedef alabilir - kanit olmadan tahmin yurutmez.

REPEAT_THRESHOLD = 3     # ayni hata kac kez gorulurse onlem uygulanir
MAX_LOG_ENTRIES  = 200


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ERROR_LOG_PATH: Path = memory_dir() / "error_log.json"


def _error_key(source: str, exc: Exception) -> str:
    """Ayni sorunu tanimlayan kararli anahtar: kaynak + hata tipi.
    (self_heal_v35_fixed.py dosya+satir kullaniyordu; biz burada genel
    amacli oldugumuz icin - LLM cagrilari, ses cihazlari, herhangi bir
    call_with_resilience kullanicisi - 'kaynak adi' + 'exception sinifi'
    yeterince kararli ve genel bir anahtar.)"""
    return f"{source}|{type(exc).__name__}"


def _load_error_log() -> dict:
    try:
        if ERROR_LOG_PATH.is_file():
            data = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_error_log(data: dict) -> None:
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Sadece en son guncellenen MAX_LOG_ENTRIES kaydi tut - sonsuza
        # kadar buyumesin.
        items = sorted(data.items(), key=lambda kv: kv[1].get("last_seen", ""))
        trimmed = dict(items[-MAX_LOG_ENTRIES:])
        with tempfile.NamedTemporaryFile(
            "w", dir=ERROR_LOG_PATH.parent, delete=False,
            encoding="utf-8", suffix=".tmp",
        ) as tmp:
            json.dump(trimmed, tmp, indent=2, ensure_ascii=False)
            temp_name = tmp.name
        Path(temp_name).replace(ERROR_LOG_PATH)
    except Exception as e:
        print(f"[Resilience] ⚠️ error_log.json yazılamadı: {e}")


def record_error(source: str, exc: Exception) -> dict:
    """Bir hatayi error_log.json'a kaydeder. Ayni hata (kaynak+tip) ust
    uste REPEAT_THRESHOLD kez gorulmusse, GUVENLI bir onlem (sadece veri -
    asla kod degil) kaydedip dondurur: su an tek strateji 'increased_backoff'
    (bir sonraki denemede ekstra bekleme suresi). Asla exception firlatmaz -
    bu bir gozlem katmani, ana akisi asla bozmamali."""
    try:
        key = _error_key(source, exc)
        now = time.time()
        log = _load_error_log()
        entry = log.get(key, {
            "source": source,
            "error_type": type(exc).__name__,
            "count": 0,
            "first_seen": now,
            "mitigation": None,
        })
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_seen"] = now
        entry["last_message"] = str(exc)[:300]

        if entry["count"] >= REPEAT_THRESHOLD and not entry.get("mitigation"):
            extra_delay = min(60.0, 5.0 * (entry["count"] - REPEAT_THRESHOLD + 1))
            entry["mitigation"] = {
                "strategy": "increased_backoff",
                "extra_delay_seconds": extra_delay,
                "created_at": now,
            }
            print(f"[Resilience] 🧠 Tekrarlayan hata ({entry['count']}x) → "
                  f"'{key}' için önlem: +{extra_delay:.0f}sn ekstra bekleme")

        log[key] = entry
        _save_error_log(log)
        return entry
    except Exception as e:
        print(f"[Resilience] ⚠️ record_error başarısız: {e}")
        return {"count": 0, "mitigation": None}


def record_recovery(source: str, exc_type: type[Exception] | None = None) -> None:
    """Basarili bir cagridan sonra, o kaynagin biriken hata sayacini/onlemini
    temizler - artik calisiyorsa, eski hatalar yuzunden sonsuza kadar
    cezalandirilmamali. exc_type verilmezse, o 'source' ile baslayan TUM
    anahtarlar temizlenir (farkli hata tipleri arasinda gecis olabildigi
    icin)."""
    try:
        log = _load_error_log()
        if exc_type is not None:
            keys = [f"{source}|{exc_type.__name__}"]
        else:
            keys = [k for k in log if k.startswith(f"{source}|")]
        changed = False
        for key in keys:
            if key in log:
                del log[key]
                changed = True
        if changed:
            _save_error_log(log)
    except Exception:
        pass


def get_active_mitigation(source: str, exc: Exception | None = None) -> dict | None:
    """Su an aktif bir onlem var mi diye sorgular (kayit yapmadan). exc
    verilirse tam anahtar aranir; verilmezse o kaynaga ait ilk aktif onlem
    dondurulur."""
    log = _load_error_log()
    if exc is not None:
        entry = log.get(_error_key(source, exc))
        return entry.get("mitigation") if entry else None
    for key, entry in log.items():
        if key.startswith(f"{source}|") and entry.get("mitigation"):
            return entry["mitigation"]
    return None


def _last_real_error_message(source: str) -> str | None:
    """Bu kaynak icin error_log.json'da kayitli, GERCEKTEN yasanmis (devre
    kesici acik oldugu icin atlanmis degil) en son hatanin kisa mesajini
    dondurur, yoksa None. Sadece okur, asla yazmaz - call_with_resilience'in
    kritik yolunu asla bozmamali."""
    try:
        log = _load_error_log()
        candidates = [e for k, e in log.items() if k.startswith(f"{source}|")]
        if not candidates:
            return None
        best = max(candidates, key=lambda e: e.get("last_seen", 0))
        return f"{best.get('error_type', '?')}: {best.get('last_message', '')}"[:300]
    except Exception:
        return None


def error_log_summary(limit: int = 10) -> str:
    """Insan-okunabilir ozet - saglik kontrolu veya agent_loop'un 'su an
    neresi surekli bozuluyor' diye sormasi icin."""
    log = _load_error_log()
    if not log:
        return "Kayıtlı tekrarlayan hata yok."
    items = sorted(log.items(), key=lambda kv: kv[1].get("last_seen", 0), reverse=True)[:limit]
    lines = []
    for key, entry in items:
        mit = entry.get("mitigation")
        mit_str = f" [önlem: {mit['strategy']} +{mit['extra_delay_seconds']:.0f}sn]" if mit else ""
        lines.append(f"  {key}: {entry.get('count', 0)}x{mit_str} — {entry.get('last_message', '')[:80]}")
    return f"Son {len(items)} tekrarlayan hata kaydı:\n" + "\n".join(lines)


# --- Ana cagiri sarmalayicisi --------------------------------------------

class AllAttemptsFailed(Exception):
    def __init__(self, last_error: Exception):
        self.last_error = last_error
        super().__init__(f"Tüm denemeler başarısız: {last_error}")


class ModelFallbackNeeded(Exception):
    """classify_error 'fallback' dediginde firlatilir - caginin baska
    bir modele/saglayiciya gecmesi gerektigini belirtir."""
    def __init__(self, original: Exception):
        self.original = original
        super().__init__(str(original))


def call_with_resilience(
    fn,
    breaker: CircuitBreaker | None = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
):
    """fn() cagirir; retryable hatalarda jitter'li exponential backoff ile
    tekrar dener, terminal hatalarda hemen yukari firlatir, fallback
    hatalarinda ModelFallbackNeeded firlatir (cagiran baska saglayiciya
    gecsin diye), devre kesici acikken hic denemeden hata verir."""
    source = breaker.name if breaker is not None else "unknown"

    if breaker is not None and breaker.is_open():
        # ONEMLI: devre kesici acikken hicbir gercek cagri yapilmiyor, yani
        # burada "denenmedi" demek dogru ama bunu TEK BASINA loglamak, onu
        # ilk acan GERCEK hatayi tamamen gizliyordu (bir self_improve()
        # cagrisinin 3 denemesi de ayni "devre kesici acik" mesajini
        # goruyor, gercek sebep hicbir yere yazilmiyordu). Bunun yerine,
        # error_log.json'da bu kaynak icin en son kaydedilmis GERCEK hatayi
        # bulup mesaja ekliyoruz - boylece "rolled_back" gibi ust katman
        # loglari da gercek kok nedeni tasiyor.
        last_real = _last_real_error_message(source)
        suffix = f" (son gerçek hata: {last_real})" if last_real else ""
        raise AllAttemptsFailed(RuntimeError(f"'{breaker.name}' devre kesici açık, denenmedi{suffix}."))

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            result = fn()
            if breaker is not None:
                breaker.record_success()
            record_recovery(source)
            return result
        except Exception as exc:
            last_error = exc
            kind = classify_error(exc)
            entry = record_error(source, exc)
            mitigation = entry.get("mitigation")

            if kind == "terminal":
                if breaker is not None:
                    breaker.record_failure()
                raise

            if kind == "fallback":
                if breaker is not None:
                    breaker.record_failure()
                raise ModelFallbackNeeded(exc) from exc

            # 'retryable' veya 'unknown': jitter'li backoff ile tekrar dene
            if breaker is not None:
                breaker.record_failure()
            if attempt < max_attempts - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                delay = random.uniform(0, delay)  # full jitter
                if mitigation:
                    # Bu hata daha once de tekrar tekrar gorulmus - ekstra
                    # sabir goster, aynı hizda vurup durma.
                    delay += mitigation.get("extra_delay_seconds", 0.0)
                print(f"[Resilience] ⏳ Geçici hata ({kind}), {delay:.1f}sn sonra "
                      f"tekrar denenecek ({attempt + 1}/{max_attempts}): {exc}")
                time.sleep(delay)

    raise AllAttemptsFailed(last_error)
