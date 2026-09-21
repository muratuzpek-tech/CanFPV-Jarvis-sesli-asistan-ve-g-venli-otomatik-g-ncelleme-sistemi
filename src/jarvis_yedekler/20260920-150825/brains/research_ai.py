"""research_ai.py — RESEARCH AI: Araştırma Beyni.

Görevi (bölüm 3): internette araştırma yapmak, kaynakları karşılaştırmak,
bilgi toplamak, sonucu YAPILANDIRILMIŞ şekilde döndürmek. Kod DEĞİŞTİRMEZ.

Gerçek internet erişimi için mevcut actions/web_search.py'yi kullanır -
YENİ bir arama/scraping mekanizması icat etmez (tools_kopru.py'nin "sadece
var olan araçları kullan" ilkesiyle tutarlı).
"""
from __future__ import annotations

import re

from jarvis.brains.base_brain import BaseBrain, BrainError

# 2026-09-15 canli testte bulundu: Planner bazen "actions/dev_agent.py
# dosyasini incele/analiz et" gibi YEREL proje dosyasi okuma adimlarini
# research_ai'ye atiyordu. research_ai'nin internet aramasi disinda hicbir
# yetkisi yok (yerel dosya okumaz - bu coder_ai'nin isi), dolayisiyla boyle
# bir adim ic bir web aramasina donusturuluyor ("dosyayi inceleyin" gibi bir
# cumleyi Google'da aratmak) ve dogal olarak alakasiz/bos sonuc donuyordu
# (bazen tesadufen hava durumu/KDV hesaplayici gibi tamamen alakasiz
# sayfalar bile eslesebiliyordu). Boyle bir istek gelirse BOSUNA arama
# yapmadan, durumu ACIKCA "bu benim isim degil" diye bildiriyoruz.
_LOCAL_FILE_PATTERN = re.compile(
    r"[\w./\\-]+\.(py|json|txt|md|ini|cfg|ya?ml|log)\b", re.IGNORECASE
)

SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın ARAŞTIRMA BEYNİsin (research_ai).

GÖREVİN: Sana verilen ham arama sonuçlarını degerlendirip, YAPILANDIRILMIŞ
bir arastirma raporuna donustur: bulgular, kaynaklar, oneriler.

KESİN SINIRLAR:
- Kod YAZMA/DEĞİŞTİRME - bu coder_ai'nin işi.
- Kaynaksız/uydurma bilgi verme - SADECE sana verilen arama sonuçlarına dayan;
  yeterli bilgi yoksa bunu findings içinde açıkça belirt.

SADECE şu JSON şemasında dön:
{
  "agent": "research_ai",
  "status": "completed",
  "findings": ["..."],
  "sources": ["..."],
  "recommendations": ["..."]
}"""


class ResearchAI(BaseBrain):
    NAME = "research_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def handle(self, message: dict) -> dict:
        payload = message.get("payload") or {}
        query = payload.get("query", "").strip()
        if not query:
            raise BrainError("research_ai: 'query' parametresi boş olamaz.")

        # Yerel proje dosyasi okuma/analiz istegi mi? (bkz. dosya basi not).
        # Boyleyse internete hic cikmadan, dogru/durust bir "kapsam disi"
        # sonucu don - bosuna Gemini/DDG cagrisi harcamayalim ve Auditor'a
        # yanlislikla "arastirma yapildi ama bulgu yok" degil, gercek nedeni
        # gorsun.
        if _LOCAL_FILE_PATTERN.search(query):
            self.log(f"Kapsam disi (yerel dosya) istegi, arama yapilmadi: {query!r}")
            return self.ok(message, {
                "agent": "research_ai",
                "status": "completed",
                "findings": [
                    "Bu adım proje içindeki YEREL bir dosyayı okuma/analiz etme istiyor. "
                    "research_ai SADECE genel internette arama yapabilir, yerel proje "
                    "dosyalarını okuyamaz - bu coder_ai'nin (dosyayı okuyup değiştirme "
                    "yetkisi olan tek beyin) veya doğrudan orchestrator'ın işi."
                ],
                "sources": [],
                "recommendations": [
                    "Bu adımı research_ai yerine coder_ai'ye (dosya yolu belirterek) "
                    "atayın, ya da plan dışında doğrudan inceleyin.",
                ],
            })

        # Gercek arama - mevcut araclar, YENI bir mekanizma degil.
        #
        # DUZELTME (2026-09-15, canli testte bulundu): sorguda "github"
        # geciyorsa (ornegin "GitHub'da ... acik kaynakli projeler arayin"),
        # bu adim HER ZAMAN genel web_search.py'ye (Gemini google_search /
        # DDG fallback) gidiyordu - bu da GitHub depolarindan tamamen alakasiz
        # sonuclar donduruyordu (bir canli calistirmada Isvec trafik
        # isaretleri ve alakasiz tibbi makaleler cikmisti). Oysa proje zaten
        # GERCEK GitHub arama API'sine sarilan actions/github_arama.py'yi
        # tasiyor (brain_orchestrator._infer_executor_action executor_ai
        # icin zaten ayni "github" -> github_search eslemesini yapiyor,
        # research_ai icin hic yapilmiyordu). Sonuc: "github" gecen sorgular
        # artik ONCE gercek GitHub depo aramasina gidiyor.
        if "github" in query.lower():
            try:
                from jarvis.actions.github_arama import github_search
                raw_results = github_search({"query": query}) or ""
            except Exception as e:
                raw_results = f"(github_search çağrısı başarısız oldu: {e})"
        else:
            try:
                from jarvis.actions.web_search import web_search
                raw_results = web_search(parameters={"query": query, "mode": payload.get("mode", "search")}) or ""
            except Exception as e:
                raw_results = f"(web_search çağrısı başarısız oldu: {e})"

        report = self.call_llm_json(
            f"ARAŞTIRMA KONUSU: {query}\n\nHAM ARAMA SONUÇLARI:\n{raw_results[:6000]}"
        )
        if not isinstance(report, dict):
            raise BrainError(f"research_ai: model beklenen rapor şemasını döndürmedi: {report!r}")

        report.setdefault("agent", "research_ai")
        report.setdefault("status", "completed")
        report.setdefault("findings", [])
        report.setdefault("sources", [])
        report.setdefault("recommendations", [])

        self.log(f"Araştırma tamamlandı: {query!r} — {len(report['findings'])} bulgu")
        return self.ok(message, report)
