# JARVIS (FINAL_BUILD) — Sistemin Doğru Çalışma Şekli

Bu belge, `C:\Users\murat\Desktop\MuratJarvis\FINAL_BUILD` projesinin
**gerçek kodundan doğrulanmış** (uydurma/varsayımsal değil) mimarisini ve her
parçanın DOĞRU çalıştığında ne yapması gerektiğini anlatır. Amaç: bu projeye
yeni giren bir geliştirici/AI oturumunun, sistemi baştan keşfetmeden "doğru
davranış nedir" sorusuna tek yerden cevap bulabilmesi.

---

## 1. Üç Katmanlı Mimari (özet)

Jarvis üç ayrı alt sistemden oluşur, HER BİRİ farklı hızda ve farklı amaçla
çalışır:

1. **Gemini Live (main.py / `JarvisLive` sınıfı)** — kullanıcıyla sesli/
   yazılı canlı konuşma arayüzü. `TOOL_DECLARATIONS` listesiyle Gemini'ye
   hangi araçları çağırabileceğini bildirir.
2. **Agent Loop (actions/agent_loop.py + actions/tools_kopru.py)** —
   arka planda **60 saniyede bir** tetiklenen "eski nesil" görev motoru.
   Menüsünü `tools_kopru.TOOL_DESCRIPTIONS`'tan otomatik üretir.
3. **Brain Team (brains/*.py + core/brain_orchestrator.py)** —
   arka planda **20 saniyede bir** tetiklenen, çok-beyinli (planner/coder/
   security/auditor/executor) görev motoru. `core/watchdog.py` ile görev
   sağlığını denetler.

Bu üç katman BİRBİRİNDEN BAĞIMSIZ çalışır; biri çökerse diğerleri
etkilenmemelidir (bkz. `base_brain.py`'nin "TASARIM SINIRI" notu).

---

## 2. Gemini Live (main.py) — Doğru Davranış

- Kullanıcının sesli/yazılı isteğini alır, `TOOL_DECLARATIONS`'taki
  araçlardan uygun olanı seçip çağırır (FILE_ANALYSIS/FILE_MODIFICATION gibi
  ağır işler `core.get_orchestrator()` üzerinden **Brain Team**'e,
  basit/hızlı işler `tools_kopru.ALLOWED_TOOLS` üzerinden **Agent Loop**'a
  yönlendirilir).
- `get_orchestrator()` process başına TEK SEFER, İLK Brain Team komutunda
  tembel (lazy) olarak oluşturulur — process yeniden başlatılınca eski
  kuyruk state'i diskten (`tasks/brain_tasks.json`) okunarak devam eder,
  ama orchestrator'ın kendisi (worker thread) her process için yeniden
  kurulur. `tasks/.orchestrator.lock` dosyası, aynı anda İKİ orchestrator
  instance'ının aynı görev kuyruğuna yazmasını (stale PID kontrolüyle)
  engeller.
- **KESİN SINIR (dokunulmaması gereken alan):** main.py'nin mikrofon,
  Gemini Live bağlantısı, Qt/UI event loop'u, Intent Router mantığı —
  kullanıcının açık, dar kapsamlı onayı olmadan DEĞİŞTİRİLMEZ. Bu proje
  boyunca uygulanan kural budur.

---

## 3. Agent Loop + tools_kopru.py — Doğru Davranış

- `agent_loop._decide_next_step()` her tick'te `tools_kopru.
  TOOL_DESCRIPTIONS`'ı okuyup Gemini'ye "elindeki araçlar bunlar, hangisini
  kullanmak istersin" diye sorar — **yeni bir araç eklemek için `agent_loop.py`'de
  hiçbir kod değişikliği gerekmez**, sadece `tools_kopru.py`'ye kayıt yeterlidir.
- Dispatch `tools_kopru.ALLOWED_TOOLS[tool_name](parameters)` ile yapılır.
- `is_destructive(tool, parameters)` onay akışını belirler:
  - `send_message`, `discovery_register`, `entegrasyon_uygula` → HER ZAMAN
    onay ister.
  - `file_controller` (action `delete`/`move`), `computer_settings`
    (action `shutdown`/`restart`/`lock_screen`/`lock`) → parametreye göre
    onay ister.
  - Listede olmayan/tanınmayan bir araç → güvenli varsayım: onay ister
    (`True`).
  - `ALLOWED_TOOLS` içindeki, yukarıdaki kümelere girmeyen her şey → onay
    istemez (`False`) — ör. `web_search`, `system_status`,
    `windows_system` (salt-okunur).
- **Doğru çalışıyor sayılması için:** her yeni entegre edilen araç HEM
  `ALLOWED_TOOLS` HEM `TOOL_DESCRIPTIONS`'a eklenmiş olmalı (ikisi
  senkron olmalı — `set(ALLOWED_TOOLS) == set(TOOL_DESCRIPTIONS)`), gerçek
  bir bağımlılık eksikse `capability_registry.guess_missing_deps()` bunu
  yakalamalı.

---

## 4. Brain Team — Doğru Davranış

### 4.1 Orkestrasyon
- `core/brain_orchestrator.py` **20 saniyede bir** `_tick()` çalıştırır.
- `_tick()` SIRASI: önce `watchdog.scan_and_apply()` (ölü/takılı görev
  temizliği), sonra kuyruktan **SADECE pending[0]**'ı işler — yani kuyruk
  tek seferde tek görev işler, paralel değil.
- **14. BACKUP KURALI:** Coder AI'ye bir dosya değişikliği isteği gitmeden
  ÖNCE backup alınır, security_ai onayından SONRA gerçek yazma yapılır.
  Coder AI'nin KENDİSİ backup almaz/onay istemez — bu sıralama
  orchestrator'ın sorumluluğundadır.

### 4.2 Beyinler (her biri `BaseBrain`'den türer, `brains/base_brain.py`)
- **planner_ai** — hedefi küçük görevlere böler, öncelik/sıra belirler.
- **coder_ai** — dosyanın TAM yeni içeriğini üretir; `.py` dosyaları için
  yazmadan ÖNCE kendi kendine `ast.parse` ile sözdizimi doğrular (geçersizse
  YAZMAZ, `BrainError` fırlatır).
- **security_ai** — riskli değişiklikleri onaylar/reddeder.
- **auditor_ai** — sonucu denetler.
- **executor_ai** — `_ALLOWED_ACTIONS` içindeki sabit eylemleri çalıştırır
  (`file_controller`, `backup_create`, `backup_rollback`, `vault_encrypt`,
  `vault_decrypt`, `github_search`, `windows_system`); `send_message`
  eylemini DOĞRUDAN çalıştırmayı REDDEDER (`BrainError`).
- Her beyin KENDİ hata sınırına sahiptir — bir beynin hatası diğerlerine
  veya Jarvis'in geri kalanına sızmaz (try/except `call()` içinde).

### 4.3 LLM Çağrı Zinciri (2026-09-16/17'de doğrulanan doğru davranış)
- `BaseBrain.call_llm()`: önce Gemini'yi **45 saniye** sabit timeout
  (`LLM_CALL_TIMEOUT_SECONDS`) ile dener, `max_attempts=1` (Gemini
  katmanında tekrar denemez — tek başarısızlık hemen Ollama'ya düşer).
- Gemini başarısız/timeout olursa `generate_with_fallback(...,
  ollama_timeout=30.0)` ile yerel Ollama'ya düşer.
- **Toplam en kötü durum: ~75 saniye** (45+30) — eski ~212 saniyelik
  takılmaların düzeltilmiş hâli budur.
- `call_llm_json()`: yanıtı `json.loads` ile ayrıştırır. Model bazen büyük/
  çok satırlı içerikleri (ör. tam bir .py dosyası) standart JSON kaçışı
  yerine Python'un üçlü tırnak (`"""`) sözdizimiyle sarmalıyor — bu GEÇERSİZ
  JSON'dur. **2026-09-17'de eklenen düzeltme:** bu bilinen bozuk kalıp
  tanınıp otomatik onarılıyor (`_repair_triple_quoted_json`); tanınmayan
  bir bozukluk olursa orijinal hata olduğu gibi raporlanır, hiçbir şey
  icat edilmez.
- **Not:** `agent_loop.py`, `self_improve.py`, `discovery.py` (×3),
  `entegrasyon.py` bu 30 saniyelik sıkı Ollama timeout'unu KULLANMAZ —
  onlar `ollama_timeout` parametresini geçmediği için `local_llm.py`'nin
  varsayılanı olan **120 saniye**yi kullanmaya devam eder. Bu BİLİNÇLİ bir
  tercihtir: bu akışlar (özellikle self_improve/entegrasyon) tam dosya
  üretimi gibi uzun üretim pencerelerine ihtiyaç duyar; kullanıcıyla bu
  konuşulmuş ve şu an için dokunulmaması kararlaştırılmıştır.

### 4.4 Görev Yaşam Döngüsü ve Watchdog (`core/task_manager.py` + `core/watchdog.py`)
- Durumlar: `pending → running → completed` veya `failed`/`cancelled`;
  ayrıca `waiting_approval` (kullanıcı onayı bekleniyor).
- `watchdog._ACTIVE_STATUSES = {"pending", "running"}` — **`waiting_approval`
  BİLEREK bu kümede DEĞİL**: onay bekleyen bir görev "takılmış" sayılmaz,
  kararı kullanıcıya aittir, otomatik `failed` yapılmaz.
- `STALL_WARNING_SECONDS = 30 dakika` → sadece işaretlenir
  (`payload["stalled"]=True`), durum değişmez.
- `DEAD_TASK_SECONDS = 2 saat` → `pending`/`running` durumundaki görev
  otomatik `failed` yapılır (kuyruğun sonsuza kadar bloke kalmasını önler).
- Bu tarama `_tick()`'in HER turunda, pending görev seçiminden ÖNCE çalışır
  ve tek bir görevdeki hata diğerlerinin taranmasını engellemez.

---

## 5. Capability (Yetenek) Sistemi — Doğru Davranış

- `actions/capability_registry.py`: main.py/tools_kopru.py'yi **ASLA
  import etmez** (Gemini Live/mikrofon/Qt yan etkilerini tetiklememek
  için) — SADECE dosyaları metin olarak okuyup `ast.parse` +
  `ast.literal_eval` ile `TOOL_DECLARATIONS`/`ALLOWED_TOOLS`/
  `TOOL_DESCRIPTIONS`'ı çıkarır.
- Risk sınıflandırması: `_ALWAYS_HIGH_RISK` (send_message,
  discovery_register, entegrasyon_uygula), `_CONDITIONAL_RISK`
  (file_controller, computer_settings, windows_system), geri kalanı
  `ALLOWED_TOOLS`'taysa `low`, değilse `unknown`.
- `discovered_*.py` araçları için `guess_missing_deps()` ile eksik
  bağımlılık kontrolü yapılır — SADECE bilinen üçüncü-parti paket
  isimleri (`_KNOWN_THIRD_PARTY_IMPORTS`) kontrol edilir, tanınmayan bir
  import asla "eksik" diye yanlış-pozitif raporlanmaz.
- `actions/capability_resolver.py`, `capability_registry.get_capabilities()`
  sonucunu kullanarak (ör. `windows_system`'ın gerçekten kayıtlı olup
  olmadığını) yapılandırılmış görev dağıtımını (structured dispatch)
  doğrular.

---

## 6. Keşif, Entegrasyon ve Self-Improve — Doğru Davranış

- `actions/discovery.py`: GitHub'da yeni araç adayları arar, gap-analizi
  ve kullanılabilirlik analizi yapar (`capability_registry.
  get_capability_summary()` üzerinden), sonucu kullanıcı onayına sunar
  (`discovery_register` onay gerektirir).
- `actions/entegrasyon.py`: onaylanan bir adayı projeye gerçekten
  entegre eder (`entegrasyon_uygula` onay gerektirir), `_verify_module()`
  ile `guess_missing_deps()` kullanarak doğrular.
- `actions/self_improve.py`: Jarvis'in KENDİ kod tabanını otonom olarak
  iyileştirmeye çalışan döngü. **Dikkat:** bu döngü, elle yapılmış
  düzeltmeleri de (kod "iyileştirmeye açık" göründüğü sürece) kendi
  versiyonuyla EZEBİLİR — bu proje sırasında gerçekten yaşanmıştır
  (`capability_registry.py`'nin elle yapılan düzeltmesi self_improve
  tarafından bir kez ezilip yeniden uygulanmak zorunda kalınmıştır).
  Şu an için bu döngüyü belirli dosyalardan hariç tutan bir mekanizma
  YOK — kullanıcı bu fikri değerlendirip "iptal edelim" demiştir, yani
  bilinçli olarak eklenmemiştir.

---

## 7. Güvenlik / Onay Modeli — Doğru Davranış (özet ilke)

- Hem Agent Loop hem Brain Team için ortak ilke: **yıkıcı/geri alınamaz
  eylemler (silme, taşıma, sistem ayarı değiştirme, mesaj gönderme, dış
  entegrasyon) HER ZAMAN kullanıcı onayı gerektirir; salt-okunur/bilgi
  sorgulayan eylemler onay gerektirmez.**
- Yeni bir araç eklenirken varsayılan GÜVENLİ tarafta durulur: tanınmayan
  bir araç onay ister (izin listesine bilerek eklenmeden asla "onaysız
  çalışabilir" hâle gelmez).
- `windows_shell.py` (plandaki yeni yetenek) bu ilkeye örnektir: SADECE
  sabit bir allowlist'teki komut adlarını (`process_list`, `service_list`,
  `system_info`, `cpu_load`, `disk_info`, `network_info`,
  `network_connections`) kabul eder; ham/keyfi komut, process
  kill/servis durdur/dosya sil/registry/yönetici yetkisi gibi hiçbir şey
  KOD YOLUNDA bile yoktur — güvenlik "doğrulamayla" değil "mimari olarak
  mümkün olmama" ile sağlanır.

---

## 8. Şu An Doğrulanmış Durum (2026-09-16/17 itibarıyla)

Aşağıdakiler bu oturumda gerçek dosya okuma + cihazda dağıtım + geri okuma
ile doğrulanmıştır (varsayım değildir):

- `main.py` satır 1413 f-string söz dizimi hatası düzeltildi, kullanıcı
  kendi cihazında temiz başlangıç ile doğruladı.
- `actions/capability_registry.py` tamamen işlevsel hale getirildi
  (önceden `pass` gövdeli, sahte `"path/to/main.py"` içeren bir iskeletti).
- Brain Team LLM timeout zinciri (45s Gemini + 30s Ollama, toplam ~75s)
  çalışır durumda; ölü/takılı görev tespiti (`watchdog.py`) tasarlandığı
  gibi çalışıyor.
- `coder_ai`'nin üçlü-tırnak JSON hatası onarım mekanizmasıyla düzeltildi.
- `discovered_jarvis_registry` (alakasız bir AWS aracı) kayıttan
  kaldırıldı; iki ölü kopya dosya (`file_controller-1.py`,
  `executor_ai-1.py`) içerik olarak nötürleştirildi (cihazda fiziksel
  silme aracı olmadığı için).
- `requirements.txt`'e eksik `jc` bağımlılığı eklendi (kullanıcının
  `pip install` çalıştırması gerekiyor).

## 9. Hâlâ Açık Olan Noktalar (bilinçli olarak dokunulmadı)

- `agent_loop.py`/`self_improve.py`/`discovery.py`/`entegrasyon.py`'nin
  120 saniyelik Ollama timeout'u sıkılaştırılmadı (uzun üretim pencereleri
  gerektikleri için).
- `TaskManager`'ın `"running"` durumu için ayrı bir heartbeat/canlılık
  sinyali yok (sadece `watchdog`'un 2 saatlik eşiği var).
- `self_improve.py`'yi belirli "kritik" dosyalardan (ör.
  `capability_registry.py`) hariç tutacak bir mekanizma kullanıcı
  tarafından bilerek eklenmedi.
- `windows_shell.py` planı (salt-okunur Windows sistem sorgu aracı) henüz
  uygulanmadı — sadece plan olarak var (`/root/.claude/plans/
  peppy-puzzling-minsky.md`), kullanıcı onayı/tetiklemesi bekliyor.
