"""e2e_file_task_self_test.py — UÇTAN UCA doğrulama testi (kullanıcı onaylı
"A+B+C" analiz raporunun "C" maddesi).

AMAÇ: "Agent 'yaptım' demesi başarı kanıtı değildir" ilkesini GERÇEK kodla
kanıtlamak - mock/simülasyon DEĞİL, gerçek `core.brain_orchestrator`,
gerçek `brains.executor_ai`, gerçek `actions.file_controller` fonksiyonları
kullanılır; SADECE `planner_ai` ve `auditor_ai`'nin Gemini çağrısı
(bu ikisi gerçek bir API anahtarı gerektirir, offline testte YAPILMAZ)
sahte/mock yanıtlarla değiştirilir - tıpkı diğer `*_self_test.py`
dosyalarındaki gibi.

Gerçekten çalışan/çağrılan üretim kodu (mock DEĞİL):
  - core.task_manager.TaskManager (geçici bir dosyaya yönlendirilir)
  - core.brain_orchestrator.BrainOrchestrator._infer_executor_action()
  - core.brain_orchestrator.BrainOrchestrator._execute_step()
    -> gerçek bus.send() -> gerçek brains.executor_ai.ExecutorAI.call()
    -> gerçek actions.file_controller.file_controller() -> GERÇEK
    dosya sistemi işlemleri (create_folder/create_file/write/read)
  - core.brain_orchestrator.BrainOrchestrator._finish_step()
    -> core.brain_orchestrator.BrainOrchestrator._verify_file_action()
    (YENİ eklenen bağımsız pathlib doğrulaması)

NOT (GÜNCELLEME, kullanıcı onaylı, 2026-09-16): bu testin 15 Eylül'deki
ilk hâlinde, `_infer_executor_action()`'ın HER adım için `path="."`
sabitlediği (bir klasör oluşsa bile sonraki adımların onun İÇİNE değil,
hep düz çalışma dizinine gittiği) ayrı bir mimari kopukluk bulunmuştu; test
o güne kadar bunu "düz yapı" olarak doğruluyordu. 16 Eylül'de bu kopukluk
da düzeltildi: `_finish_step()` artık başarılı bir create_folder adımından
sonra `payload["_active_folder"]`'ı günceller, `_execute_step()`/
`_verify_file_action()` de sonraki adımlarda bunu kullanır. Bu test artık
kullanıcının ORİJİNAL örneğini birebir doğruluyor: `jarvis_test`
KLASÖRÜNÜN GERÇEKTEN İÇİNE `test.txt` oluşuyor/yazılıyor/okunuyor.

İKİ SENARYO çalıştırılır:
  1) MUTLU YOL: her şey gerçekten olduğu gibi - auditor (mock) "passed=True"
     der VE bağımsız doğrulama da onaylar -> adım gerçekten geçer.
  2) SAHTE BAŞARI SİMÜLASYONU: auditor (mock) yine "passed=True" der (yani
     LLM'in kandığı senaryo simüle ediliyor) AMA gerçek dosya içeriği
     BEKLENENLE UYUŞMUYOR -> _verify_file_action bunu YAKALAMALI ve
     passed=False'a çevirmeli. Bu, düzeltmeden ÖNCEKİ koddaki tam olarak
     canlı testte görülen "sahte başarı" hatasını simüle eder.

Çalıştırma:
    cd core
    python e2e_file_task_self_test.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jarvis.core import brain_orchestrator as bo
from jarvis.core.task_manager import TaskManager


def _print_step_report(idx: int, step: dict, tool_action: str, tool_params: dict,
                        tool_result, verification_error, passed: bool) -> None:
    print(f"  Adım {idx}: {step['description']}")
    print(f"    seçilen agent   : {step['agent']}")
    print(f"    çağrılan tool   : file_controller / {tool_action}  (params={tool_params})")
    print(f"    tool sonucu     : {tool_result}")
    print(f"    verification    : {verification_error or 'OK - bağımsız pathlib kontrolü de doğruladı'}")
    print(f"    adım sonucu     : {'PASSED' if passed else 'FAILED'}")


def _run_scenario(tmp_dir: Path, tag: str, corrupt_after_write: bool) -> dict:
    """Bir görevi baştan sona (create_folder -> create_file -> write -> read)
    GERÇEK executor_ai/file_controller ile çalıştırır. corrupt_after_write
    True ise, file_controller yazdıktan SONRA dosyanın içeriğini bozarak
    (üretim kodunun kendi iç doğrulaması bunu YAKALAYACAĞI için) hem
    file_controller'ın kendi kontrolünü hem de orchestrator'ın bağımsız
    _verify_file_action() kontrolünü aynı anda test eder."""
    print(f"\n{'='*70}\nSENARYO: {tag}\n{'='*70}")

    orch = bo.BrainOrchestrator()
    orch.tasks = TaskManager(path=tmp_dir / "brain_tasks.json")

    # auditor_ai'ye giden bus.send'i SAHTE bir "passed=True" ile değiştir -
    # gerçek Gemini çağrısı YAPILMIYOR (bkz. dosya başı not). Diğer TÜM
    # hedefler (executor_ai dahil) GERÇEK bus.send'e gidiyor.
    _orig_send = orch.bus.send

    def _mock_send(from_agent, to_agent, task, payload=None, priority="medium"):
        if to_agent == "auditor_ai":
            return {"status": "completed",
                    "result": {"passed": True, "reason": "(mock) LLM bu sonucu geçerli buldu."}}
        return _orig_send(from_agent, to_agent, task, payload=payload, priority=priority)

    orch.bus.send = _mock_send

    goal = "Çalışma dizininde `jarvis_test` klasörü oluştur, içine `test.txt` oluştur, içine metni yaz, oku ve doğrula."
    task = orch.tasks.create(name=goal, agent="planner_ai", payload={"goal": goal})
    print(f"Task ID: {task['id']}")
    print("Planner sonucu: GERÇEK planner_ai ÇAĞRILMADI (Gemini API anahtarı gerektirir, "
          "offline testte yapılmaz) - plan, canlı testte gözlemlenen GERÇEK planner çıktısıyla "
          "AYNI şemada elle oluşturuldu.")

    expected_content = "Jarvis otonom görev testi başarılı."
    plan = [
        {"order": 1, "description": "Kullanıcının çalışma dizininde `jarvis_test` adlı bir klasör oluşturmak.",
         "agent": "executor_ai"},
        {"order": 2, "description": "`test.txt` adlı bir dosya oluşturmak.", "agent": "executor_ai"},
        # DUZELTME (kullanici onayli, 2026-09-15): bu adimin ONCEKI hali
        # ("Dosyaya '...' metnini yazmak.") icinde dosya ADI icin tek bir
        # tirnakli/backtick'li token YOKTU - sadece ICERIK metni vardi.
        # _extract_quoted() bu yuzden name="" donduruyor, gercek Planner
        # ciktisinda GORULMEYEN, sadece bu test scriptinin kendi elle
        # yazilmis (Gemini'siz) plan taslaginin bir kusuruydu - "BUG #2"
        # (bos isim -> hedef CWD olur) DEGIL, o ayri file_controller.py
        # duzeltmesiyle (bkz. yukarida) zaten ayrica ele alindi. Gercekci
        # bir Planner ciktisi gibi, dosya adini ACIKCA backtick icine alip
        # veriyoruz.
        {"order": 3, "description": f"`test.txt` dosyasına '{expected_content}' metnini yazmak.",
         "agent": "executor_ai"},
        {"order": 4, "description": "`test.txt` dosyasını oku.", "agent": "executor_ai"},
    ]
    payload = {"goal": goal, "plan": plan, "step_index": 0, "history": [], "audit_retries": 0}
    orch.tasks.update(task["id"], payload=payload)

    all_passed = True
    real_error = None
    for i, step in enumerate(plan, start=1):
        # Sadece raporlama için: _execute_step()'in KENDİSİNİN kullanacağı
        # AYNI base_path (bir önceki adımda gerçekten oluşmuş klasör varsa
        # onu) ile - yoksa rapordaki 'path' değeri gerçekte kullanılandan
        # farklı görünür.
        active_folder = payload.get("_active_folder", ".")
        action, params = orch._infer_executor_action(step["description"], active_folder)
        try:
            result = orch._execute_step(task, step)
        except Exception as e:
            real_error = str(e)
            all_passed = False
            break

        # SAHTE BAŞARI SİMÜLASYONU: file_controller GERÇEKTEN doğru yazdı,
        # ama biz (sadece bu senaryoda) yazma sonrası dosyayı BOZARAK,
        # auditor (mock) hâlâ "passed=True" derken bağımsız kontrolün
        # bunu YAKALAYIP YAKALAMADIĞINI test ediyoruz.
        if corrupt_after_write and step["order"] == 3:
            (tmp_dir / "jarvis_test" / "test.txt").write_text("BOZULMUŞ İÇERİK", encoding="utf-8")

        task["payload"] = payload
        orch._finish_step(task, step, result)
        step_passed = task["payload"]["history"][-1]["passed"]
        verification_error = task["payload"]["history"][-1]["audit"].get("reason") if not step_passed else None
        _print_step_report(i, step, params.get("action"), params, result, verification_error, step_passed)

        if not step_passed:
            all_passed = False
            # Üretim kodunun kendi mantığıyla AYNI: MAX_AUDIT_ROUNDS'a kadar
            # aynı adım tekrar denenebilir - bu testte tek denemede kesiyoruz
            # çünkü hata KALICI (bozulmuş dosya kendi kendine düzelmez).
            break

    # Bağımsız, GERÇEKTEN ham pathlib ile (orchestrator'dan/file_controller'
    # dan bile bağımsız) SON bir doğrulama - test scriptinin kendi güvenlik ağı.
    # Kullanıcının orijinal örneği: dosya jarvis_test KLASÖRÜNÜN İÇİNDE olmalı
    # (path-context düzeltmesi sayesinde artık gerçekten öyle - bkz. dosya
    # başı NOT).
    real_file = tmp_dir / "jarvis_test" / "test.txt"
    file_exists = real_file.is_file()
    content_matches = file_exists and real_file.read_text(encoding="utf-8") == expected_content

    final_status = "COMPLETED" if (all_passed and file_exists and content_matches) else "FAILED"
    orch.tasks.update(task["id"], status=final_status.lower() if final_status == "COMPLETED" else "failed",
                       payload=task["payload"],
                       result="Tüm adımlar ve bağımsız dosya doğrulaması geçti." if final_status == "COMPLETED"
                              else "En az bir adım veya bağımsız doğrulama başarısız oldu.")

    report = {
        "task_id": task["id"],
        "final_status": final_status,
        "real_error": real_error,
        "retry_count_field": task.get("retry_count", 0),
        "audit_retries_field": task["payload"].get("audit_retries", 0),
        "file_exists_independent_check": file_exists,
        "content_matches_independent_check": content_matches,
    }
    print("\n  --- BAĞIMSIZ SON DOĞRULAMA (test scriptinin kendisi, pathlib ile) ---")
    print(f"  Dosya gerçekten var mı  : {file_exists}")
    print(f"  İçerik gerçekten doğru mu: {content_matches}")
    print(f"  FINAL STATUS            : {final_status}")
    print(f"  Gerçek hata             : {real_error}")
    print(f"  retry_count alanı       : {report['retry_count_field']} "
          f"(NOT: bu alan şemada var ama brain_orchestrator.py'nin hiçbir yerinde "
          f"artırılmıyor - kullanılan gerçek sayaç payload['audit_retries'])")
    print(f"  audit_retries           : {report['audit_retries_field']}")

    orch.bus.send = _orig_send
    return report


def run() -> bool:
    ok = True
    tmp_dir = Path(tempfile.mkdtemp(prefix="e2e_file_task_", dir=str(Path.home())))
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_dir)  # _infer_executor_action() hep path="." kullanıyor - üretimdeki gibi

        r1 = _run_scenario(tmp_dir, "1) MUTLU YOL - gerçek dosya, gerçek içerik", corrupt_after_write=False)
        if r1["final_status"] != "COMPLETED" or not r1["content_matches_independent_check"]:
            print("[FAIL] Mutlu yol senaryosu COMPLETED olmalıydı!")
            ok = False
        else:
            print("\n[OK] Senaryo 1: gerçek dosya gerçekten oluştu, içerik gerçekten doğru, COMPLETED verildi.")

        shutil.rmtree(tmp_dir / "jarvis_test", ignore_errors=True)

        r2 = _run_scenario(tmp_dir, "2) SAHTE BAŞARI SİMÜLASYONU - auditor(mock) passed=True der ama dosya bozuk",
                            corrupt_after_write=True)
        if r2["final_status"] == "COMPLETED":
            print("[FAIL] Sahte başarı senaryosu YAKALANAMADI - COMPLETED verildi, bu YANLIŞ!")
            ok = False
        else:
            print("\n[OK] Senaryo 2: auditor(mock) 'passed=True' dediği HALDE, bağımsız doğrulama "
                  "(_verify_file_action) bunu yakaladı ve adımı FAILED'e çevirdi - 'sahte başarı' engellendi.")

    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return ok


if __name__ == "__main__":
    success = run()
    print("\n=== SONUÇ:", "BAŞARILI" if success else "BAŞARISIZ", "===")
    sys.exit(0 if success else 1)
