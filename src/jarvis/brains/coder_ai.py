"""coder_ai.py — CODER AI: Kodlama Beyni.

Görevi (bölüm 4): Python kodu yazmak, mevcut kodu analiz etmek, hataları
bulmak, kod iyileştirmek, test yazmak, teknik değişiklik önermek.

KESİN SINIR (kullanıcı talimatı: "Coder AI kendi başına kritik sistem
değişikliği yapmamalıdır"): Coder AI'nin KENDİSİ backup almaz, güvenlik
onayı istemez, Auditor'a göndermez - bunların HEPSİ brain_orchestrator.py
tarafından, Coder AI çağrılmadan ÖNCE ve SONRA yürütülür (bkz. 14. BACKUP
KURALI). Coder AI'ye bir değişiklik isteği geldiğinde, bu isteğin zaten
backup alınmış ve security_ai tarafından onaylanmış olduğu VARSAYILIR -
orchestrator bu sırayı garanti eder.

Coder AI kendi ürettiği değişikliği yazmadan önce/sonra EN AZ sözdizimi
düzeyinde kendi kendini doğrular (.py dosyaları için ast.parse) - bu
oturum boyunca her manuel kod değişikliğinde kullanılan AYNI doğrulama
adımı, otomatikleştirilmiş hali."""
from __future__ import annotations

import ast
from pathlib import Path

from jarvis.brains.base_brain import BaseBrain, BrainError

SYSTEM_PROMPT = """Sen JARVIS AI Beyin Takımı'nın KODLAMA BEYNİsin (coder_ai).

Sana bir dosyanın MEVCUT içeriği ve istenen değişiklik verilecek. Görevin:
dosyanın YENİ, TAM içeriğini üretmek (sadece bir parça değil - dosyanın
BAŞTAN SONA tamamı). Mevcut kod stiline, dile (Türkçe yorum vs.) ve
mimariye sadık kal. Gereksiz yeniden yazım yapma - SADECE istenen
değişikliği uygula, geri kalanı olduğu gibi koru.

SADECE şu JSON şemasında dön (kod bloğu/markdown YOK, new_content ham
metin bir JSON string alanı olarak):
{"new_content": "...", "summary": "ne değiştirildiğinin kısa açıklaması"}"""


class CoderAI(BaseBrain):
    NAME = "coder_ai"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def handle(self, message: dict) -> dict:
        payload = message.get("payload") or {}
        file_path = payload.get("file_path", "").strip()
        change_request = payload.get("change_request", "").strip()
        dry_run = bool(payload.get("dry_run", False))

        if not file_path or not change_request:
            raise BrainError("coder_ai: 'file_path' ve 'change_request' zorunlu.")

        target = Path(file_path)
        if not target.is_file():
            raise BrainError(f"coder_ai: dosya bulunamadı: {file_path}")

        current_content = target.read_text(encoding="utf-8")

        response = self.call_llm_json(
            f"DOSYA: {file_path}\n\nMEVCUT İÇERİK:\n{current_content}\n\n"
            f"İSTENEN DEĞİŞİKLİK:\n{change_request}"
        )
        if not isinstance(response, dict) or "new_content" not in response:
            raise BrainError(f"coder_ai: model beklenen şemayı döndürmedi: {response!r}")

        new_content = response["new_content"]
        summary = response.get("summary", change_request)

        # Kendi kendini dogrulama - .py dosyalari icin en az sozdizimi kontrolu.
        # Bu, bu oturum boyunca HER manuel degisiklikte yapilan kontrolun
        # otomatize edilmis hali - hicbir kod, gecerliligi dogrulanmadan
        # "hazir" sayilmaz.
        if target.suffix == ".py":
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                raise BrainError(f"coder_ai: üretilen kod geçersiz Python sözdizimi içeriyor, YAZILMADI: {e}") from e
        if dry_run:
            self.log(f"[dry_run] Değişiklik önerildi (yazılmadı): {file_path} — {summary}")
            return self.ok(message, {
                "file_path": file_path, "summary": summary,
                "new_content": new_content, "written": False,
            })

        target.write_text(new_content, encoding="utf-8")
        self.log(f"Dosya güncellendi: {file_path} — {summary}")
        return self.ok(message, {
            "file_path": file_path, "summary": summary, "written": True,
        })
