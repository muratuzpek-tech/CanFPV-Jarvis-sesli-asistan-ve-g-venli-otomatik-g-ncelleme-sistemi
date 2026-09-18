"""
test_usability_jc.py — jc (kellyjonbrazil/jc) için GERÇEK karantina verisi
üzerinde, YENİ kullanılabilirlik (usability) analizini
(actions.discovery._capability_usability_analyze) CANLI Gemini API'siyle
test eder.

NEDEN BU BETİK VAR: test_gap_jc.py ile aynı gerekçe — Claude'un sandbox'ında
kullanıcının gerçek Gemini API anahtarı yok, bu yüzden GERÇEK/canlı bir karar
burada üretilemiyor. Bu betik cihazınızda çalıştırılmalı.

KULLANIM (FINAL_BUILD klasöründe, PowerShell'de):
    python test_usability_jc.py

Bu betik SADECE OKUR - hiçbir kalıcı değişiklik yapmaz (tek istisna: sonucu
discovery_gap_log.jsonl'a bir satır olarak ekler, aynı test_gap_jc.py gibi).
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1] / "src" / "jarvis"
sys.path.insert(0, str(BASE_DIR))

from jarvis.actions.discovery import (  # noqa: E402
    _capability_usability_analyze,
    _gap_analyze,
    _log_gap_result,
    combine_gap_and_usability,
    QUARANTINE_ROOT,
)

JC_QUARANTINE = QUARANTINE_ROOT / "9041372b28"

TOOL_VERDICT = {
    "verdict": "tool",
    "description": (
        "Standart komut satırı araçlarının ve sistem dosyalarının "
        "çıktılarını JSON formatına dönüştürmeyi sağlayan açık kaynaklı "
        "'jc' aracının kaynak kodları."
    ),
    "reasoning": "(orijinal analiz sırasında ayrıca saklanmadı)",
}


def main() -> None:
    if not JC_QUARANTINE.is_dir():
        print(f"HATA: karantina klasörü bulunamadı: {JC_QUARANTINE}")
        sys.exit(1)

    print("1/2: Yetenek-boşluğu (gap) analizi çalıştırılıyor (gerekli - "
          "usability analizi buna bağlı context kullanıyor)...")
    gap = _gap_analyze(JC_QUARANTINE, TOOL_VERDICT)
    print(json.dumps(gap, indent=2, ensure_ascii=False))

    print("\n2/2: Kullanılabilirlik (usability) analizi çalıştırılıyor "
          "(gerçek, canlı Gemini API çağrısı)...")
    usability = _capability_usability_analyze(JC_QUARANTINE, TOOL_VERDICT, gap)
    combined = combine_gap_and_usability(gap.get("decision", ""), usability.get("decision", ""))

    print("\n" + "=" * 70)
    print("GERÇEK KULLANILABİLİRLİK ANALİZİ SONUCU (kellyjonbrazil/jc):")
    print("=" * 70)
    print(json.dumps(usability, indent=2, ensure_ascii=False))
    print(f"\nBİRLEŞİK KARAR: {combined}")
    print("  (PASS_AUTO = onaysız da geçebilir, PASS_REVIEW = sadece insan "
          "onaylı boruda geçebilir, BLOCK = hiçbir yerde geçmez)")
    print("=" * 70)

    _log_gap_result("kellyjonbrazil/jc (retrospektif usability testi)", TOOL_VERDICT, gap,
                     usability=usability, combined_decision=combined)
    print(f"\nSonuç ayrıca {BASE_DIR / 'memory' / 'discovery_gap_log.jsonl'} dosyasına eklendi.")


if __name__ == "__main__":
    main()
