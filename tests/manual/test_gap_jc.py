"""
test_gap_jc.py — jc (kellyjonbrazil/jc) icin GERCEK karantina verisi
uzerinde, YENI gap-analiz sistemini (actions.discovery._gap_analyze)
CANLI Gemini API'siyle test eder.

NEDEN BU BETIK VAR: Kullanici, yeni "gercekten faydali mi?" analizinin
jc uzerinde NE SONUC VERECEGINI gormek istedi - UYDURULMUS/ONCEDEN
BELIRLENMIS bir sonuc degil, gercek bir sonuc. Bu test Claude'un kendi
sandbox'inda calistirilamaz cunku gercek Gemini API cagrisi kullanicinin
KENDI config/api_keys.json'undaki anahtarini gerektiriyor - o anahtar
Claude'a hicbir zaman verilmedi/okunmadi (kullanicinin API kotasini/
parasini onun bilgisi disinda harcamak dogru olmaz).

KULLANIM (FINAL_BUILD klasorunde, PowerShell'de):
    python test_gap_jc.py

Bu betik SADECE OKUR - Jarvis'in gercek koduna, hafizasina veya
config'ine HICBIR SEY YAZMAZ (tek istisna: sonucu, zaten var olan
discovery_gap_log.jsonl formatiyla ayni dosyaya bir satir olarak EKLER,
boylece bu retrospektif test de normal log akisinda gorunur).
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1] / "src" / "jarvis"
sys.path.insert(0, str(BASE_DIR))

from jarvis.actions.discovery import _gap_analyze, _log_gap_result, QUARANTINE_ROOT  # noqa: E402

# jc'nin GERCEK karantina klasoru - memory/discovered_tools.json'daki kayittan
# alindi. integrate_discovered_tool() bu klasoru HICBIR ZAMAN silmedi, hala
# diskte duruyor (dogrulandi: 2026-09-16 itibariyle mevcut).
JC_QUARANTINE = QUARANTINE_ROOT / "9041372b28"

# jc'nin GERCEK on-degerlendirme aciklamasi (discovered_tools.json'daki
# kayittan, birebir). 'reasoning' alani orijinal _analyze() cagrisinda kalici
# olarak saklanmadigi icin bilinmiyor - bu SADECE bir bilgi kaybidir, gap
# analizinin kendisini etkilemez (capability_registry ozeti + adayin GERCEK
# dosya/bagimlilik verisi zaten tam ve gercek).
TOOL_VERDICT = {
    "verdict": "tool",
    "description": (
        "Standart komut satırı araçlarının ve sistem dosyalarının "
        "çıktılarını JSON formatına dönüştürmeyi sağlayan açık kaynaklı "
        "'jc' aracının kaynak kodları."
    ),
    "reasoning": "(orijinal analiz sırasında ayrıca saklanmadı - sadece description kaydedilmişti)",
}


def main() -> None:
    if not JC_QUARANTINE.is_dir():
        print(f"HATA: karantina klasörü bulunamadı: {JC_QUARANTINE}")
        print("Muhtemelen elle silinmiş. Bu durumda gap-analizini görmek için "
              "aynı 'jc' sorgusuyla yeni bir GitHub keşfi tetiklemek gerekir.")
        sys.exit(1)

    file_count = sum(1 for _ in JC_QUARANTINE.rglob("*") if _.is_file())
    print(f"Karantina klasörü: {JC_QUARANTINE} ({file_count} dosya)")
    print("Gemini'ye GERÇEK gap-analizi sorgusu gönderiliyor (canlı API çağrısı, "
          "birkaç saniye sürebilir)...\n")

    try:
        result = _gap_analyze(JC_QUARANTINE, TOOL_VERDICT)
    except Exception as e:
        print(f"HATA: gap-analizi çalıştırılamadı: {type(e).__name__}: {e}")
        sys.exit(1)

    print("=" * 70)
    print("GERÇEK GAP-ANALİZİ SONUCU (kellyjonbrazil/jc, retrospektif test):")
    print("=" * 70)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 70)

    if result.get("decision") == "UNKNOWN":
        print("\nNOT: UNKNOWN, gap-analizinin BAŞARISIZ olduğu (ağ hatası, geçersiz "
              "cevap vb.) GÜVENLİ varsayılan sonucudur - 'faydasız' anlamına gelmez, "
              "'değerlendirilemedi' anlamına gelir. 'reason' alanına bakın.")

    _log_gap_result("kellyjonbrazil/jc (retrospektif test)", TOOL_VERDICT, result)
    print(f"\nSonuç ayrıca {BASE_DIR / 'memory' / 'discovery_gap_log.jsonl'} dosyasına da eklendi.")


if __name__ == "__main__":
    main()
