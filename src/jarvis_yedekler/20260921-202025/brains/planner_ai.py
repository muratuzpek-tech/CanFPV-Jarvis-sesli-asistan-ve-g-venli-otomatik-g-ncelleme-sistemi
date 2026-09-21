"""planner_ai.py — PLANNER AI: Planlama Beyni.

Görevi (kullanıcı talimatı, bölüm 2): kullanıcının hedefini analiz etmek,
büyük işleri küçük görevlere bölmek, öncelik belirlemek, görev sırası
oluşturmak, gerekirse diğer AI'lara görev atamak.

KESİN SINIR: Planner AI doğrudan kod değiştirmez, araştırma yapmaz, dosya
silmez - SADECE bir plan üretir. Planın kendisi bir sonraki adımı hangi
beynin (research_ai, coder_ai, ...) üstleneceğini işaretler; o adımı
GERÇEKTEN çalıştırmak brain_orchestrator.py'nin işidir.
"""
from __future__ import annotations

from jarvis.brains.base_brain import BaseBrain, BrainError

SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın PLANLAMA BEYNİsin (planner_ai).

GÖREVİN:
- Kullanıcının hedefini analiz et.
- Büyük işi küçük, somut adımlara böl.
- Her adım için hangi UZMAN BEYNİN uygun olduğunu belirle: research_ai
  (SADECE genel internette araştırma/bilgi toplama), coder_ai (projedeki
  bir dosyayı OKUYUP ANALİZ ETME ya da GERÇEKTEN DEĞİŞTİRME), executor_ai
  (onaylanmış, mevcut bir aracı gerçekten çalıştırma - ör. Windows sistem
  sorgusu, yedek alma, GitHub araması) - bunların dışında bir beyin
  uydurma. security_ai bir adım hedefi DEĞİLDİR - o, orchestrator'ın HER
  adımdan önce otomatik olarak sorduğu, arka plandaki bağımsız bir risk
  denetçisidir; plana ayrı bir "adım" olarak asla eklenmez.
- Öncelik belirle (low/medium/high).
- Her adım için "operation" alanını da doldur - şu değerlerden biri:
  * "research": research_ai ile SADECE internette araştırma yapılacak.
  * "analyze": coder_ai ile projedeki bir dosya OKUNUP analiz edilecek,
    dosya DEĞİŞTİRİLMEYECEK (ör. "bu dosyayı incele", "şunun neden böyle
    davrandığını açıkla", "kodu gözden geçir").
  * "modify": coder_ai ile projedeki bir dosya GERÇEKTEN değiştirilecek.
  * "execute": executor_ai ile mevcut, onaylı bir araç çalıştırılacak.
  * "unknown": hiçbiri uymuyorsa (bu durumda agent de "unknown" olmalı).
- executor_ai ile guvenli_kasa şifreleme/şifre çözme adımı gerekiyorsa
  operation="execute" ve ayrıca yapılandırılmış "capability" alanını
  kullan: "vault_encrypt" veya "vault_decrypt"; "parameters" içinde
  source ve kullanıcının açıkça verdiği password bulunmalı. Parola uydurma,
  varsayılan parola koyma veya hedef metninden tahmin etme.
- "sonucu kontrol et", "risk değerlendir" veya benzeri meta-adımları ayrı
  bir adım olarak üretme; bunlar orchestrator/auditor tarafından otomatik
  yapılır. Emin olunamayan gerçek bir işlem için unknown kullan.
- Adım coder_ai ise (operation "analyze" ya da "modify" fark etmez), ZORUNLU
  olarak "file_path" alanını da doldur: incelenecek/değiştirilecek dosyanın
  proje köküne göre göreli yolu (ör. "actions/weather_report.py" ya da
  "brains/planner_ai.py"). Hangi dosya olduğundan EMİN DEĞİLSEN, coder_ai
  yerine "unknown" agent ve "unknown" operation kullan - asla dosya yolu
  uydurma.
- Projenin KENDİ yerel bir dosyasını okuma/analiz etme isteği gelirse bunu
  coder_ai + operation="analyze" ile ver (coder_ai zaten dosyayı okuyup
  analiz edebiliyor, HİÇBİR ŞEY YAZMAZ). research_ai'yi BUNUN İÇİN ASLA
  KULLANMA - research_ai SADECE genel internette arama yapar, yerel proje
  dosyalarıyla hiçbir ilgisi yoktur, böyle bir adımı ona verirsen anlamsız
  bir web araması yapıp alakasız sonuç döner.
- "Risk değerlendir", "güvenlik kontrolü yap" gibi bir adım aklına gelirse
  YAZMA - bu zaten her adımda otomatik yapılıyor, ayrı bir adım gerekmez.

KESİN SINIRLAR:
- Kendi başına kod YAZMA, dosya DEĞİŞTİRME, komut ÇALIŞTIRMA - sadece plan üret.
- Araştırma YAPMA - bunu research_ai yapacak, sen sadece "araştırma gerekiyor" de.
- Emin olmadığın bir adım için uydurma bir beyin adı KULLANMA; agent="unknown",
  operation="unknown" yaz.

SADECE şu JSON şemasında dön, başka hiçbir şey yazma:
{
  "goal": "kullanicinin orijinal hedefinin kisa ozeti",
  "steps": [
    {"order": 1, "description": "...", "agent": "research_ai|coder_ai|executor_ai|unknown", "operation": "research|analyze|modify|execute|unknown", "priority": "low|medium|high", "file_path": "sadece agent=coder_ai ise, yoksa boş string", "capability": "opsiyonel yapılandırılmış executor capability", "parameters": {}}
  ]
}"""


class PlannerAI(BaseBrain):
    NAME = "planner_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def handle(self, message: dict) -> dict:
        goal = (message.get("payload") or {}).get("goal", "").strip()
        if not goal:
            raise BrainError("planner_ai: 'goal' parametresi boş olamaz.")

        plan = self.call_llm_json(f"KULLANICI HEDEFİ: {goal}")
        if not isinstance(plan, dict) or "steps" not in plan:
            raise BrainError(f"planner_ai: model beklenen plan şemasını döndürmedi: {plan!r}")

        steps = plan.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise BrainError("planner_ai: plan hiç adım içermiyor.")

        # Deterministik guvenlik: tanimadigimiz bir beyin adi gecerse
        # "unknown" a cevir - orchestrator boyle bir adimi asla calistirmaz,
        # kullaniciya/Auditor'a bildirir. Planner'in kendisi hicbir sey
        # calistirmiyor, sadece burada VERIYI temizliyoruz.
        #
        # DUZELTME (2026-09-15, canli testte bulundu): "security_ai" burada
        # "taninan" bir beyin olarak listelenmisti, ama brain_orchestrator.
        # _execute_step() SADECE research_ai/coder_ai/executor_ai adimlarini
        # calistirabiliyor - security_ai bir "adim yurutucusu" degil, HER
        # adimdan once orchestrator'in kendisinin otomatik cagirdigi ayri bir
        # risk denetcisi. Bu yuzden Planner "security_ai" adinda bir adim
        # uretirse, orchestrator bunu calistiramayip RuntimeError firlatiyor
        # ve adim sessizce basarisiz sayiliyor (crash yok ama adim hep
        # basarisiz olurdu). Cozum: security_ai'yi bu kumeden cikarip, boyle
        # bir adimi da "unknown" a cevirmek - tıpkı diger taninmayan beyinler
        # gibi. (Ayni duzeltme SYSTEM_PROMPT'ta da yapildi.) DEGISMEDI.
        known_agents = {"research_ai", "coder_ai", "executor_ai"}

        # YENI (2026-09-16, UNRESOLVED_AGENT duzeltmesi): "operation" alani
        # eklendi. research_ai/executor_ai'nin ZATEN tek anlamli bir islevi
        # var - LLM'in bu alani dogru yazmasina GUVENMEK yerine, agent
        # biliniyorsa operation DETERMINISTIK olarak sabitleniyor. SADECE
        # coder_ai gercekten iki deger arasinda dallaniyor (analyze/modify) -
        # o da gecersiz/eksik gelirse GERIYE DONUK UYUMLULUK icin "modify"ye
        # duser (bu alan eklenmeden ONCEKI TUM davranis zaten buydu, yani
        # eski/operation'siz bir cagiran icin hicbir sey degismez).
        _FIXED_OPERATION = {"research_ai": "research", "executor_ai": "execute"}
        _CODER_OPERATIONS = {"analyze", "modify"}

        for step in steps:
            if step.get("agent") not in known_agents:
                step["agent"] = "unknown"
                step["operation"] = "unknown"
                continue

            agent = step["agent"]
            if agent in _FIXED_OPERATION:
                step["operation"] = _FIXED_OPERATION[agent]
                continue

            # agent == "coder_ai": file_path ZORUNLU - yoksa guvenli tarafta
            # kalip "unknown" yap (orchestrator boyle bir adimi calistirmaz,
            # bir sonraki adima gecer/gorevi basarisiz sayar - asla dosya
            # uydurmaz). Bu kontrol operation="analyze" icin de GECERLI -
            # analiz de coder_ai'nin dosyayi GERCEKTEN okumasini gerektiriyor.
            if not step.get("file_path"):
                step["agent"] = "unknown"
                step["operation"] = "unknown"
                step["description"] = (step.get("description", "") +
                                        " [DOSYA YOLU BELİRTİLMEDİĞİ İÇİN ATLANDI]")
                continue

            if step.get("operation") not in _CODER_OPERATIONS:
                step["operation"] = "modify"

        self.log(f"Plan üretildi: {len(steps)} adım, hedef={goal!r}")
        return self.ok(message, {"goal": plan.get("goal", goal), "steps": steps})
