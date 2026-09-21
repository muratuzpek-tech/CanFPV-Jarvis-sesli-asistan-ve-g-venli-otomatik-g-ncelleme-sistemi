"""
github_arama.py — agent_loop bir gorev icin var olan araclarla yetinemeyip
GitHub'da hazir bir cozum aramasi gerektigine karar verdiginde kullanilan
arama araci VE (kullanicinin acikca istedigi) GitHub'dan yeni bir yetenek
kesfeden/degerlendiren arka plan hattinin bulundugu modul.

BOLUM 1 — github_search(): SALT OKUNUR arama.
ONEMLI: Bu fonksiyon HICBIR SEYI INDIRMEZ/CALISTIRMAZ - sadece GitHub'in
genel arama API'siyle depo bilgisi (isim, aciklama, yildiz, lisans, URL)
dondurur. Bulunan bir deponun GERCEKTEN indirilip kullanilmasi, ayri bir
adimdir (asagida BOLUM 2).

BOLUM 2 — github_arac_bul_ve_degerlendir() / apply_pending_integration():
Kullanicinin acikca istedigi ("kendisi icin daha iyi yazilim aramasi"),
agent_loop'un VAR OLAN gorev sistemi uzerinden calisan, tekrarlayan bir
kesif hatti. discovery.py'nin Downloads icin yaptigi karantina+analiz
akisinin AYNISINI GitHub arama sonuclari icin uygular (ayni
_safe_extract_zip/_analyze fonksiyonlari, discovery.py'den PAYLASILIR).

TASARIM FARKI — kullanicinin bu ozellik icin acikca sectigi, discovery.py'nin
Downloads hattindan (bkz. entegrasyon.py, "sormadan kendisi entegre etsin")
BILINCLI olarak FARKLI bir davranis:
  - Downloads hatti: bulunan arac otomatik, ONAY BEKLEMEDEN entegre edilir.
  - Bu GitHub hatti: bulunan arac ASLA otomatik entegre edilmez - once
    kullaniciya SORULUR (agent_loop'un onay akisi). Kullanici bunu acikca
    boyle istedi ("Once sana sorsun (onay bekleyerek)").

Bu davranis farki icin OZEL bir "bypass" kodu YAZILMADI - sadece iki yeni
arac (bkz. tools_kopru.py) kaydedildi:
  1. github_arac_bul_ve_degerlendir  -> GUVENLI (yikici degil): sadece arar,
     izole karantinaya indirir, analiz eder. Jarvis'in KENDI koduna hicbir
     sey yazmaz.
  2. entegrasyon_uygula              -> YIKICI: gercek entegrasyonu yapar
     (entegrasyon.integrate_discovered_tool cagirir). tools_kopru.py'nin
     is_destructive() fonksiyonu bunu otomatik olarak onay bekleyen
     (awaiting_approval) hale getirir - agent_loop.py'de degisiklik
     GEREKMEDI, sistem zaten boyle tasarlanmisti.

Iki adim arasindaki kopru: bulunan "arac" adayinin detaylari (aciklama,
karantina yolu) memory/github_pending_integration.json'a yazilir - boylece
planlayici modelin (Gemini) ikinci adimda uzun/kirilgan bir yol string'ini
dogru hatirlamasina GEREK KALMAZ, sadece kisa source_name'i tekrar eder.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests
from jarvis.paths import memory_dir

_API_URL = "https://api.github.com/search/repositories"
_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 60


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
SEEN_PATH = memory_dir() / "github_seen.json"
PENDING_INTEGRATION_PATH = memory_dir() / "github_pending_integration.json"


class GithubSearchError(Exception):
    """github_search() ve github_arac_bul_ve_degerlendir() tarafindan
    paylasilan, kullaniciya dogrudan gosterilebilir Turkce mesajli hata."""
    pass


# --- Ham arama (her iki giris noktasi tarafindan paylasilir) ---------------

def _raw_search(query: str, min_stars: int = 0, max_results: int = 5) -> list[dict]:
    """GitHub arama API'sine tek bir HTTP istegi atar, ham repo sozluklerini
    (full_name, stars, license, description, html_url, default_branch)
    dondurur. Hata durumunda GithubSearchError firlatir."""
    query = (query or "").strip()
    if not query:
        raise GithubSearchError("Arama için bir sorgu (query) gerekli.")

    max_results = min(int(max_results or 5), 10)
    q = query
    if min_stars > 0:
        q += f" stars:>={min_stars}"

    try:
        resp = requests.get(
            _API_URL,
            params={"q": q, "sort": "stars", "order": "desc", "per_page": max_results},
            headers={"Accept": "application/vnd.github+json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise GithubSearchError(f"GitHub aramasında bağlantı hatası: {e}") from e

    if resp.status_code == 403:
        raise GithubSearchError("GitHub API oran sınırına takıldı (rate limit) — birazdan tekrar dene.")
    if resp.status_code != 200:
        raise GithubSearchError(f"GitHub arama hatası: HTTP {resp.status_code}")

    try:
        items = resp.json().get("items", [])
    except Exception as e:
        raise GithubSearchError(f"GitHub yanıtı ayrıştırılamadı: {e}") from e

    results = []
    for repo in items:
        results.append({
            "full_name": repo.get("full_name", "") or "",
            "stars": repo.get("stargazers_count", 0),
            "license": (repo.get("license") or {}).get("spdx_id", "lisanssız"),
            "description": (repo.get("description") or "").strip(),
            "html_url": repo.get("html_url", ""),
            "default_branch": repo.get("default_branch") or "main",
        })
    return results


def github_search(parameters: dict) -> str:
    parameters = parameters or {}
    query = (parameters.get("query") or "").strip()
    try:
        results = _raw_search(
            query,
            min_stars=int(parameters.get("min_stars", 0) or 0),
            max_results=int(parameters.get("max_results", 5) or 5),
        )
    except GithubSearchError as e:
        return str(e)

    if not results:
        return f"'{query}' için depo bulunamadı."

    lines = [f"'{query}' için {len(results)} sonuç (yıldıza göre sıralı):"]
    for repo in results:
        lines.append(
            f"- {repo['full_name']} ⭐{repo['stars']} [{repo['license']}] — "
            f"{repo['description'][:100]}\n  {repo['html_url']}"
        )
    return "\n".join(lines)


# --- Kesif hatti icin "gorulmus" takibi (discovery.py'nin ayni deseni) ----

def _load_seen() -> dict:
    from jarvis.actions.discovery import _load_json
    return _load_json(SEEN_PATH, {})


def _save_seen(seen: dict) -> None:
    from jarvis.actions.discovery import _atomic_write_json
    try:
        _atomic_write_json(SEEN_PATH, seen)
    except Exception as e:
        print(f"[GithubArama] ⚠️ github_seen.json yazılamadı: {e}")


def _load_pending() -> dict:
    from jarvis.actions.discovery import _load_json
    return _load_json(PENDING_INTEGRATION_PATH, {})


def _save_pending(data: dict) -> None:
    from jarvis.actions.discovery import _atomic_write_json
    try:
        _atomic_write_json(PENDING_INTEGRATION_PATH, data)
    except Exception as e:
        print(f"[GithubArama] ⚠️ github_pending_integration.json yazılamadı: {e}")


def _download_zip(full_name: str, branch: str, dest_zip: Path) -> None:
    url = f"https://codeload.github.com/{full_name}/zip/refs/heads/{branch}"
    try:
        resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT, stream=True)
    except requests.RequestException as e:
        raise GithubSearchError(f"'{full_name}' indirilirken bağlantı hatası: {e}") from e
    if resp.status_code != 200:
        raise GithubSearchError(f"'{full_name}' indirilemedi: HTTP {resp.status_code}")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_zip, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                f.write(chunk)


# --- Kesif + degerlendirme (BULMA - Jarvis'in kendi koduna HICBIR SEY yazmaz) --

def github_arac_bul_ve_degerlendir(parameters: dict) -> str:
    """agent_loop'un, kullanicinin ekledigi bir gorev uzerinden TEKRAR TEKRAR
    (her tick'te) cagirdigi kesif adimi. discovery.py'nin Downloads icin
    yaptigi karantina+analiz akisinin aynisini GitHub sonuclari icin uygular.

    GUVENLI (yikici degil) sayilir: sadece GitHub'da arar, DAHA ONCE
    DEGERLENDIRILMEMIS ilk sonucu izole bir karantina klasorune indirir,
    Gemini'den ayni "tool/junk/dangerous" degerlendirmesini alir. 'tool'
    verdict'inde bile Jarvis'in gercek koduna (actions/, tools_kopru.py)
    HICBIR SEY YAZMAZ - sadece memory/github_pending_integration.json'a bir
    aday kaydeder ve kullaniciya bunu 'entegrasyon_uygula' araciyla
    ONAYLAMASI gerektigini soyler (bkz. bu dosyanin basindaki tasarim notu).
    """
    parameters = parameters or {}
    query = (parameters.get("query") or "").strip()
    if not query:
        return "Arama için bir sorgu (query) gerekli."

    try:
        results = _raw_search(query, min_stars=int(parameters.get("min_stars", 0) or 0), max_results=10)
    except GithubSearchError as e:
        return str(e)

    seen = _load_seen()
    candidate = next(
        (r for r in results if r["full_name"] and r["full_name"] not in seen), None,
    )
    if candidate is None:
        return (f"'{query}' için GitHub'da yeni (daha önce değerlendirilmemiş) bir aday "
                f"bulunamadı. Görev tamamlanmış sayılabilir.")

    full_name = candidate["full_name"]
    # Basarisiz da olsa hemen isaretle - ayni aday sonsuz donguyle tekrar
    # tekrar denenmesin (discovery.py'nin _mark_seen'iyle ayni mantik).
    seen[full_name] = {"seen_at": datetime.now().isoformat(), "query": query}
    _save_seen(seen)

    from jarvis.actions.discovery import QUARANTINE_ROOT, _safe_extract_zip, _analyze, _cleanup_quarantine

    qid = uuid.uuid4().hex[:10]
    qpath = QUARANTINE_ROOT / qid
    tmp_zip = QUARANTINE_ROOT / f"_dl_{qid}.zip"

    try:
        _download_zip(full_name, candidate.get("default_branch", "main"), tmp_zip)
    except Exception as e:
        return f"'{full_name}' indirilirken hata: {e}"

    try:
        _safe_extract_zip(tmp_zip, qpath)
    except Exception as e:
        _cleanup_quarantine(qpath)
        return f"'{full_name}' güvenli şekilde çıkarılamadı, atlandı: {e}"
    finally:
        tmp_zip.unlink(missing_ok=True)

    try:
        verdict = _analyze(qpath)
    except Exception as e:
        _cleanup_quarantine(qpath)
        return f"'{full_name}' analiz edilemedi: {e}"

    if verdict.get("verdict") != "tool":
        _cleanup_quarantine(qpath)
        return (f"'{full_name}' değerlendirildi: {verdict.get('verdict')} — entegre "
                f"edilmeyecek. ({verdict.get('reasoning', '')})")

    # YENI: "gercek bir tool" olmasi TEK BASINA yeterli degil - ayrica
    # Jarvis'in ZATEN VAR olan yeteneklerine gore GERCEKTEN faydali olmasi
    # da gerekiyor. ONEMLI: bu, GitHub hattinin mevcut ONAY akisini hicbir
    # sekilde DEGISTIRMEZ/ZAYIFLATMAZ - is_destructive()/approve_task()/
    # deny_task() aynen eskisi gibi calisir. Bu gate sadece hangi adaylarin
    # DAHA BASTAN onay asamasina bile ULASACAGINI daraltir: yararsiz/
    # tekrarlayan bir aday zaten 'entegrasyon_uygula' cagrisina hic konu
    # olmaz, kullaniciya bosuna onay sorulmaz.
    from jarvis.actions.discovery import _gap_analyze, _log_gap_result

    gap = _gap_analyze(qpath, verdict)

    if gap.get("decision") not in ("USEFUL_NEW_CAPABILITY", "USEFUL_PARTIAL_CAPABILITY"):
        _log_gap_result(full_name, verdict, gap, combined_decision="BLOCK")
        _cleanup_quarantine(qpath)
        return (
            f"'{full_name}' gerçek bir yazılım ama yetenek-boşluğu analizi "
            f"'{gap.get('decision')}' dedi — entegre edilmeyecek. "
            f"({gap.get('reason', '')})"
        )

    # YENI (3. soru): "yeni/faydali" olmasi da yetmez - Jarvis bunu GERCEKTEN
    # cagirabilmeli. GitHub borusunda ZATEN bir insan onayi var (asagida
    # 'ARAÇ:' mesaji sadece bir ONAY TALEBIDIR, entegrasyon_uygula CAGRILMADAN
    # hicbir sey olmaz) - bu yuzden PASS_AUTO (tam CALLABLE) VE PASS_REVIEW
    # (adapter/entegrasyon noktasi gerekebilir) ikisi de kullaniciya sorulmak
    # UZERE pending'e yazilabilir; kullanici onaylarken bu ek bilgiyi
    # (usability_decision) gorur. SADECE BLOCK (NOT_CALLABLE/UNKNOWN)
    # pending'e hic ulasmaz.
    from jarvis.actions.discovery import _capability_usability_analyze, combine_gap_and_usability
    usability = _capability_usability_analyze(qpath, verdict, gap)
    combined = combine_gap_and_usability(gap.get("decision", ""), usability.get("decision", ""))
    _log_gap_result(full_name, verdict, gap, usability=usability, combined_decision=combined)

    if combined == "BLOCK":
        _cleanup_quarantine(qpath)
        return (
            f"'{full_name}' yeni/faydalı bulundu ama kullanılabilirlik analizi "
            f"'{usability.get('decision')}' dedi — Jarvis'in bunu çağıracak gerçek "
            f"bir yolu yok, entegre edilmeyecek. ({usability.get('reason', '')})"
        )

    pending = _load_pending()
    pending[full_name] = {
        "description": verdict.get("description", ""),
        "quarantine_path": str(qpath),
        "html_url": candidate.get("html_url", ""),
        "stars": candidate.get("stars", 0),
        "found_at": datetime.now().isoformat(),
        "gap_decision": gap.get("decision", ""),
        "gap_reason": gap.get("reason", ""),
        "missing_capability": gap.get("missing_capability", ""),
        "concrete_use_case": gap.get("concrete_use_case", ""),
        "usability_decision": usability.get("decision", ""),
        "usability_reason": usability.get("reason", ""),
        "call_path": usability.get("call_path", ""),
        "integration_point": usability.get("integration_point", ""),
    }
    _save_pending(pending)

    # KISA tutulmali VE KRITIK KISIM ONCE gelmeli: agent_loop._decide_next_step()
    # planlama gecmisinde 'result' alanini ILK 150 karaktere kirpiyor - model
    # bir sonraki tick'te entegrasyon_uygula(source_name=...) cagrisini
    # gecmisten hatirlamak zorunda kalirsa, bu cagri satiri mutlaka o ilk
    # 150 karakterin icinde kalmali. Gap/usability bilgisi ONEMLI ama ikincil -
    # bu yuzden bilerek EN SONA, kirpilmasi zararsiz olacak sekilde eklendi.
    review_note = " [İNCELEME: adapter/entegrasyon noktası gerekebilir]" if combined == "PASS_REVIEW" else ""
    return (
        f"ARAÇ: '{full_name}'. Onay için entegrasyon_uygula(source_name='{full_name}') çağır. "
        f"(Yetenek-boşluğu: {gap.get('decision')} — {gap.get('reason', '')[:60]}. "
        f"Kullanılabilirlik: {usability.get('decision')}{review_note})"
    )


def apply_pending_integration(parameters: dict) -> str:
    """SADECE agent_loop'un onay akisindan (kullanici acikca 'onaylıyorum'
    dedikten SONRA, approve_task -> call_tool('entegrasyon_uygula', ...))
    cagrilir - bkz. tools_kopru.py'deki is_destructive(). GitHub'da bulunup
    'arac' olarak degerlendirilen bir adayi, entegrasyon.py'nin ZATEN
    kullandigi ayni guvenlik agiyla (tam proje yedegi + sozdizimi/import
    dogrulamasi + basarisiz olursa otomatik geri alma) Jarvis'in GERCEK
    koduna yazar."""
    source_name = (parameters or {}).get("source_name", "").strip()
    if not source_name:
        return "Entegre edilecek aracın adı (source_name) belirtilmedi."

    pending = _load_pending()
    entry = pending.get(source_name)
    if entry is None:
        return f"'{source_name}' için bekleyen bir GitHub entegrasyon adayı bulunamadı."

    from jarvis.actions.entegrasyon import integrate_discovered_tool
    result = integrate_discovered_tool({
        "source_name": source_name,
        "description": entry.get("description", ""),
        "quarantine_path": entry.get("quarantine_path", ""),
    })

    # Basarili da olsa basarisiz da olsa bu aday "islendi" sayilir - ayni
    # adayla tekrar tekrar onay istenmesin. Kullanici isterse yeniden arama
    # yaptirip yeni bir kesif+onay akisi baslatabilir.
    pending.pop(source_name, None)
    _save_pending(pending)
    return result
