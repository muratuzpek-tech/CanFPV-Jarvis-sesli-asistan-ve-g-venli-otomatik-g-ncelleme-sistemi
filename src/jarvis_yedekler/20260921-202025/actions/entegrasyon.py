"""
entegrasyon.py — kullanıcının açık isteğiyle eklenen TAM OTOMATİK entegrasyon
adımı: discovery.py'nin Gemini'den "tool" değerlendirmesi aldığı bir şeyi,
KULLANICIYA SORMADAN Jarvis'in kendi çalışan koduna ekler.

AÇIKÇA KABUL EDİLEN RİSK (kullanıcıya söylendi, kullanıcı onayladı):
Bu, discovery.py'nin başındaki tasarım notunda anlatılan güvenlik sınırını
BİLEREK KALDIRIR. Buradaki tek koruma self_improve.py'nin ZATEN kullandığı
standart: tam proje yedeği + söz dizimi/import doğrulaması + otomatik geri
alma. Bu, "açıkça bozuk mu" sorusuna cevap verir — kötü niyetli ama
sözdizimi geçerli bir kodu YAKALAMAZ. Kullanıcıya bu sınırlama açıkça
anlatıldı.

Kapsam (bilerek dar tutuldu): bulunan yetenek, karantinadaki gerçek kod
okunarak Gemini'ye YENİ, TEK bir actions/discovered_<isim>.py modülü
yazdırılır (kaynak kod olduğu gibi kopyalanıp çalıştırılmaz — Gemini onu
okuyup Jarvis'in kendi mimarisine uygun bir sarmalayıcı/uyarlama yazar).
Bu modül SADECE agent_loop/tools_kopru üzerinden erişilebilir hale gelir
(tools_kopru.py'ye otomatik bir satır eklenir) - main.py'nin sesli komut
yüzeyine (TOOL_DECLARATIONS) OTOMATİK eklenmez, çünkü main.py canlı sesli
oturumu çalıştıran dosyadır ve oradaki bir hata tüm asistanı çökertebilir;
bu yüzden risk kasıtlı olarak agent_loop'un arka plan görevleriyle sınırlı
tutulur.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from jarvis.paths import memory_dir

MAX_ATTEMPTS      = 3
MODEL_NAME        = "gemini-flash-latest"
MAX_SOURCE_CHARS  = 8000   # Gemini'ye gonderilecek kaynak kod ust siniri


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
API_KEYS_PATH    = BASE_DIR / "config" / "api_keys.json"
TOOLS_KOPRU_PATH = BASE_DIR / "actions" / "tools_kopru.py"
LOG_PATH         = memory_dir() / "integration_log.jsonl"


def _get_api_key() -> str:
    from jarvis.core.secure_config import get_gemini_api_key
    return get_gemini_api_key()


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": datetime.now().isoformat(), **entry}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Entegrasyon] ⚠️ Log yazılamadı: {e}")


def _slugify(name: str) -> str:
    stem = Path(name).stem
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_").lower()
    return slug or "arac"


def _gather_source(quarantine_path: Path) -> str:
    """Karantinadaki kod dosyalarindan (oncelik .py) Gemini'ye gonderilecek
    bir ozet cikarir - MAX_SOURCE_CHARS ile sinirli."""
    parts = []
    total = 0
    py_files = sorted(quarantine_path.rglob("*.py"))
    other_files = [p for p in quarantine_path.rglob("*") if p.is_file() and p.suffix != ".py"]

    for f in py_files + other_files:
        if total >= MAX_SOURCE_CHARS:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        chunk = f"--- {f.relative_to(quarantine_path)} ---\n{text}\n"
        parts.append(chunk[: MAX_SOURCE_CHARS - total])
        total += len(chunk)

    return "\n".join(parts) or "(okunabilir kaynak kod bulunamadı)"


def _clean_code(text: str) -> str:
    text = text.strip()
    match = re.search(r"```[a-zA-Z]*\r?\n?(.*?)\r?\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


_INTEGRATION_PROMPT = """Sen Jarvis adli bir sesli asistan projesine yeni bir
YETENEK ekleyen bir Python muhendisisin. Asagida, internetten/Downloads'tan
bulunan bir arac/kutuphanenin GERCEK kaynak kodu (ozet) var.

GOREV: Bu aracin yaptigi ISI, Jarvis'in kendi mimarisine uyan TEK BIR YENI
Python dosyasi olarak yeniden yaz. Kurallar:
- SADECE tam dosya icerigini don - aciklama, markdown fence, yorum YOK.
- Dosyanin TEK bir genel fonksiyonu olmali: `def run(parameters: dict) -> str:`
  - parameters bir sozluk olacak, donus degeri kullaniciya okunacak bir metin.
- Kaynak kodu OLDUGU GIBI KOPYALAMA - ne yaptigini anla, Jarvis'in kod
  stiline (basit, hata-toleransli, disariya sadece dogal dilde metin donen
  fonksiyonlar) uygun, KENDI YENI implementasyonunu yaz.
- Disaridan bir sey calistirmiyorsa (ör. sadece bir hesaplama/format
  kutuphanesiyse), sadece o mantigi kullan; bir CLI/GUI araciysa, temel
  islevini `run()` icinde tekrar uygula.
- Ekstra bagimlilik gerektiriyorsa, sadece Python'un standart kutuphanesini
  kullan (yeni pip paketleri EKLEME - kullanicinin ortaminda olmayabilir).
- Sonuc GECERLI Python OLMALI ve import edilebilmeli.

Aracin adi: {name}
Aracin ne yaptigi (on-degerlendirme): {description}

KAYNAK KOD OZETI:
{source}

YENI actions/discovered_{slug}.py ICERIGI:"""


def _read_requirements_names() -> set[str]:
    """requirements.txt'deki paket adlarini (versiyon/extra/ortam-isaretcisi
    kisimlari kirpilmis, kucuk harfe cevrilmis, alt-cizgi/tire farki
    normallestirilmis) bir kume olarak dondurur. Dosya yoksa/okunamazsa BOS
    kume doner - cagiran taraf bunu 'bilinmiyor' olarak yorumlamali, asla
    hata firlatmamali (bu sadece bir DOGRULAMA yardimcisidir, requirements.txt
    KESINLIKLE bu dosya tarafindan degistirilmez)."""
    req_path = BASE_DIR / "requirements.txt"
    names: set[str] = set()
    try:
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.split(";")[0].strip()  # sys_platform=="win32" gibi isaretciler
            name = re.split(r"[<>=\[\s]", line)[0].strip()
            if name:
                names.add(name.lower().replace("_", "-"))
    except Exception:
        pass
    return names


def _has_top_level_run(source: str) -> bool:
    """Modulun ust seviyede `def run(...)` tanimlayip tanimlamadigini kontrol
    eder - SADECE bu tur modullerde (discovered_*) gercek bir 'bos parametreyle
    cagirmayi dene' testi (asagida C) anlamlidir; tools_kopru.py gibi baska
    bir yapidaki dosyalar icin bu adim atlanir."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body)


def _verify_module(path: Path, mod_name: str) -> tuple[bool, str]:
    """self_improve.py'nin _verify() ile AYNI standart olan (A) sozdizimi ve
    (B) gercek import kontrolune ek olarak, discovered_jc.py'de YAKALANAMAYAN
    bir hatanin (fonksiyon govdesindeki GECIKMELI/ic ice import - ör. `def
    run(): import jc`) bir DAHA gozden kacmamasi icin (D) bagimlilik taramasi,
    (E) requirements.txt karsilastirmasi ve (C) gercek bir bos-parametre
    cagri testi eklendi. Hepsi ayri bir Python surecinde calisir (bu surecin
    kendi import cache'ini kirletmemek icin).

    ONEMLI AYRIM: 'ModuleNotFoundError / No module named' (eksik bagimlilik)
    HER ZAMAN sert bir basarisizliktir (FAILED_DEPENDENCY) - kod calismaz.
    Ama run({}) BASKA bir sebeple hata verirse (ör. fonksiyon gercek
    parametre bekliyor, bos sozlukle KeyError/ValueError firlatiyor) bu bir
    HATA DEGILDIR - bircok gercek arac bos girdiyle mantikli sekilde hata
    verir. Bu durumda YUMUSAK bir uyari notu eklenir ama dogrulama BASARILI
    sayilir - yoksa gercekte calisan araclari yanlislikla reddederiz (false
    positive)."""
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
    except SyntaxError as e:
        return False, f"Söz dizimi hatası (satır {e.lineno}): {e.msg}"
    except Exception as e:
        return False, f"Dosya okunamadı: {type(e).__name__}: {e}"

    # (B) mevcut, degismedi: ust-duzey import calisiyor mu?
    proc = subprocess.run(
        [sys.executable, "-c", f"import actions.{mod_name}"],
        capture_output=True, text=True, timeout=30, cwd=str(BASE_DIR),
    )
    if proc.returncode != 0:
        return False, f"Import hatası: {proc.stderr.strip()[-600:]}"

    # (D) + (E): dosyanin TAMAMINDA (fonksiyon govdeleri DAHIL - ast.walk
    # ic ice/gecikmeli importlari da yakalar) kullanilan 3. parti paketleri
    # tara, ortamda kurulu olmayanlari requirements.txt ile karsilastir.
    try:
        from jarvis.actions.capability_registry import guess_missing_deps
        missing_deps = guess_missing_deps(path)
    except Exception as e:
        missing_deps = []
        print(f"[Entegrasyon] ⚠️ Bağımlılık taraması atlandı (capability_registry hatası): {e}")

    if missing_deps:
        declared = _read_requirements_names()
        truly_missing = [d for d in missing_deps if d.lower().replace("_", "-") not in declared]
        if truly_missing:
            return False, (
                f"FAILED_DEPENDENCY: kod şu paketleri kullanıyor ama bunlar ne "
                f"ortamda kurulu ne de requirements.txt'de: {', '.join(truly_missing)}. "
                f"Talimat 'sadece Python standart kütüphanesini kullan, yeni pip "
                f"paketleri EKLEME' idi — bu ihlal edilmiş görünüyor."
            )

    # (C) gercek, izole bir 'bos parametreyle cagirmayi dene' testi - SADECE
    # modul ust seviyede bir `run()` tanimliyorsa (discovered_* modulleri).
    warning_note = ""
    if _has_top_level_run(source):
        test_script = (
            f"import sys\n"
            f"from actions.{mod_name} import run\n"
            f"try:\n"
            f"    run({{}})\n"
            f"    print('RUN_OK')\n"
            f"except Exception as e:\n"
            f"    print('RUN_EXC:' + type(e).__name__ + ':' + str(e)[:300])\n"
            f"    sys.exit(2)\n"
        )
        try:
            run_proc = subprocess.run(
                [sys.executable, "-c", test_script],
                capture_output=True, text=True, timeout=15, cwd=str(BASE_DIR),
            )
        except subprocess.TimeoutExpired:
            warning_note = " (uyarı: run({}) çağrısı zaman aşımına uğradı - kritik değil, gerçek kullanımda ağ/IO bekliyor olabilir)"
        else:
            out = (run_proc.stdout or "").strip()
            if run_proc.returncode == 2 and out.startswith("RUN_EXC:"):
                exc_info = out[len("RUN_EXC:"):]
                exc_type = exc_info.split(":", 1)[0]
                if exc_type in ("ModuleNotFoundError", "ImportError") or "No module named" in exc_info:
                    return False, f"FAILED_DEPENDENCY: run({{}}) çağrısı sırasında eksik modül: {exc_info[:300]}"
                # BASKA bir istisna - yumusak uyari, dogrulama basarili sayilir.
                warning_note = f" (uyarı: run({{}}) boş parametreyle {exc_info[:200]} verdi - muhtemelen gerçek parametre gerekiyor, kritik değil)"
            elif run_proc.returncode not in (0, 2):
                # beklenmeyen bir cikis kodu (ör. segfault benzeri) - sert
                # basarisizlik degil ama bilgilendirici bir uyari olarak isaretle.
                warning_note = f" (uyarı: run({{}}) testi beklenmeyen çıkış kodu {run_proc.returncode} verdi)"

    return True, ("ok" + warning_note if warning_note else "ok")


def _patch_tools_kopru(mod_name: str, tool_name: str, description: str) -> tuple[bool, str, str]:
    """tools_kopru.py'ye YENI aracin cagri koprusunu ekler. Basarisiz olursa
    orijinal icerigi (fonksiyonun aldigi original_content) hicbir sey
    degismeden birakir. Donus: (basarili_mi, yeni_icerik_veya_hata, eski_icerik)."""
    original = TOOLS_KOPRU_PATH.read_text(encoding="utf-8")

    if f'"{tool_name}"' in original:
        return False, f"'{tool_name}' zaten tools_kopru.py'de kayıtlı.", original

    wrapper_fn = f"_call_{mod_name}"
    new_call_fn = (
        f"\n\ndef {wrapper_fn}(parameters: dict) -> str:\n"
        f"    from actions.{mod_name} import run\n"
        f"    return run(parameters) or \"Done.\"\n"
    )

    # 1) Yeni cagri fonksiyonunu, ALLOWED_TOOLS tanimindan hemen once ekle.
    marker = "\n\n# tool_adi -> cagiran fonksiyon."
    if marker not in original:
        return False, "tools_kopru.py beklenen yapıda değil (ALLOWED_TOOLS işaretçisi bulunamadı).", original
    updated = original.replace(marker, new_call_fn + marker, 1)

    # 2) ALLOWED_TOOLS sozlugune yeni satiri ekle.
    allowed_marker = "ALLOWED_TOOLS: dict[str, Any] = {"
    if allowed_marker not in updated:
        return False, "ALLOWED_TOOLS sözlüğü bulunamadı.", original
    updated = updated.replace(
        allowed_marker,
        allowed_marker + f'\n    "{tool_name}": {wrapper_fn},',
        1,
    )

    # 3) TOOL_DESCRIPTIONS sozlugune yeni satiri ekle.
    desc_marker = "TOOL_DESCRIPTIONS: dict[str, str] = {"
    if desc_marker not in updated:
        return False, "TOOL_DESCRIPTIONS sözlüğü bulunamadı.", original
    safe_desc = description.replace('"', "'").replace("\n", " ")[:200]
    updated = updated.replace(
        desc_marker,
        desc_marker + f'\n    "{tool_name}": "{safe_desc} (otomatik entegre edildi)",',
        1,
    )

    return True, updated, original


def integrate_discovered_tool(item: dict) -> str:
    """discovery.py'nin 'tool' dedigi bir seyi, KULLANICIYA SORMADAN
    Jarvis'in koduna entegre etmeye calisir. Basarisiz olursa hicbir kalici
    degisiklik birakmaz (yeni dosya silinir, tools_kopru.py'nin orijinal
    hali korunur) ve durumu acikca loglar/kullaniciya bildirir."""
    source_name = item.get("source_name", "bilinmeyen")
    description = item.get("description", "")
    quarantine_path = Path(item.get("quarantine_path", ""))

    if not quarantine_path.is_dir():
        msg = f"'{source_name}' için karantina klasörü bulunamadı, entegrasyon iptal edildi."
        _log({"source_name": source_name, "status": "failed", "reason": msg})
        return msg

    slug = _slugify(source_name)
    mod_name = f"discovered_{slug}"
    target = BASE_DIR / "actions" / f"{mod_name}.py"
    if target.exists():
        msg = f"'{mod_name}' zaten mevcut, tekrar entegre edilmedi."
        _log({"source_name": source_name, "status": "skipped", "reason": msg})
        return msg

    try:
        from jarvis.backup_tool import JarvisBackupTool
        backup_path = JarvisBackupTool(BASE_DIR).create_backup()
    except Exception as e:
        msg = f"Yedek alınamadı, güvenlik için entegrasyon iptal edildi: {e}"
        _log({"source_name": source_name, "status": "failed", "reason": msg})
        return msg

    source_summary = _gather_source(quarantine_path)
    prompt = _INTEGRATION_PROMPT.format(
        name=source_name, description=description, source=source_summary, slug=slug,
    )

    from google import genai
    from jarvis.actions.resilience import CircuitBreaker, call_with_resilience

    breaker = CircuitBreaker(name="gemini-entegrasyon", failure_threshold=3, cooldown_seconds=60.0)
    client = genai.Client(api_key=_get_api_key())

    last_error = None
    module_verify_note = "ok"
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        error_note = f"\n\nÖnceki deneme bu hatayla başarısız oldu, düzelt:\n{last_error}" if last_error else ""

        def _call(error_note=error_note):
            return client.models.generate_content(model=MODEL_NAME, contents=prompt + error_note)

        try:
            from jarvis.actions.local_llm import generate_with_fallback
            raw_text = generate_with_fallback(
                lambda: call_with_resilience(_call, breaker=breaker, max_attempts=2, base_delay=2.0, max_delay=15.0),
                prompt_for_ollama=prompt + error_note,
                source="entegrasyon",
            )
            new_content = _clean_code(raw_text)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue

        if not new_content.strip():
            last_error = "Model boş içerik döndürdü."
            continue

        target.write_text(new_content, encoding="utf-8")
        ok, detail = _verify_module(target, mod_name)
        if ok:
            module_verify_note = detail  # "ok" ya da "ok (uyarı: ...)" - asagida kullanilir
            break
        last_error = detail
        target.unlink(missing_ok=True)
    else:
        msg = (f"'{source_name}' entegre edilemedi — {MAX_ATTEMPTS} deneme de doğrulamadan "
                f"geçemedi. Son hata: {last_error}. Hiçbir kalıcı değişiklik yapılmadı.")
        _log({"source_name": source_name, "status": "failed", "reason": last_error,
              "backup": str(backup_path)})
        return msg

    tool_name = mod_name
    patched_ok, patched_content_or_error, original_kopru = _patch_tools_kopru(
        mod_name, tool_name, description,
    )
    if not patched_ok:
        target.unlink(missing_ok=True)
        msg = f"'{source_name}' modülü doğrulandı ama araç köprüsüne kaydedilemedi: {patched_content_or_error}"
        _log({"source_name": source_name, "status": "failed", "reason": patched_content_or_error,
              "backup": str(backup_path)})
        return msg

    TOOLS_KOPRU_PATH.write_text(patched_content_or_error, encoding="utf-8")
    kopru_ok, kopru_detail = _verify_module(TOOLS_KOPRU_PATH, "tools_kopru")
    # tools_kopru.py'nin kendi modul adiyla import kontrolu icin kucuk bir
    # duzeltme: yukaridaki _verify_module "actions.<isim>" import ediyor,
    # tools_kopru icin de bu dogru (actions.tools_kopru).
    if not kopru_ok:
        TOOLS_KOPRU_PATH.write_text(original_kopru, encoding="utf-8")
        target.unlink(missing_ok=True)
        msg = (f"'{source_name}' modülü doğrulandı ama araç köprüsüne eklenince bozuldu, "
                f"her iki değişiklik de geri alındı: {kopru_detail}")
        _log({"source_name": source_name, "status": "rolled_back", "reason": kopru_detail,
              "backup": str(backup_path)})
        return msg

    try:
        from jarvis.actions.discovery import register_discovered_tool
        register_discovered_tool({
            "name": source_name, "description": description,
            "quarantine_path": str(quarantine_path),
        })
    except Exception:
        pass  # kayit basarisiz olsa bile gercek entegrasyon zaten tamamlandi

    verify_suffix = f" [doğrulama notu: {module_verify_note}]" if module_verify_note != "ok" else ""
    msg = (f"'{source_name}' otomatik olarak kendime entegre ettim — yeni araç: '{tool_name}'. "
            f"{description} Tam proje yedeği: {backup_path.name}.{verify_suffix}")
    _log({"source_name": source_name, "status": "integrated", "tool_name": tool_name,
          "backup": str(backup_path), "verify_note": module_verify_note})
    return msg
