# Ücretsiz yerel Dev Agent sağlayıcıları

Jarvis'e iki opsiyonel yerel sağlayıcı eklendi:

- `ollama`: Varsayılan sağlayıcı; `127.0.0.1:11434` üzerinden çalışır.
- `open-interpreter`: Sadece bilgisayara ayrıca kurulmuşsa ve açıkça seçilmişse kullanılır.

## Yapılandırma

```powershell
$env:JARVIS_DEV_AGENT_PROVIDERS = "ollama,open-interpreter"
$env:JARVIS_OLLAMA_MODEL = "qwen2.5-coder:7b"
```

Ollama için örnek:

```powershell
ollama pull qwen2.5-coder:7b
```

Open Interpreter opsiyoneldir; kurulumu yapılmadıysa fallback zinciri Ollama'yı
kullanmaya devam eder.

## Güvenlik sınırı

`dev_agent_providers.py` yalnızca metin üretir. Dönen kodu otomatik uygulamaz,
`src/jarvis` içine yazmaz ve paket kurmaz. Patch uygulama, test çalıştırma ve
kullanıcı onayı mevcut `dev_agent` akışında kalmalıdır. Her provider izole
workspace ile çağrılmalıdır.

Bu değişiklik hiçbir dosyayı silmez.
