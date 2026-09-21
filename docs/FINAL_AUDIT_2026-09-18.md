# MuratJARVIS 25.1.0 Paketleme ve Başlatma Notu

**Kapsam:** Bu not yalnızca paketleme, kullanıcı veri yolu, offline UI-only
başlatma ve Windows yardımcı betikleri için hazırlanmıştır. Testler Linux
sandbox'ında, geçici `JARVIS_HOME` ile ve gerçek API, ağ, ses, kamera,
dashboard veya firewall başlatılmadan yürütülür.

## Doğrulanan yerel kontroller

| Kontrol | Kapsam |
| --- | --- |
| `pyproject.toml` metadata ve sürüm | 25.1.0, Python 3.11–3.12 aralığı |
| `python -m jarvis --ui-only` giriş yolu | UI mock ile backend import edilmeden kontrol |
| Kullanıcı veri yolu | Geçici `JARVIS_HOME`; paket ağacına yazma yok |
| Windows `.cmd` yardımcıları | Klasör bağımsızlığı, yerel `.venv`, Python 3.11/3.12 seçimi statik olarak kontrol |
| Post-install kontrolü | Offline; geçici dizin ve paket yolları |
| Legacy test wrapper | Yalnızca tarihsel script tarzı testlerin açık listesi |

Bu kontroller gerçek Windows'ta `.cmd` çalıştığını, gerçek mikrofonu veya canlı
Gemini oturumunu kanıtlamaz.

## Kullanıcı verisi ve sırlar

Kaynak kodu ile kullanıcı verisi ayrıdır. `JARVIS_HOME` testlerde mutlaka
ayrı bir geçici dizine yönlendirilmelidir. API anahtarı ortam değişkeninden
veya kullanıcı yapılandırmasından okunabilir; testler sahte anahtar yazmaz ve
anahtarı çıktıya basmaz. Kurulum kod dizinine log, görev, bellek veya sertifika
yazmamalıdır.

## Windows sınırları

`KUR_WINDOWS.cmd` mevcut ve yanlış sürümlü sanal ortamı silmez; hata vererek
kullanıcı kararını bekler. `BASLAT_WINDOWS.cmd` ve `UI_ONIZLE_WINDOWS.cmd`
kendi script klasörlerine geçtikleri için `C:\Windows\System32` gibi başka bir
çalışma dizininden çağrılabilir. Yönetici yetkisi, kalıcı ExecutionPolicy
değişikliği ve otomatik API anahtarı yazımı yoktur.

Windows mikrofon gizliliği, giriş cihazı/host API seçimi, sürücü davranışı,
hoparlör, kamera, DPI ve Gemini Live bağlantısı gerçek kullanıcı bilgisayarında
ayrıca kabul edilmelidir. Bu not bunların düzeldiğini iddia etmez.

## Otomatik onay ve ağ

Paketleme yolu kullanıcı adına dosya onaylamaz, dosya silmez ve ağ çağrısı
yapmaz. Canlı arama, dashboard, firewall ve gerçek cihaz testleri manuel
kapsamdadır; CI/offline `pytest` tarafından çalıştırılmaz.
