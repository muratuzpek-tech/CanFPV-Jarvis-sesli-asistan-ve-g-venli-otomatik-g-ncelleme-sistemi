# Mimari ve v25'ten taşınan düzeltmeler

## 1. Yapı

```
murat-jarvis/
├── pyproject.toml            # tek bağımlılık/paket kaynağı (setup.py + requirements.txt yerine)
├── README.md
├── src/
│   └── jarvis/               # TEK uygulama paketi (import kökü: jarvis.*)
│       ├── __main__.py       # python -m jarvis / "jarvis" komutu
│       ├── paths.py          # kod dizini ↔ kullanıcı veri dizini ayrımı
│       ├── main.py           # Gemini Live oturumu + araç yönlendirme
│       ├── ui.py             # PyQt6 HUD
│       ├── actions/          # araçlar (dosya, web, ekran, otomasyon, keşif...)
│       ├── brains/           # planner / coder / auditor / research / security / memory / executor
│       ├── core/             # orkestratör, mesaj yolu, watchdog, LLM istemcisi, sır yönetimi
│       ├── dashboard/        # FastAPI + statik telefon arayüzü
│       ├── memory/           # hafıza ve yapılandırma yöneticisi (VERİ DEĞİL, kod)
│       ├── self_improvement/ # sanal beyin deneyleri
│       ├── config/           # işletim sistemi/konfig yardımcıları
│       └── assets/           # ikonlar
├── scripts/                  # setup_windows.ps1, post_install_check.py
├── tests/                    # pytest ile koşan testler
│   └── manual/               # canlı API anahtarı / GUI gerektirenler
├── docs/
└── developer_archive/        # eski yedekler, v25 çalışma verisi, ölü kod (paketlenmez)
```

Kural: **kod salt okunur, veri yazılabilir.** Kod dizinine hiçbir zaman log, hafıza, görev veya
anahtar yazılmaz; hepsi `jarvis.paths` üzerinden kullanıcı veri dizinine gider.

## 2. v25'te bulunan sorunlar ve yapılan düzeltmeler

### Kritik / güvenlik

| Sorun | Sonucu | Düzeltme |
| --- | --- | --- |
| `config/certs/jarvis.key` gerçek RSA özel anahtarı paketin içinde dağıtılıyordu | Paketi eline geçiren herkes aynı anahtara sahip → dashboard TLS'i koruma sağlamıyordu | Anahtar pakete girmiyor; `secure_config.ensure_self_signed_cert()` ilk çalıştırmada makineye özel üretiyor |
| `config/api_keys.json` kurulu kodun içinde tutuluyor ve oraya yazılıyordu | Anahtarın zip'e sızması, "Program Files" altında yazma hatası, güncellemede kaybolma | Anahtar `%LOCALAPPDATA%\MuratJARVIS\config\api_keys.json` içinde; okuma sırası env → kullanıcı dizini → eski kurulum |
| `dashboard/server.py` güvenlik duvarı betiğini `shell=True` ile çalıştırıyordu | Kabuk enjeksiyonuna açık yüzey, taşınamaz | `[%COMSPEC%, "/c", bat]` argüman listesi; `JARVIS_NO_FIREWALL_SETUP=1` ile tamamen kapatılabilir |
| `guvenli_kasa.py` şifre çözerken başlıktaki iterasyon sayısını okuyup kullanmıyordu | `ITERATIONS` bir gün değişirse eski kasa dosyaları açılamaz hale gelirdi | `derive_key(password, salt, iterations)` |

### Çalışma zamanı hataları

| Sorun | Sonucu | Düzeltme |
| --- | --- | --- |
| `actions/dev_agent.py` içinde `os` import edilmeden `os.name` kullanılıyordu | Windows'ta `.cmd` komutu çalıştırılınca `NameError` | `import os` eklendi |
| `main.py` araç şemasında `confirm_code` anahtarı iki kez tanımlıydı | İlk (delete_all_files'ı da kapsayan) açıklama sessizce siliniyordu | Tek, her iki işlemi kapsayan tanım |
| `main()` kökte var olmayan `face.png` dosyasını arıyordu | HUD sessizce yüzsüz açılıyordu | Pakete gömülü `assets/jarvis_icon.png`, `JARVIS_FACE` ile değiştirilebilir |
| `actions/entegrasyon.py` döngü değişkenini closure ile yakalıyordu | Yeniden denemede yanlış hata notu gönderme riski | Varsayılan argümanla bağlandı |
| 21 yerde `except` içinde `raise ... from` yoktu | Hata zinciri kayboluyor, kök neden görünmüyordu | Tümü zincirlendi |

### Yapı / bakım

| Sorun | Düzeltme |
| --- | --- |
| Tüm modüller kök dizinde (`actions/`, `brains/`, `core/` ...), `sys.path` hilelerine bağımlı | Tek `src/jarvis` paketi, `pip install -e .` ile kurulur |
| Eski `main.py.bak_*`, `ui.py.bak_*`, `ui_v4*` dosyaları ve Claude çıktıları kaynak ağacında | `developer_archive/` altına taşındı |
| `memory/`, `logs/`, `tasks/` kullanıcı verisi dağıtımın içinde | Kullanıcı veri dizinine taşındı (`jarvis.paths`) |
| Yarım kalmış `src/openjarvis` ağacı (eksik modüllere import) | `developer_archive/dead_code/openjarvis`; paket artık %100 import edilebiliyor |
| `setup.py` + `requirements.txt` + `setup_windows.ps1` üçlüsü çelişiyordu (betik Python 3.14'ü kabul ediyor, setup.py 3.13+'ı doğrulanmamış sayıyor) | Tek kaynak `pyproject.toml`, `requires-python = ">=3.11,<3.14"`; betik yalnızca 3.11/3.12 |
| Testler eski dizin düzenine göre yol kuruyordu, pytest "0 test" raporluyordu | Yollar düzeltildi, betik tarzı testler adlandırılmış pytest sonuçlarına dönüştürüldü, canlı API gerektirenler `tests/manual/`'a alındı |
| Lint yapılandırması yoktu | `ruff` yapılandırıldı, 464 bulgunun tamamı temizlendi (stil kuralları gerekçesiyle devre dışı) |

## 3. Geriye dönük uyum

- `jarvis/__init__.py` içindeki `_LegacyFinder`, `actions.*`, `core.*`, `brains.*` gibi eski
  düz import'ları `jarvis.*` karşılığına yönlendirir. Böylece dinamik olarak modül adı üreten
  `capability_resolver`, `discovery` ve `self_improve` çalışmaya devam eder.
- Proje kökünde `memory/` klasörü varsa (eski kurulum), veri dizini olarak o kök kullanılır;
  mevcut hafıza kaybolmaz.

## 4. Doğrulanan / doğrulanamayan

Bu ortamda (Linux, Python 3.11) doğrulandı: `compileall`, 90 modülün tamamının import'u,
`ruff check` temiz, `pytest` 20 test geçti, editable kurulum ve konsol betikleri.

Doğrulanamadı (gerçek Windows + canlı anahtar gerekir): Gemini Live ses akışı, mikrofon/hoparlör
seçimi, Windows UAC/güvenlik duvarı akışı, telefon dashboard'ı üzerinden uçtan uca kullanım.
