# Sanal Beyin / Digital Twin — self_improvement/

Bu klasör, "JARVIS — FAZ 9 Uyumlu Sanal Beyin / Digital Twin Geliştirme
Promptu" belgesinde tanımlanan kontrollü araştırma/deney laboratuvarının
**AŞAMA A (temel klasör + state sistemi)** ve **AŞAMA B (Orchestrator +
Message Bus entegrasyonu)** çıktılarını içerir.

## Kesin sınır (bu aşamada)

AŞAMA B ile birlikte bu paket artık gerçek Jarvis'in MessageBus'ına
BAĞLANABİLİYOR (bkz. aşağıdaki "AŞAMA B" bölümü) — ama SADECE salt-okunur
üç beyin (research_ai, security_ai, auditor_ai) üzerinden, ve SADECE bu
paketin kod içinden ÇAĞRILDIĞINDA. Hiçbir dosya gerçek Jarvis dosyalarını
(main.py, core/, brains/, actions/) DEĞİŞTİRMEZ; hiçbir arka plan
döngüsü/otomatik tetikleyici EKLENMEDİ - bu modüller sadece elle/komutla
çağrılırsa çalışır. Bu, orijinal belgenin "her aşama küçük adımlarla,
onay alınmadan devam edilmez" ilkesiyle tutarlıdır (bkz. §42).

## Klasör yapısı

```text
self_improvement/
├── knowledge/              # AŞAMA G'de dolacak: problem/hipotez/sonuç kayıtları
├── sandbox/
│   ├── workspace/          # AŞAMA D: izole deney çalışma alanı
│   ├── experiments/        # AŞAMA D: deney sırasında üretilen geçici dosyalar
│   ├── artifacts/          # AŞAMA D: deney çıktıları (prototip kod vb.)
│   ├── logs/                # AŞAMA D: sandbox process logları
│   └── (.venv/ HENÜZ YOK — aşağıya bakın)
├── virtual_brain/
│   ├── orchestrator/       # AŞAMA B: deney yönetimi için yardımcı orchestrator
│   ├── simulations/        # AŞAMA E: Digital Twin simülasyon kayıtları
│   ├── hypotheses/         # AŞAMA C: hipotez kayıtları
│   ├── prototypes/         # AŞAMA D: sandbox'ta üretilen prototipler
│   ├── benchmarks/         # AŞAMA F: A/B karşılaştırma sonuçları
│   ├── experiments/        # AŞAMA C: Experiment Manager'ın deney kayıtları (EXP-YYYYMMDD-NNN)
│   ├── brain_state/        # BU AŞAMADA DOLU: state.json + state_manager.py
│   └── reports/            # AŞAMA H: deney raporları (bkz. orijinal belge §39)
├── proposals/               # AŞAMA H: DEVELOPMENT PROPOSAL kayıtları
└── staging/                 # AŞAMA I/J: kullanıcı onayından sonraki staging alanı
```

Boş klasörler bu aşamada yalnızca bir `.gitkeep` dosyasıyla iskelet olarak
tutuluyor; içerikleri ait oldukları aşamada doldurulacak.

## `.venv/` neden bu aşamada yok

Orijinal belgenin §17'si (Package Güvenliği) sandbox'ın kendi Python
sanal ortamını kullanmasını istiyor. Gerçek bir `.venv` oluşturmak
(`python -m venv`) bilgisayarınızda ÇALIŞTIRILMASI gereken bir komuttur —
ben dosya okuma/yazma yapabiliyorum ama bilgisayarınızda komut
çalıştıramıyorum, dolayısıyla bu adımı burada sahte biçimde taklit etmek
yerine gerçek zamanı geldiğinde (AŞAMA D — Sandbox Controller) size tam
komutu vereceğim. Şimdiden çalıştırmak isterseniz:

```powershell
cd "C:\Users\murat\Desktop\MuratJarvis\FINAL_BUILD\self_improvement\sandbox"
python -m venv .venv
```

## State sistemi

`virtual_brain/brain_state/state.json`, Sanal Beyin'in güncel durumunu
tutar (FAZ 8 Brain Center'ın §34'te tarif ettiği alanlarla uyumlu:
status, research_status, experiments_count, tests_count, audits_count,
security_last_result, pending_proposals, latest_experiment_id/result).
Bu dosyayı elle düzenlemeyin — `state_manager.py`'deki `get_state()` /
`update_state()` fonksiyonları, `core/task_manager.py` ile AYNI atomik
yazma desenini (tempfile + `Path.replace`) kullanarak güvenli okuma/yazma
sağlıyor.

## AŞAMA A durumu

**TAMAMLANDI** — klasör iskeleti + bağımsız state sistemi.

## AŞAMA B — Orchestrator + Message Bus entegrasyonu

**TAMAMLANDI.** `virtual_brain/orchestrator/` altında:

- `experiment_task_manager.py` — `core/task_manager.TaskManager` ile AYNI
  arayüz ve atomik-yazma deseni, ama TAMAMEN AYRI bir dosyaya
  (`experiments.json`, bu klasörde) yazar. **Neden ayrı:** gerçek
  `tasks/brain_tasks.json`'a eklenen her görev, gerçek Orchestrator'ın
  arka plan döngüsü tarafından otomatik ÇALIŞTIRILIYOR - deneyler oraya
  karışsaydı "deney" olmaktan çıkıp denetimsiz gerçek görevlere dönerdi.
  Durumlar §10'a uygun: pending/running/waiting_approval/completed/
  failed/cancelled/**rollback**. Deney ID'leri §11 formatında:
  `EXP-YYYYMMDD-NNN`.
- `virtual_orchestrator.py` — gerçek `core/brain_orchestrator.py`'nin
  ZATEN çalışan MessageBus'ını kullanır (yeni bir bus icat etmez, §9),
  ama SADECE `research_ai`, `security_ai`, `auditor_ai`'ye mesaj
  göndermeye izin verir (`ALLOWED_BRAINS`). `coder_ai`/`executor_ai`/
  `planner_ai`/`memory_ai`'ye erişim bu aşamada KOD SEVİYESİNDE
  engellendi (`VirtualBrainSafetyError`) - bunlar gerçek dosya
  değiştirir/gerçek eylem çalıştırır, sandbox + onay zinciri (AŞAMA D/H)
  kurulmadan açılmayacak.
- `self_test.py` — sahte (mock) bir bus ile ÇEVRİMDIŞI mantık testi
  (gerçek API anahtarı/gerçek Gemini çağrısı GEREKTİRMEZ). Bu ortamda
  çalıştırıldı, tüm kontroller (deney dosyasının ayrı olması, izinli
  beyinlerin çalışması, coder_ai'nin reddedilmesi) **BAŞARILI** sonuçlandı.

**Henüz yapılmayan / bilerek ertelenen:** gerçek research_ai/security_ai/
auditor_ai'ye GERÇEK bir çağrı ile "canlı duman testi" — bu ancak gerçek
Jarvis (main.py) çalışırken, ondan içeriden yapılabilir; bu paketi
bağımsız çalıştırıp `get_real_bus()`'ı tetiklemeyin (gerçek arka plan
döngüsünü başlatır, bkz. `virtual_orchestrator.py` dosya başı UYARI).

## AŞAMA C — Experiment Manager

**TAMAMLANDI.** `virtual_brain/orchestrator/experiment_manager.py`,
AŞAMA B'nin tek-adımlık çağrılarını birleştirip TAM bir deney zinciri
yönetiyor:

```text
HYPOTHESIS -> RESEARCH -> AUDIT -> SECURITY -> AWAITING_SANDBOX
```

- **Neden "AWAITING_SANDBOX"da duruyor, daha ileri gitmiyor:** §12'nin tam
  sırası HYPOTHESIS → RESEARCH → **PROTOTYPE → TEST → BENCHMARK** →
  AUDIT → SECURITY → PROPOSAL. Kalın yazılan üç aşama izole bir çalışma
  alanı (AŞAMA D — Sandbox Controller) gerektiriyor; bu henüz kurulmadı.
  Var olmayan bir sandbox'ı taklit edip "test edildi" gibi görünen SAHTE
  sonuç üretmek §43'e ("hiçbir deney otomatik olarak production'a
  dönüşmez, her aşama gerçek kontrolden geçmeli") doğrudan aykırı olurdu
  — bu yüzden manager dürüstçe burada durup `final_decision` alanına
  "sandbox bekleniyor" yazıyor, fiktif bir sonuç uydurmuyor.
- Her deney kaydı artık §11'in TAM alan setini taşıyor (research_sources,
  changed_files, dependencies, security_result, auditor_result,
  approval_status, final_decision, vb).
- `_log_hypothesis()`: her deneyin ORİJİNAL hipotezi, deneyin geri kalanı
  ne olursa olsun değişmeyen, silinmeyen bir kayıt olarak
  `virtual_brain/hypotheses/hypotheses.jsonl`'a ekleniyor (§12 + §26
  "başarısız denemeler değerlidir" ilkesiyle tutarlı).
- Her deney AWAITING_SANDBOX'a ulaştığında, §39 DENEY RAPORU şablonuna
  uygun bir `.md` raporu otomatik olarak `virtual_brain/reports/
  <experiment_id>.md`'ye yazılıyor.
- `self_test_experiment_manager.py`: sahte bus ile TAM zinciri
  (start → 4x advance → AWAITING_SANDBOX → rapor dosyası kontrolü →
  terminal durumun idempotent olduğu → `run_to_awaiting_sandbox()`
  kısayolu) uçtan uca doğruluyor. Bu ortamda çalıştırıldı: **BAŞARILI.**

## Sırada: AŞAMA D — Sandbox Controller

AŞAMA C'nin bilerek yarım bıraktığı yer burası: gerçek bir izole çalışma
alanı olmadan PROTOTYPE/TEST/BENCHMARK aşamalarına geçilemez. AŞAMA D bu
izolasyonu kuracak — ve tam da bu noktada, incelemede gündeme gelen üç
açık karar KRİTİK hale geliyor (artık ertelenemez):

1. **dev_agent.py'nin durumu** — sandbox + onay zinciri kurulurken,
   mevcut `actions/dev_agent.py`'nin gerçek dosyaları hâlâ bu zincirin
   DIŞINDAN (denetimsiz) değiştirmeye devam edip etmeyeceği netleşmeli.
2. **`src/openjarvis/`'in durumu** — kullanılmayan ama duran bu üçüncü
   backup/rollback sistemi, sandbox tasarımını karıştırmadan önce
   silinsin mi, yoksa öylece mi kalsın?
3. **FAZ 5/7/32'nin gerçek dosya karşılıkları** — sandbox'tan çıkan bir
   önerinin kullanıcıya onaylatılması (AŞAMA H/J) için Telegram Approval
   mekanizmasının gerçekte nerede olduğu gerekecek.

Bu üçü netleşince AŞAMA D'ye geçebiliriz.
