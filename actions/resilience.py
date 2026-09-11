"""
Paylasilan LLM dayaniklilik katmani.

Arastirma raporundan uyarlanmistir: hata siniflandirmasi + jitter'li
backoff + devre kesici (circuit breaker). dev_agent.py ve code_helper.py
gibi Gemini/Ollama cagiran her yerde ayni tutarli davranisi saglar.

Kullanim:
    from actions.resilience import call_with_resilience, CircuitBreaker

    breaker = CircuitBreaker(name="gemini")
    result = call_with_resilience(
        lambda: model.generate_content(prompt),
        breaker=breaker,
    )
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field


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
    if breaker is not None and breaker.is_open():
        raise AllAttemptsFailed(RuntimeError(f"'{breaker.name}' devre kesici açık, denenmedi."))

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            result = fn()
            if breaker is not None:
                breaker.record_success()
            return result
        except Exception as exc:
            last_error = exc
            kind = classify_error(exc)

            if kind == "terminal":
                if breaker is not None:
                    breaker.record_failure()
                raise

            if kind == "fallback":
                if breaker is not None:
                    breaker.record_failure()
                raise ModelFallbackNeeded(exc)

            # 'retryable' veya 'unknown': jitter'li backoff ile tekrar dene
            if breaker is not None:
                breaker.record_failure()
            if attempt < max_attempts - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                delay = random.uniform(0, delay)  # full jitter
                print(f"[Resilience] ⏳ Geçici hata ({kind}), {delay:.1f}sn sonra "
                      f"tekrar denenecek ({attempt + 1}/{max_attempts}): {exc}")
                time.sleep(delay)

    raise AllAttemptsFailed(last_error)
