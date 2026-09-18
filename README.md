# MuratJARVIS

Gemini Live tabanlı, çok beyinli (planner / coder / auditor / research / security / memory / executor)
sesli masaüstü asistanı. PyQt6 arayüz, yerel dashboard (telefondan uzaktan kumanda), ekran/kamera
analizi, dosya işlemleri, web araştırması ve kendi kendini geliştirme modülleri içerir.

## Kurulum

Gereken Python: **3.11 veya 3.12** (kod `asyncio.TaskGroup` ve `except*` kullanıyor; 3.13+ doğrulanmadı).

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

### Linux / macOS / geliştirme

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## API anahtarı

Anahtar **koda veya depoya yazılmaz**. Öncelik sırası:

1. `GEMINI_API_KEY` ortam değişkeni
2. Kullanıcı veri dizinindeki `config/api_keys.json` (uygulama içindeki kurulum ekranı buraya yazar)

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "ANAHTAR", "User")
```

`docs/api_keys.example.json` örnek şemayı gösterir.

## Çalıştırma

```bash
jarvis            # veya:  python -m jarvis
jarvis-cli        # terminal istemcisi
```

## Dosyalar nerede?

| İçerik | Konum |
| --- | --- |
| Kod (salt okunur) | `src/jarvis/` |
| Kullanıcı verisi | Windows `%LOCALAPPDATA%\MuratJARVIS`, macOS `~/Library/Application Support/MuratJARVIS`, Linux `~/.local/share/MuratJARVIS` |
| Hafıza / log / görev / sırlar | veri dizini altında `memory/`, `logs/`, `tasks/`, `config/` |

Ortam değişkenleri:

| Değişken | Etkisi |
| --- | --- |
| `JARVIS_HOME` | Tüm kullanıcı verisini verilen dizine taşır |
| `JARVIS_API_KEYS` | `api_keys.json` için özel yol |
| `JARVIS_FACE` | HUD'da gösterilecek görsel |
| `JARVIS_NO_FIREWALL_SETUP=1` | Dashboard'ın Windows güvenlik duvarı/UAC kurulumunu atlar |

## Geliştirme

```bash
ruff check .                    # lint
pytest                          # otomatik testler
pytest tests/manual/...         # canlı API/GUI gerektiren testler (CI'da çalışmaz)
```

`developer_archive/` yalnızca tarihsel kayıttır (eski yedekler, v25 çalışma verisi, tamamlanmamış
`openjarvis` ağacı); pakete dahil edilmez ve import edilmez.

Ayrıntılı mimari ve v25'te bulunan sorunların listesi: [`docs/MIMARI.md`](docs/MIMARI.md).
