# MuratJARVIS 25.1.0 mimarisi ve doğrulama sınırları

## Yapı

`src/jarvis/` kurulabilir uygulama paketidir. `pyproject.toml` tek paket
metadata ve bağımlılık kaynağıdır. `jarvis.paths` kod ile kullanıcı verisini
ayırır; `JARVIS_HOME` verilmişse tüm yazılabilir alt dizinler bu kökün altında
oluşur. Paket ağacının salt-okunur kurulumlarda da çalışması hedeflenir.

`src/jarvis/__main__.py` iki açık giriş yolu sunar:

- Normal `python -m jarvis` yolu mevcut backend, UI, ses ve ağ akışını başlatır.
- `python -m jarvis --ui-only` yalnızca `JarvisUI` oluşturur; `jarvis.main`,
  Gemini, ses, dashboard ve backend task loop'u import edilmez.

UI-only yolu tanılama içindir; API anahtarı uydurmaz ve kullanıcı verisini
onay olmadan değiştirmez. UI'nin gerçek `JarvisUI` davranışı PyQt ve işletim
sistemiyle ayrıca değerlendirilmelidir.

## Veri ve sır kuralları

API anahtarı önce `GEMINI_API_KEY`, sonra kullanıcı yapılandırması üzerinden
okunur. `save_config` yalnızca kullanıcı veri dizinine yazar. Sertifikalar,
loglar, görevler ve bellek de aynı ayrık veri kökünü kullanır. Testler ayrı bir
geçici `JARVIS_HOME` ile yapılır; mevcut kullanıcı geçmişi kullanılmaz.

## Windows başlatıcıları

Kök `KUR_WINDOWS.cmd` kendi script dizinine geçer, Python 3.12 veya 3.11'i
seçer, eksik `.venv` oluşturur ve editable kurulumu yapar. Var olan uyuşmayan
venv silinmez. `BASLAT_WINDOWS.cmd` normal başlatmayı, `UI_ONIZLE_WINDOWS.cmd`
ise backend'siz UI-only yolu çalıştırır. Hiçbiri yönetici istemez, kalıcı
ExecutionPolicy değiştirmez veya API yapılandırmasını üzerine yazmaz.

## Test sözleşmesi

Otomatik testler offline ve donanımsızdır. Ağ, canlı API, gerçek mikrofon,
hoparlör, kamera, dashboard, firewall ve Windows kabulü `tests/manual/`
kapsamındadır. Bu alanlar sandbox testlerinin geçtiği gerekçesiyle doğrulanmış
sayılmaz. Dosya işlemleri kullanıcı onayı olmadan otomatikleştirilmez.
