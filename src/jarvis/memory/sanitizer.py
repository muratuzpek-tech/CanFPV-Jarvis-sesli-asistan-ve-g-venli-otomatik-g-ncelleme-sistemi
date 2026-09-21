"""
sanitizer.py — hafif, bağımlılıksız PII/credential redaksiyonu.

`memory_manager.remember()`/`update_memory()` ve `conversation_log.log_turn()`
gibi diske kalıcı yazılan her noktada metni bu modülden geçirerek parola,
API anahtarı, token, kullanıcı-adı içeren dosya yolu gibi hassas verilerin
düz metin olarak `long_term.json` / `conversation_log.jsonl` içine
yazılmasını engellemeyi amaçlar.

Presidio/spaCy gibi ağır bağımlılıklar KULLANILMAZ — yalnızca regex.
Bu yüzden %100 garanti değildir, ama en sık karşılaşılan sızıntı
türlerini (bilinen API key formatları, "parola: ..." kalıpları,
kullanıcı adı içeren dosya yolları) önceden yakalar. Ultron projesinin
`utils/sanitizer.py`'ındaki CREDENTIAL_PATTERNS / PATH_PATTERNS
mantığından esinlenilmiştir, buraya Presidio kısmı taşınmamıştır.
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

# Sıra önemlidir: daha spesifik/dar kalıplar önce denenir.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{30,40}")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic_bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.=]{10,}")),
    (
        "labeled_secret",
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|token|secret|access[_-]?key)\s*[:=]\s*"
            r"[^\s,;]{6,}"
        ),
    ),
    (
        "labeled_password",
        # \w{0,6}: "parolam:", "parolanız:", "şifreniz:" gibi Türkçe iyelik
        # eki almış hallerini de yakalar (sadece çıplak "parola:" değil).
        re.compile(r"(?i)\b(parola|password|şifre|sifre|pwd)\w{0,6}\s*[:=]\s*\S+"),
    ),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+")),
    ("unix_home_path", re.compile(r"/home/[^/\s]+")),
]


def sanitize(text: str) -> str:
    """Metindeki bilinen kimlik bilgisi / parola / kullanıcı-yolu örüntülerini
    [REDACTED] ile değiştirir. Metin değilse veya boşsa dokunmadan döner."""
    if not text or not isinstance(text, str):
        return text
    for _name, pattern in _PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def sanitize_value(value):
    """remember()/update_memory() gibi str olmayan değerlerin de güvenle
    geçmesi için: sadece str ise sanitize eder, değilse aynen döner."""
    if isinstance(value, str):
        return sanitize(value)
    return value
