"""security_ai.py — SECURITY AI: Güvenlik Beyni.

Görevi (bölüm 5 ve 15): kritik işlemleri kontrol eden BAĞIMSIZ güvenlik
katmanı. Her işlem için {"approved": bool, "risk": "low|medium|high",
"reason": "..."} üretir. HIGH riskli işlemlerde kullanıcı onayı zorunludur.

TASARIM TERCİHİ (bilinçli): Risk sınıflandırması SADECE Gemini'nin kararına
bırakılmaz - deterministik bir kural tablosuyla yapılır (aşağıdaki
_HIGH_RISK_ACTIONS / _MEDIUM_RISK_ACTIONS), tıpkı actions/tools_kopru.py'nin
is_destructive() fonksiyonunun ZATEN yaptığı gibi. Sebep: bir LLM'in "bu
güvenli" demesi tek başına güvenilir bir güvenlik sınırı değildir - bu
oturumda gerçek bir güvenlik açığı (WhatsApp'a yanlışlıkla mesaj gönderme)
tam olarak "otomatik/LLM kararına güvenme" yüzünden yaşandı. Gemini SADECE
kullanıcıya gösterilecek okunabilir 'reason' metnini üretir, KARARI değil.
"""
from __future__ import annotations

from jarvis.brains.base_brain import BaseBrain, BrainError

# 15. RİSK SİSTEMİ + 5. bölümdeki "kontrol edeceği işlemler" listesiyle
# birebir uyumlu, deterministik eşleme. (tool, action) -> risk seviyesi.
_HIGH_RISK = {
    ("file_controller", "delete"),
    ("file_controller", "move"),
    ("computer_settings", "shutdown"),
    ("computer_settings", "restart"),
    ("computer_settings", "lock_screen"),
    ("computer_settings", "lock"),
    ("send_message", None),          # disariya HER mesaj HIGH
    ("entegrasyon_uygula", None),    # Jarvis'in gercek koduna yazmak HIGH
    ("discovery_register", None),
    # NOT: asagidaki isimler, executor_ai.py'nin GERCEK _ALLOWED_ACTIONS
    # sozlugundeki isimlerle BIREBIR ayni olmali - iki dosya arasinda farkli
    # bir isimlendirme kullanmak, risk kontrolunun sessizce atlanmasina yol
    # acabilirdi (bkz. brain_orchestrator._risk_of_step, iki dosyayi da
    # kullanan yer).
    ("vault_encrypt", None),
    ("vault_decrypt", None),
    ("backup_rollback", None),
    ("coder_ai", "modify_critical_file"),
    ("install_program", None),
    ("download_file", None),
}
_MEDIUM_RISK = {
    ("file_controller", "create_file"),
    ("file_controller", "create_folder"),
    ("file_controller", "copy"),
    ("coder_ai", "write_new_file"),
    ("backup_create", None),
}
# Geri kalan her şey (okuma, analiz, araştırma, loglama) varsayılan olarak LOW.


SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın GÜVENLİK BEYNİsin (security_ai).

Sana bir işlem (tool, action, hedef) verilecek ve bu işlemin risk seviyesi
ZATEN deterministik bir kuralla belirlenmiş olacak. SENİN TEK GÖREVİN: bu
kararı kullanıcıya açıklayacak KISA, NET bir 'reason' cümlesi yazmak.
KARARI SEN VERMİYORSUN, sadece açıklıyorsun. Onaylanıp onaylanmayacağına
karar verme, sadece riskin NEDEN o seviyede olduğunu 1-2 cümleyle özetle.

SADECE şu JSON şemasında dön:
{"reason": "..."}"""


class SecurityAI(BaseBrain):
    NAME = "security_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    @staticmethod
    def classify_risk(tool: str, action: str | None) -> str:
        if (tool, action) in _HIGH_RISK or (tool, None) in _HIGH_RISK:
            return "high"
        if (tool, action) in _MEDIUM_RISK or (tool, None) in _MEDIUM_RISK:
            return "medium"
        return "low"

    def handle(self, message: dict) -> dict:
        payload = message.get("payload") or {}
        tool = payload.get("tool", "").strip()
        action = payload.get("action")
        target = payload.get("target", "")
        if not tool:
            raise BrainError("security_ai: 'tool' parametresi boş olamaz.")

        risk = self.classify_risk(tool, action)

        # Gemini'ye SADECE aciklama metni icin danisiyoruz; o cagri
        # basarisiz olsa bile (kota vb.) karar ETKİLENMEZ - deterministik
        # fallback metni kullanilir. Guvenlik kararinin bir LLM cagrisinin
        # basarisina bagli olmasi kabul edilemez.
        try:
            resp = self.call_llm_json(
                f"İŞLEM: tool={tool}, action={action}, hedef={target}, risk={risk}"
            )
            reason = resp.get("reason") if isinstance(resp, dict) else None
        except BrainError:
            reason = None

        if not reason:
            reason = f"'{tool}'" + (f".{action}" if action else "") + f" işlemi {risk.upper()} risk kategorisinde (deterministik kural tablosu)."

        approved = risk != "high"  # HIGH -> kullanici onayi ZORUNLU, burada asla otomatik onaylanmaz
        result = {"approved": approved, "risk": risk, "reason": reason}
        self.log(f"Risk değerlendirildi: tool={tool} action={action} -> {risk} (approved={approved})")
        return self.ok(message, result)
