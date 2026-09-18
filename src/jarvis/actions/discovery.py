"""
discovery.py — Jarvis'in Downloads klasöründe kendiliğinden beliren yeni
zip/klasörleri fark edip, İZOLE bir karantina klasöründe inceleyip, Gemini'den
"araç mı / çöp mü / tehlikeli mi" değerlendirmesi alan modül.

TASARIM SINIRI (kullanıcıyla birlikte, önceki bir öneriyi reddederek
kararlaştırıldı — bkz. tools_kopru.py'nin başındaki not):
Bu modül KEŞFİ (izleme + karantina + analiz) otomatik yapar, ama ASLA
bulduğu kodu otomatik olarak Jarvis'in kendi koduna ENTEGRE ETMEZ. Sebep:
bir LLM'in dosya listesi + README okuyup "zararsız görünüyor" demesi bir
güvenlik denetimi DEĞİLDİR — self_improve.py'nin de açıkça belirttiği gibi,
söz dizimi/import kontrolü sadece "açıkça bozuk mu" sorusuna cevap verir,
kötü niyetli ama sözdizimi geçerli bir kodu YAKALAYAMAZ. İnternetten bulunan
rastgele kodu, mikrofon/kamera/mesaj gönderme/bilgisayarı kapatma yetkisi
olan ÇALIŞAN bir sürece sadece bir LLM'in onayıyla otomatik enjekte etmek
tedarik zinciri saldırılarına (supply chain attack) açık kapı bırakır.

Bu yüzden akış şudur:
  1. scan_downloads_once() her agent_loop turunda çağrılır, Downloads'ta
     DAHA ÖNCE GÖRÜLMEMİŞ bir .zip dosyası ya da klasör var mı bakar.
  2. Yeni bir şey bulunursa: KARANTİNA klasörüne (Jarvis'in kendi proje
     klasörünün TAMAMEN dışında, memory/quarantine/ altında) çıkarılır/
     kopyalanır — orijinal dosyaya ve Jarvis'in kendi koduna ASLA dokunulmaz.
  3. Karantinadaki içerik (dosya listesi + varsa README) Gemini'ye verilir,
     yapılandırılmış bir JSON değerlendirme istenir: verdict (tool/junk/
     dangerous), description, suggested_capability.
  4. Sonuç "tool" ise, agent_loop'un ZATEN VAR olan ve test edilmiş
     onay mekanizmasına (awaiting_approval + bildirim) bir görev olarak
     eklenir — kullanıcı "onaylıyorum" demeden HİÇBİR ŞEY kalıcı olarak
     kaydedilmez/entegre edilmez. Onaylansa bile bu SADECE bir kayıt
     (memory/discovered_tools.json) oluşturur — Jarvis'in gerçek koduna
     (main.py, actions/) otomatik yazma YAPMAZ. Gerçek entegrasyon, ayrı ve
     bilinçli bir adım olarak self_improve/dev_agent ile kullanıcının kendi
     isteğiyle yapılır.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from jarvis.paths import memory_dir

MAX_FILES_LISTED   = 200      # Gemini'ye gonderilen dosya listesi ust siniri
MAX_README_CHARS   = 4000     # README'den okunacak maksimum karakter
MAX_ITEM_SIZE_BYTES = 200 * 1024 * 1024   # 200MB - daha buyuk zip/klasorler atlanir (guvenlik + maliyet)

# --- Yetenek-Boslugu (Gap) Analizi sabitleri --------------------------------
# NOT: Bunlar _analyze()'in "tool/junk/dangerous" mantigina hicbir sekilde
# dokunmaz - _analyze() AYNEN eskisi gibi calismaya devam eder. Bu sabitler
# SADECE _analyze() zaten "tool" dedikten SONRA calisan, IKINCI ve AYRI bir
# soru icin: "bu tool Jarvis'e GERCEKTEN bir sey katiyor mu?"
_GAP_DECISIONS = {
    "USEFUL_NEW_CAPABILITY",     # Jarvis'te hic olmayan, gercek bir eksigi kapatiyor
    "USEFUL_PARTIAL_CAPABILITY", # kismen ortusen ama gercek katkisi olan bir yetenek
    "REDUNDANT",                 # Jarvis'te zaten ayni isi yapan bir arac var
    "LOW_VALUE",                 # calisir ama somut/gercekci bir kullanim senaryosu yok
    "NOT_COMPATIBLE",            # Jarvis'in mimarisine/calisma seklime uymuyor
    "SECURITY_RISK",             # _analyze() "tool" dese bile ek incelemede risk gorunuyor
    "NEEDS_REVIEW",              # model emin degil - insan gozden gecirmeli
    "UNKNOWN",                   # analiz basarisiz oldu / gecersiz cevap geldi (GUVENLI varsayilan)
}
_GAP_REQUIRED_FIELDS = (
    "decision", "reason", "missing_capability", "overlap",
    "integration_complexity", "security_risk", "concrete_use_case",
)

# --- Kullanilabilirlik (Usability) Analizi sabitleri ------------------------
# UCUNCU ve AYRI bir soru: _gap_analyze() "Jarvis'e yeni bir sey katiyor mu?"
# dedikten SONRA calisan bu katman "Jarvis bunu GERCEKTEN cagirabilir mi?"
# sorusunu sorar. Bir yetenek teknik olarak yeni olabilir ama Jarvis'in
# mevcut arac zincirinde ona ulasan gercek bir yol yoksa (ör. jc, ham bir
# shell komutunun CIKTISINI JSON'a cevirir - ama Jarvis'in hicbir araci
# boyle bir ham komut ciktisi URETMIYOR), sirf "yeni" oldugu icin
# entegre edilmemeli.
_USABILITY_DECISIONS = {
    "CALLABLE",                 # dogrudan, mevcut bir cagri noktasindan cagrilabilir
    "CALLABLE_WITH_ADAPTER",    # kucuk bir baglayici/adapter ile cagrilabilir
    "NEEDS_INTEGRATION_POINT",  # yeni bir entegrasyon noktasi gerekiyor (mimari degisiklik)
    "NOT_CALLABLE",             # Jarvis'in mevcut mimarisinde bunu cagiracak hicbir yol yok
    "UNKNOWN",                  # analiz basarisiz oldu / gecersiz cevap (GUVENLI varsayilan)
}
_USABILITY_REQUIRED_FIELDS = (
    "decision", "reason", "call_path", "input_source", "output_consumer",
    "integration_point", "concrete_use_case", "complexity", "risk",
)
MAX_USABILITY_SOURCE_CHARS = 6000  # Gemini'ye gonderilecek aday KOD ozeti ust siniri


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
SEEN_PATH        = memory_dir() / "discovery_seen.json"
REGISTRY_PATH    = memory_dir() / "discovered_tools.json"
QUARANTINE_ROOT  = memory_dir() / "quarantine"
API_KEYS_PATH    = BASE_DIR / "config" / "api_keys.json"
GAP_LOG_PATH     = memory_dir() / "discovery_gap_log.jsonl"


# --- Depolama yardimcilari ----------------------------------------------

def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8", suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def _load_json(path: Path, default):
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Discovery] ⚠️ {path.name} okunamadı: {e}")
    return default


def _load_seen() -> dict:
    return _load_json(SEEN_PATH, {})


def _save_seen(seen: dict) -> None:
    try:
        _atomic_write_json(SEEN_PATH, seen)
    except Exception as e:
        print(f"[Discovery] ⚠️ discovery_seen.json yazılamadı: {e}")


def _load_registry() -> list[dict]:
    data = _load_json(REGISTRY_PATH, [])
    return data if isinstance(data, list) else []


def _save_registry(items: list[dict]) -> None:
    try:
        _atomic_write_json(REGISTRY_PATH, items)
    except Exception as e:
        print(f"[Discovery] ⚠️ discovered_tools.json yazılamadı: {e}")


# --- Downloads'i tara ------------------------------------------------------

def _get_downloads() -> Path:
    from jarvis.actions.file_controller import _get_downloads as _fc_downloads
    return _fc_downloads()


def _item_key(p: Path) -> str:
    """Ayni ismi tasiyan ama icerigi degisen bir dosyayi da yeni sayabilmek
    icin isim + boyut + mtime birlestirilir."""
    try:
        st = p.stat()
        return f"{p.name}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        return p.name


def find_new_downloads() -> list[Path]:
    """Downloads'ta daha once gorulmemis .zip dosyalarini VE klasorleri
    dondurur. Jarvis'in kendi proje klasorlerini (MuratJarvis, FINAL_BUILD
    vb.) ve gizli/sistem ogelerini atlar."""
    downloads = _get_downloads()
    if not downloads.is_dir():
        return []

    seen = _load_seen()
    new_items: list[Path] = []

    try:
        for item in downloads.iterdir():
            if item.name.startswith("."):
                continue
            is_zip = item.is_file() and item.suffix.lower() == ".zip"
            is_dir = item.is_dir()
            if not (is_zip or is_dir):
                continue
            # Jarvis'in kendi projeleriyle ilgili klasorleri asla "kesfedilecek
            # yabanci arac" gibi islemeye kalkma.
            if "jarvis" in item.name.lower():
                continue
            try:
                size = item.stat().st_size if is_zip else sum(
                    f.stat().st_size for f in item.rglob("*") if f.is_file()
                )
            except Exception:
                continue
            if size > MAX_ITEM_SIZE_BYTES:
                continue

            key = _item_key(item)
            if key in seen:
                continue
            new_items.append(item)
    except Exception as e:
        print(f"[Discovery] ⚠️ Downloads taranamadı: {e}")
        return []

    return new_items


def _mark_seen(item: Path) -> None:
    seen = _load_seen()
    seen[_item_key(item)] = {
        "name": item.name,
        "seen_at": datetime.now().isoformat(),
    }
    _save_seen(seen)


# --- Karantina --------------------------------------------------------------

def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """Zip-slip korumali cikarma - bir zip icindeki '../../etc/passwd' gibi
    yollarin karantina disina cikmasini engeller."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            member_path = (dest / member.filename).resolve()
            if not str(member_path).startswith(str(dest.resolve())):
                raise ValueError(f"Güvensiz zip içeriği (zip-slip): {member.filename}")
        zf.extractall(dest)


def _quarantine(item: Path) -> Path:
    """Item'i (zip ya da klasor) Jarvis'in proje klasorunun TAMAMEN disinda,
    kendi izole karantina klasorune tasir (kopyalar - orijinali silmez)."""
    qid = uuid.uuid4().hex[:10]
    dest = QUARANTINE_ROOT / qid
    dest.mkdir(parents=True, exist_ok=True)

    if item.is_file() and item.suffix.lower() == ".zip":
        _safe_extract_zip(item, dest)
    else:
        shutil.copytree(item, dest / item.name, dirs_exist_ok=True)

    return dest


def _cleanup_quarantine(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# --- Gemini analizi -----------------------------------------------------

def _get_api_key() -> str:
    from jarvis.core.secure_config import get_gemini_api_key
    return get_gemini_api_key()


_ANALYSIS_PROMPT = """Asagida, kullanicinin bilgisayarina indirdigi bir
zip/klasorun icerik listesi ve varsa README'si var. Bunun ne oldugunu
degerlendir.

ONEMLI: Bu SADECE bir on-degerlendirme, bir guvenlik garantisi degil - kodu
GERCEKTEN calistirmiyorsun, sadece dosya isimlerine/README'ye bakiyorsun.
Emin olmadigin her durumda "junk" veya "dangerous" de, "tool" demek icin
gercekten NET bir fayda gormelisin.

Dosya listesi ({count} dosya, ilk {max_files} tanesi):
{file_list}

README (varsa, ilk {max_chars} karakter):
{readme}

SADECE gecerli JSON don, markdown/aciklama YOK:
{{
  "verdict": "tool" | "junk" | "dangerous",
  "description": "bu ne yapiyor, 1-2 cumle, Turkce",
  "reasoning": "bu karari neden verdin, kisa"
}}
"""


def _strip_fences(text: str) -> str:
    import re
    text = re.sub(r"```(?:json)?", "", text).strip()
    return text.rstrip("`").strip()


def _analyze(quarantine_path: Path) -> dict:
    files = sorted(str(p.relative_to(quarantine_path)) for p in quarantine_path.rglob("*") if p.is_file())
    file_list = "\n".join(files[:MAX_FILES_LISTED]) or "(dosya yok)"

    readme_text = "(README bulunamadı)"
    for candidate in ("README.md", "README.txt", "readme.md", "README"):
        rp = quarantine_path / candidate
        if rp.is_file():
            try:
                readme_text = rp.read_text(encoding="utf-8", errors="ignore")[:MAX_README_CHARS]
            except Exception:
                pass
            break

    prompt = _ANALYSIS_PROMPT.format(
        count=len(files), max_files=MAX_FILES_LISTED,
        file_list=file_list, max_chars=MAX_README_CHARS, readme=readme_text,
    )

    from google import genai
    from jarvis.actions.resilience import CircuitBreaker, call_with_resilience

    breaker = CircuitBreaker(name="gemini-discovery", failure_threshold=3, cooldown_seconds=60.0)
    client = genai.Client(api_key=_get_api_key())

    def _call():
        return client.models.generate_content(model="gemini-flash-latest", contents=prompt)

    from jarvis.actions.local_llm import generate_with_fallback
    raw_text = generate_with_fallback(
        lambda: call_with_resilience(_call, breaker=breaker, max_attempts=2, base_delay=2.0, max_delay=15.0),
        prompt_for_ollama=prompt,
        source="discovery",
    )
    text = _strip_fences(raw_text.strip())
    result = json.loads(text)
    if not isinstance(result, dict) or "verdict" not in result:
        raise ValueError("Model geçerli bir değerlendirme döndürmedi.")
    return result


# --- Yetenek-Boslugu (Gap) Analizi ------------------------------------------
# _analyze() SADECE "bu gercek/calisan bir yazilim mi?" sorusuna cevap verir.
# Asagidaki _gap_analyze() ise _analyze() "tool" dedikten SONRA calisan,
# TAMAMEN AYRI ikinci bir soru sorar: "Jarvis'in ZATEN VAR olan yeteneklerine
# gore, bu tool GERCEKTEN bir seyi kapatiyor mu, yoksa zaten var olani mi
# tekrarliyor / somut bir faydasi yok mu?" _analyze()'in kendisi hicbir
# sekilde degistirilmedi - bu fonksiyon onun DONUS DEGERINI (verdict dict'i)
# girdiye ek olarak kullanir, davranisini degistirmez.

_GAP_PROMPT = """Asagida, "gercek/calisan bir yazilim" oldugu ONCEDEN
degerlendirilmis bir aday hakkinda bilgi var. Senin gorevin BASKA bir soruya
cevap vermek: bu aday, Jarvis adli bir asistanin ZATEN SAHIP OLDUGU
yeteneklere gore GERCEKTEN yeni/faydali bir sey katiyor mu?

JARVIS'IN SU ANKI GERCEK YETENEKLERI (kod tabanindan otomatik cikarildi,
bu liste GUNCEL ve GERCEK - varsayim yapma, asagidakine gore karar ver):
{capability_summary}

ADAY HAKKINDA ON-DEGERLENDIRME (ayri bir analiz asamasindan geldi):
- Aciklama: {tool_description}
- On-degerlendirme gerekcesi: {tool_reasoning}

ADAYIN DOSYA OZETI:
{file_summary}

ADAYIN BAGIMLILIK BILGISI (varsa requirements.txt/pyproject.toml/setup.py/package.json icerigi):
{dependency_info}

KARAR VERIRKEN UNUTMA:
- "Faydali olabilir" gibi BELIRSIZ/GENEL bir gerekce KABUL EDILMEZ - somut,
  spesifik bir kullanim senaryosu ("kullanici X derse Jarvis Y yapabilir
  hale gelir" gibi) yazmalisin, yoksa LOW_VALUE veya NEEDS_REVIEW sec.
- Yukaridaki yetenek listesinde ZATEN benzer bir sey varsa REDUNDANT sec ve
  hangi mevcut yetenekle ortustugunu 'overlap' alaninda ACIKCA belirt.
- SENIN guvenlik degerlendirmen bir INSAN ONAYININ YERINE GECMEZ - bu
  sadece bilgilendirme amaclidir, nihai entegrasyon HER ZAMAN ayri bir
  onay adimindan gecer. Yine de acik bir risk goruyorsan SECURITY_RISK sec.
- Emin degilsen ASLA tahmin yurutup USEFUL_* secme - NEEDS_REVIEW sec.

SADECE gecerli JSON don, markdown/aciklama YOK, tum alanlar ZORUNLU:
{{
  "decision": "USEFUL_NEW_CAPABILITY" | "USEFUL_PARTIAL_CAPABILITY" | "REDUNDANT" | "LOW_VALUE" | "NOT_COMPATIBLE" | "SECURITY_RISK" | "NEEDS_REVIEW" | "UNKNOWN",
  "reason": "kararin kisa, somut gerekcesi (Turkce)",
  "missing_capability": "bu tool olmadan Jarvis'in yapamadigi TEK bir sey - somut, yoksa bos string",
  "overlap": "REDUNDANT ise hangi mevcut yetenekle ortustugu, degilse bos string",
  "integration_complexity": "low" | "medium" | "high",
  "security_risk": "low" | "medium" | "high",
  "concrete_use_case": "kullanicinin soyleyebilecegi somut bir cumle ornegi, yoksa bos string"
}}
"""


def _safe_fallback(reason: str) -> dict:
    """Gap-analizi HERHANGI bir sebeple basarisiz olursa (ag hatasi, gecersiz
    JSON, eksik alan, gecersiz decision degeri) donulen GUVENLI varsayilan.
    KRITIK: asla 'faydali' bir karara DUSMEZ - basarisizlikta her zaman
    UNKNOWN doner, boylece cagiran taraf (scan_downloads_once /
    github_arac_bul_ve_degerlendir) bunu 'kullanisli degil' gibi ele alip
    guvenli tarafta kalir."""
    return {
        "decision": "UNKNOWN",
        "reason": reason,
        "missing_capability": "",
        "overlap": "",
        "integration_complexity": "unknown",
        "security_risk": "unknown",
        "concrete_use_case": "",
    }


def _gather_dependency_hint(quarantine_path: Path) -> str:
    """Adayin karantina klasorunde bagimlilik bildiren dosyalar (varsa) - kisa
    ozet olarak Gemini'ye verilir, boylece 'bu paket zaten kurulu mu/yeni bir
    pip paketi mi gerektiriyor' sorusuna biraz daha bilgiyle karar verebilir.
    Bulunamazsa acikca 'bulunamadi' der, sessizce bos birakmaz."""
    candidates = ("requirements.txt", "pyproject.toml", "setup.py", "package.json")
    parts = []
    for name in candidates:
        for rp in quarantine_path.rglob(name):
            try:
                content = rp.read_text(encoding="utf-8", errors="ignore")[:1500]
            except Exception:
                continue
            parts.append(f"[{rp.relative_to(quarantine_path)}]\n{content}")
    if not parts:
        return "(bagimlilik dosyasi bulunamadi)"
    return "\n\n".join(parts)[:3000]


def _gap_analyze(quarantine_path: Path, tool_verdict: dict) -> dict:
    """_analyze() zaten 'tool' dedikten SONRA cagirilir. Jarvis'in GERCEK
    yetenek listesini (capability_registry) + adayin dosya/bagimlilik
    bilgisini Gemini'ye verip 'bu gercekten faydali mi?' sorusunu sorar.
    HERHANGI bir hata/gecersiz cevapta _safe_fallback() (UNKNOWN) doner -
    ASLA hata durumunda 'faydali' varsaymaz."""
    try:
        from jarvis.actions.capability_registry import get_capability_summary
        capability_summary = get_capability_summary()
    except Exception as e:
        # Kendi yetenek listemizi bile okuyamiyorsak, karsilastirma yapamayiz -
        # guvenli tarafta kal, tahmin yurutme.
        return _safe_fallback(f"capability_registry okunamadi: {e}")

    try:
        files = sorted(str(p.relative_to(quarantine_path)) for p in quarantine_path.rglob("*") if p.is_file())
        file_summary = "\n".join(files[:MAX_FILES_LISTED]) or "(dosya yok)"
        dependency_info = _gather_dependency_hint(quarantine_path)
    except Exception as e:
        return _safe_fallback(f"aday dosyalari okunamadi: {e}")

    prompt = _GAP_PROMPT.format(
        capability_summary=capability_summary,
        tool_description=tool_verdict.get("description", ""),
        tool_reasoning=tool_verdict.get("reasoning", ""),
        file_summary=file_summary,
        dependency_info=dependency_info,
    )

    try:
        from google import genai
        from jarvis.actions.resilience import CircuitBreaker, call_with_resilience
        from jarvis.actions.local_llm import generate_with_fallback

        breaker = CircuitBreaker(name="gemini-discovery-gap", failure_threshold=3, cooldown_seconds=60.0)
        client = genai.Client(api_key=_get_api_key())

        def _call():
            return client.models.generate_content(model="gemini-flash-latest", contents=prompt)

        raw_text = generate_with_fallback(
            lambda: call_with_resilience(_call, breaker=breaker, max_attempts=2, base_delay=2.0, max_delay=15.0),
            prompt_for_ollama=prompt,
            source="discovery_gap",
        )
        text = _strip_fences(raw_text.strip())
        result = json.loads(text)
    except Exception as e:
        return _safe_fallback(f"gap-analizi cagrisi basarisiz: {e}")

    if not isinstance(result, dict):
        return _safe_fallback("model gecerli bir JSON nesnesi dondurmedi")
    missing_fields = [f for f in _GAP_REQUIRED_FIELDS if f not in result]
    if missing_fields:
        return _safe_fallback(f"eksik alan(lar): {', '.join(missing_fields)}")
    if result.get("decision") not in _GAP_DECISIONS:
        return _safe_fallback(f"gecersiz decision degeri: {result.get('decision')!r}")

    return result


def _log_gap_result(
    source_name: str, tool_verdict: dict, gap: dict,
    usability: dict | None = None, combined_decision: str = "",
) -> None:
    """Her gap-analizi sonucunu (karar ne olursa olsun - useful/redundant/
    unknown farketmez) memory/discovery_gap_log.jsonl dosyasina EKLER
    (append). Loglama basarisiz olursa sessizce yutulur - Jarvis'in ana
    akisini ASLA bozmaz.

    YENI (kullanilabilirlik analizi): usability parametresi verilirse
    (SADECE gap_decision zaten USEFUL_* oldugunda hesaplanir - REDUNDANT/
    LOW_VALUE/vb icin usability hic calistirilmaz, gereksiz API cagrisi
    yapilmaz), ek alanlar eklenir. ONEMLI: mevcut alanlardan HICBIRI
    kaldirilmadi/yeniden adlandirilmadi - 'concrete_use_case' zaten gap
    analizine ait bir alan oldugu icin, usability'nin kendi 'concrete_use_case'
    alani cakismasin diye 'usability_concrete_use_case' olarak eklendi."""
    try:
        GAP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "source_name": source_name,
            "tool_verdict": tool_verdict.get("verdict", ""),
            "tool_description": tool_verdict.get("description", ""),
            "gap_decision": gap.get("decision", ""),
            "gap_reason": gap.get("reason", ""),
            "missing_capability": gap.get("missing_capability", ""),
            "overlap": gap.get("overlap", ""),
            "integration_complexity": gap.get("integration_complexity", ""),
            "security_risk": gap.get("security_risk", ""),
            "concrete_use_case": gap.get("concrete_use_case", ""),
            "usability_decision": (usability or {}).get("decision", ""),
            "usability_reason": (usability or {}).get("reason", ""),
            "call_path": (usability or {}).get("call_path", ""),
            "input_source": (usability or {}).get("input_source", ""),
            "output_consumer": (usability or {}).get("output_consumer", ""),
            "integration_point": (usability or {}).get("integration_point", ""),
            "usability_concrete_use_case": (usability or {}).get("concrete_use_case", ""),
            "usability_complexity": (usability or {}).get("complexity", ""),
            "usability_risk": (usability or {}).get("risk", ""),
            "combined_decision": combined_decision,
        }
        with open(GAP_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Discovery] ⚠️ gap-analiz logu yazılamadı: {e}")


# --- Kullanilabilirlik (Usability) Analizi ----------------------------------

_USABILITY_PROMPT = """Asagida, Jarvis adli bir sesli asistan icin "gercek bir
yazilim" oldugu VE "yeni/faydali bir yetenek katabilecegi" ONCEDEN tespit
edilmis bir aday hakkinda bilgi var. Senin gorevin UCUNCU ve FARKLI bir soruya
cevap vermek: Jarvis bu yetenegi GERCEKTEN, kendi mevcut mimarisiyle
CAGIRABILIR mi?

ONEMLI AYRIM: Bir yetenek teknik olarak yeni/faydali olabilir ama Jarvis'in
mevcut arac zincirinde ona ulasan GERCEK bir yol yoksa (ör. bir arac ham bir
shell komutunun ciktisini isliyor olabilir, ama Jarvis'in hicbir araci boyle
bir ham komut ciktisi URETMIYORSA), bu yetenek sirf "yeni" oldugu icin
entegre edilmemeli.

JARVIS'IN SU ANKI GERCEK YETENEKLERI (kod tabanindan otomatik cikarildi):
{capability_summary}

ADAY HAKKINDA ON-DEGERLENDIRME:
- Aciklama: {tool_description}
- Yetenek-boslugu analizi karari: {gap_decision} — {gap_reason}
- Iddia edilen somut kullanim senaryosu: {gap_concrete_use_case}

ADAYIN GERCEK KAYNAK KODU (ozet, fonksiyon imzalari/CLI arayuzu icin):
{code_summary}

ASAGIDAKI SORULARI KENDINE SORARAK KARAR VER:
1. Aday yetenegin Jarvis'in mevcut sisteminde gercek bir cagri noktasi var mi?
2. Mevcut bir arac bu adayin ihtiyac duydugu girdiyi (input) uretebiliyor mu?
3. Mevcut bir arac bu adayin ciktisini (output) kullanabilir mi?
4. Aday dogrudan mevcut yurutucu (agent_loop/tools_kopru) tarafindan cagrilabilir mi?
5. Aday icin yeni bir entegrasyon noktasi olusturmak gerekiyor mu?
6. Geregiyorsa bu kucuk bir baglanti mi, yoksa mimari degisiklik mi?
7. Adayin GERCEK/somut bir kullanim senaryosu var mi (varsayim degil)?
8. Bu kullanim senaryosu mevcut Jarvis gorevleriyle iliskilendirilebilir mi?

Emin degilsen ASLA CALLABLE varsayma - NOT_CALLABLE veya (belirsizlik gercekten
cozulemezse) UNKNOWN sec.

SADECE gecerli JSON don, markdown/aciklama YOK, tum alanlar ZORUNLU:
{{
  "decision": "CALLABLE" | "CALLABLE_WITH_ADAPTER" | "NEEDS_INTEGRATION_POINT" | "NOT_CALLABLE" | "UNKNOWN",
  "reason": "kararin kisa, somut gerekcesi (Turkce)",
  "call_path": "hangi mevcut arac/mekanizma bunu cagirabilir, yoksa bos string",
  "input_source": "bu adayin girdisini hangi mevcut arac uretebilir, yoksa bos string",
  "output_consumer": "bu adayin ciktisini hangi mevcut arac kullanabilir, yoksa bos string",
  "integration_point": "gerekiyorsa nerede/nasil bir entegrasyon noktasi gerekir, yoksa bos string",
  "concrete_use_case": "kullanicinin soyleyebilecegi somut bir cumle ornegi, yoksa bos string",
  "complexity": "low" | "medium" | "high",
  "risk": "low" | "medium" | "high"
}}
"""


def _gather_candidate_code_summary(quarantine_path: Path) -> str:
    """entegrasyon.py'nin _gather_source()'una BENZER ama BAGIMSIZ bir kucuk
    yardimci - BILEREK bagimsiz tutuldu cunku entegrasyon.py zaten
    actions.discovery'yi import ediyor (register_discovered_tool icin);
    tersi bir import (discovery.py -> entegrasyon.py) DONGUSEL IMPORT
    yaratirdi. Sadece .py dosyalarina odaklanir (fonksiyon imzalari/CLI
    arayuzu, kullanilabilirlik sorusu icin en bilgilendirici kisim)."""
    parts = []
    total = 0
    for f in sorted(quarantine_path.rglob("*.py")):
        if total >= MAX_USABILITY_SOURCE_CHARS:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        chunk = f"--- {f.relative_to(quarantine_path)} ---\n{text}\n"
        parts.append(chunk[: MAX_USABILITY_SOURCE_CHARS - total])
        total += len(chunk)
    return "\n".join(parts) or "(okunabilir .py dosyası bulunamadı)"


def _safe_usability_fallback(reason: str) -> dict:
    """_safe_fallback() ile AYNI mantik, kullanilabilirlik analizi icin: HIC
    bir hata durumunda CALLABLE varsayilmaz, her zaman UNKNOWN doner."""
    return {
        "decision": "UNKNOWN",
        "reason": reason,
        "call_path": "",
        "input_source": "",
        "output_consumer": "",
        "integration_point": "",
        "concrete_use_case": "",
        "complexity": "unknown",
        "risk": "unknown",
    }


def _capability_usability_analyze(quarantine_path: Path, tool_verdict: dict, gap: dict) -> dict:
    """_gap_analyze() zaten USEFUL_* dedikten SONRA cagirilir (bkz. cagiran
    kod - REDUNDANT/LOW_VALUE/vb icin bu fonksiyon hic calistirilmaz, gereksiz
    API cagrisi onlenir). Jarvis'in GERCEK yetenek listesi + adayin GERCEK
    kaynak kodu ile 'bu gercekten cagrilabilir mi?' sorusunu sorar. HERHANGI
    bir hata/gecersiz cevapta _safe_usability_fallback() (UNKNOWN) doner -
    ASLA hata durumunda CALLABLE varsaymaz."""
    try:
        from jarvis.actions.capability_registry import get_capability_summary
        capability_summary = get_capability_summary()
    except Exception as e:
        return _safe_usability_fallback(f"capability_registry okunamadı: {e}")

    try:
        code_summary = _gather_candidate_code_summary(quarantine_path)
    except Exception as e:
        return _safe_usability_fallback(f"aday kaynak kodu okunamadı: {e}")

    prompt = _USABILITY_PROMPT.format(
        capability_summary=capability_summary,
        tool_description=tool_verdict.get("description", ""),
        gap_decision=gap.get("decision", ""),
        gap_reason=gap.get("reason", ""),
        gap_concrete_use_case=gap.get("concrete_use_case", ""),
        code_summary=code_summary,
    )

    try:
        from google import genai
        from jarvis.actions.resilience import CircuitBreaker, call_with_resilience
        from jarvis.actions.local_llm import generate_with_fallback

        breaker = CircuitBreaker(name="gemini-discovery-usability", failure_threshold=3, cooldown_seconds=60.0)
        client = genai.Client(api_key=_get_api_key())

        def _call():
            return client.models.generate_content(model="gemini-flash-latest", contents=prompt)

        raw_text = generate_with_fallback(
            lambda: call_with_resilience(_call, breaker=breaker, max_attempts=2, base_delay=2.0, max_delay=15.0),
            prompt_for_ollama=prompt,
            source="discovery_usability",
        )
        text = _strip_fences(raw_text.strip())
        result = json.loads(text)
    except Exception as e:
        return _safe_usability_fallback(f"kullanılabilirlik analizi çağrısı başarısız: {e}")

    if not isinstance(result, dict):
        return _safe_usability_fallback("model geçerli bir JSON nesnesi döndürmedi")
    missing_fields = [f for f in _USABILITY_REQUIRED_FIELDS if f not in result]
    if missing_fields:
        return _safe_usability_fallback(f"eksik alan(lar): {', '.join(missing_fields)}")
    if result.get("decision") not in _USABILITY_DECISIONS:
        return _safe_usability_fallback(f"geçersiz decision değeri: {result.get('decision')!r}")

    return result


def combine_gap_and_usability(gap_decision: str, usability_decision: str) -> str:
    """Iki AYRI karari TEK bir birlesik sonuca indirger. Bu fonksiyon PUBLIC
    (alt cizgisiz) - hem scan_downloads_once() hem github_arama.py tarafindan
    kullanilir, boylece birlestirme mantigi TEK bir yerde tutulur.

    Donus degerleri:
      - 'PASS_AUTO'   : hem faydali HEM dogrudan cagrilabilir - Downloads
                        borusunun ONAYSIZ akisinda bile guvenle ilerleyebilir
                        (bu boru hicbir onay adimi icermedigi icin sadece
                        TAM CALLABLE olanlar buraya girer).
      - 'PASS_REVIEW' : faydali ama adapter/yeni entegrasyon noktasi
                        gerekiyor - SADECE zaten insan onayi olan borularda
                        (GitHub -> entegrasyon_uygula) ilerlemeli; boylece
                        insan, onaylarken bu ek karmasikligi gorebilir.
      - 'BLOCK'       : gap karari zaten reddediyor (REDUNDANT/LOW_VALUE/
                        NOT_COMPATIBLE/SECURITY_RISK/NEEDS_REVIEW/UNKNOWN)
                        VEYA yetenege ulasmanin hic yolu yok (NOT_CALLABLE)
                        VEYA kullanilabilirlik analizi basarisiz oldu
                        (UNKNOWN) - hicbir boruda ilerlemez.
    """
    if gap_decision not in ("USEFUL_NEW_CAPABILITY", "USEFUL_PARTIAL_CAPABILITY"):
        return "BLOCK"
    if usability_decision == "CALLABLE":
        return "PASS_AUTO"
    if usability_decision in ("CALLABLE_WITH_ADAPTER", "NEEDS_INTEGRATION_POINT"):
        return "PASS_REVIEW"
    return "BLOCK"  # NOT_CALLABLE veya UNKNOWN


# --- Kayit (SADECE onaydan sonra - agent_loop tarafindan cagrilir) ---------

def register_discovered_tool(parameters: dict) -> str:
    """agent_loop'un onay akisindan SADECE kullanici onayladiktan sonra
    cagrilir. Jarvis'in gercek koduna (main.py, actions/) HICBIR SEY
    yazmaz - sadece bir kayit ekler. Gercek entegrasyon ayri, bilincli
    bir adimdir (self_improve/dev_agent ile kullanicinin kendi istegiyle)."""
    items = _load_registry()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "name": parameters.get("name", "bilinmeyen"),
        "description": parameters.get("description", ""),
        "quarantine_path": parameters.get("quarantine_path", ""),
        "registered_at": datetime.now().isoformat(),
        "integrated": False,
    }
    items.append(entry)
    _save_registry(items)
    return (
        f"'{entry['name']}' hafızaya kaydedildi (kayıt id: {entry['id']}). "
        f"NOT: Bu sadece bir kayıt — Jarvis'in kendi koduna henüz entegre "
        f"edilmedi. Gerçekten kullanılabilir hale getirmek için ayrıca "
        f"'{entry['name']}'i kendine entegre et' diyerek self_improve/dev_agent "
        f"ile bilinçli bir adım daha atman gerekiyor."
    )


# --- agent_loop'un her turda cagirdigi ana giris noktasi -------------------

def scan_downloads_once() -> list[dict]:
    """Bir tur icinde Downloads'ta yeni bir zip/klasor bulunursa, karantinaya
    alir, analiz eder ve sonucu dondurur (agent_loop bunu bir onay gorevine
    cevirir). Analiz "tool" DEGILSE karantina hemen temizlenir ve bir daha
    hic bahsedilmez (ne bir onay istegi ne bir bildirim) - sadece 'tool'
    verdict'i kullaniciya ulasir."""
    results = []
    for item in find_new_downloads():
        _mark_seen(item)  # basarisiz da olsa bir daha denenmesin (sonsuz dongu olmasin)
        try:
            qpath = _quarantine(item)
        except Exception as e:
            print(f"[Discovery] ⚠️ Karantinaya alınamadı ({item.name}): {e}")
            continue

        try:
            verdict = _analyze(qpath)
        except Exception as e:
            print(f"[Discovery] ⚠️ Analiz başarısız ({item.name}): {e}")
            _cleanup_quarantine(qpath)
            continue

        if verdict.get("verdict") != "tool":
            print(f"[Discovery] '{item.name}' → {verdict.get('verdict')}, karantina temizleniyor.")
            _cleanup_quarantine(qpath)
            continue

        # YENI: "gercek bir tool" olmasi TEK BASINA yeterli degil - ayrica
        # Jarvis'in ZATEN VAR olan yeteneklerine gore GERCEKTEN faydali
        # olmasi da gerekiyor. Bu Downloads borusunun ONAYSIZ davranisini
        # DEGISTIRMEZ (useful cikan aday yine dogrudan, onay beklemeden
        # entegrasyon.integrate_discovered_tool()'a gider - agent_loop.py'de
        # hicbir sey degismedi) - sadece hangi adaylarin o asamaya
        # ULASACAGINI daraltir.
        gap = _gap_analyze(qpath, verdict)

        if gap.get("decision") not in ("USEFUL_NEW_CAPABILITY", "USEFUL_PARTIAL_CAPABILITY"):
            print(f"[Discovery] '{item.name}' → tool ama gap-analizi '{gap.get('decision')}' dedi "
                  f"({gap.get('reason', '')}), karantina temizleniyor (entegre EDILMIYOR).")
            _log_gap_result(item.name, verdict, gap, combined_decision="BLOCK")
            _cleanup_quarantine(qpath)
            continue

        # YENI (3. soru): "yeni/faydali" olmasi da TEK BASINA yeterli degil -
        # Jarvis'in bunu GERCEKTEN cagirabilecegi bir yol da olmali. Downloads
        # borusunun HICBIR onay adimi olmadigi icin (kullanicinin bilincli,
        # onceden verdigi izinle) - burada SADECE tam CALLABLE olanlar
        # (combine_gap_and_usability -> 'PASS_AUTO') gecebilir.
        # CALLABLE_WITH_ADAPTER/NEEDS_INTEGRATION_POINT gibi "insan
        # incelemesi" gerektiren durumlar icin bu boruda bir onay noktasi
        # YOK - bu yuzden onlar da burada ENGELLENIR (GitHub borusundaki
        # ZATEN VAR olan onay akisinin aksine, bkz. github_arama.py).
        usability = _capability_usability_analyze(qpath, verdict, gap)
        combined = combine_gap_and_usability(gap.get("decision", ""), usability.get("decision", ""))
        _log_gap_result(item.name, verdict, gap, usability=usability, combined_decision=combined)

        if combined != "PASS_AUTO":
            print(f"[Discovery] '{item.name}' → gap useful ama kullanılabilirlik '{usability.get('decision')}' "
                  f"dedi ({usability.get('reason', '')}), karantina temizleniyor (Downloads borusunda "
                  f"onay noktası olmadığı için PASS_REVIEW durumları da burada engellenir).")
            _cleanup_quarantine(qpath)
            continue

        results.append({
            "source_name": item.name,
            "description": verdict.get("description", ""),
            "reasoning": verdict.get("reasoning", ""),
            "quarantine_path": str(qpath),
            "gap_decision": gap.get("decision", ""),
            "gap_reason": gap.get("reason", ""),
            "missing_capability": gap.get("missing_capability", ""),
            "usability_decision": usability.get("decision", ""),
            "call_path": usability.get("call_path", ""),
        })

    return results
