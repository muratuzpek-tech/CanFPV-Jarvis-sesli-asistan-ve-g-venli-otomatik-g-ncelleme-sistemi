"""
test_windows_shell.py — actions/windows_shell.py'nin GERÇEK Windows'ta,
gerçek PowerShell ile çalıştığını doğrular.

NEDEN BU BETİK VAR: Claude'un sandbox'ı Linux'tur, `powershell` orada yok -
bu yüzden Claude sadece "powershell bulunamadı" hata yolunun düzgün
çalıştığını doğrulayabildi (gerçek bir hata, gerçek bir kod yolu - ama
komutların GERÇEKTEN çalışıp doğru veri döndürdüğünü kanıtlamaz). Bu betik
7 izinli komutun hepsini gerçekten çalıştırıp özetler.

KULLANIM (FINAL_BUILD klasöründe, PowerShell'de):
    python test_windows_shell.py

Bu betik SADECE OKUR - hiçbir kalıcı değişiklik yapmaz, hiçbir dosyaya
yazmaz.
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1] / "src" / "jarvis"
sys.path.insert(0, str(BASE_DIR))

from jarvis.actions.windows_shell import run, list_allowed_commands  # noqa: E402


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    print(f"İzinli komutlar: {', '.join(list_allowed_commands())}\n")

    all_ok = True
    for command_name in list_allowed_commands():
        print(f"--- {command_name} ---")
        raw = run({"command_name": command_name})
        result = json.loads(raw)
        print(f"  ok={result['ok']}  exit_code={result['exit_code']}  "
              f"süre={result['duration_ms']}ms")
        if result["ok"]:
            preview = result["stdout"][:300].replace("\n", " ")
            print(f"  stdout (ilk 300 karakter): {preview}")
        else:
            print(f"  stderr: {result['stderr'][:300]}")
            all_ok = False
        print()

    print("=" * 60)
    print("SONUÇ:", "TÜM KOMUTLAR BAŞARILI" if all_ok else "BAZI KOMUTLAR BAŞARISIZ (yukarıya bakın)")
    print("=" * 60)

    print("\nEk güvenlik doğrulaması (bu makinede de çalışması gerekir):")
    bad = json.loads(run({"command_name": "process_list; Remove-Item C:\\ -Recurse"}))
    print(f"  Injection denemesi reddedildi mi? {'EVET' if not bad['ok'] else 'HAYIR (SORUN!)'}")
    unknown = json.loads(run({"command_name": "shutdown_everything"}))
    print(f"  Bilinmeyen komut reddedildi mi? {'EVET' if not unknown['ok'] else 'HAYIR (SORUN!)'}")


if __name__ == "__main__":
    main()
