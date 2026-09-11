import subprocess
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
JARVIS_DIR      = BASE_DIR
MODEL           = "gemini-2.5-flash"
MAX_FIX_ATTEMPTS = 3
ERROR_LOG       = BASE_DIR / "logs" / "self_heal_log.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _log_heal(event: dict):
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if ERROR_LOG.exists():
        try:
            logs = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
        except Exception:
            logs = []
    logs.append(event)
    ERROR_LOG.write_text(
        json.dumps(logs[-100:], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _diagnose_error(error_text: str) -> dict:
    result = {
        "error_type": "unknown",
        "file": None,
        "line": None,
        "message": error_text[:500],
        "module": None,
    }

    low = error_text.lower()

    if any(x in low for x in ("modulenotfounderror", "no module named")):
        result["error_type"] = "dependency_error"
    elif "syntaxerror" in low:
        result["error_type"] = "syntax_error"
    elif any(x in low for x in ("importerror", "cannot import")):
        result["error_type"] = "import_error"
    elif any(x in low for x in ("attributeerror", "typeerror", "nameerror", "valueerror", "keyerror", "indexerror")):
        result["error_type"] = "runtime_error"
    elif any(x in low for x in ("connectionerror", "timeouterror", "websockets")):
        result["error_type"] = "connection_error"
    elif "api" in low or "401" in low or "403" in low:
        result["error_type"] = "api_error"
    elif "filenotfounderror" in low:
        result["error_type"] = "file_error"

    pattern = re.compile(
        r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE
    )
    matches = pattern.findall(error_text)

    jarvis_files = []
    other_files = []
    for raw_path, line_str in matches:
        if any(
            x in raw_path
            for x in ("actions", "core", "memory", "ui.py", "main.py")
        ):
            jarvis_files.append((raw_path, int(line_str)))
        else:
            other_files.append((raw_path, int(line_str)))

    if jarvis_files:
        result["file"], result["line"] = jarvis_files[-1]
    elif other_files:
        result["file"], result["line"] = other_files[-1]

    if result["file"]:
        result["module"] = Path(result["file"]).name.replace(".py", "")

    return result


def _read_file_safe(filepath: str) -> str:
    try:
        p = Path(filepath)
        if p.exists():
            return p.read_text(encoding="utf-8")
        p2 = JARVIS_DIR / filepath
        if p2.exists():
            return p2.read_text(encoding="utf-8")
        for subdir in ["actions", "core", "memory"]:
            p3 = JARVIS_DIR / subdir / filepath
            if p3.exists():
                return p3.read_text(encoding="utf-8")
            p3 = JARVIS_DIR / subdir / f"{filepath}.py"
            if p3.exists():
                return p3.read_text(encoding="utf-8")
        p4 = JARVIS_DIR / f"{filepath}.py"
        if p4.exists():
            return p4.read_text(encoding="utf-8")
        return ""
    except Exception:
        return ""


def _generate_fix(diagnosis: dict, file_content: str, error_text: str, speak=None) -> str:
    from google import genai
    client = genai.Client(api_key=_get_api_key())

    file_name = diagnosis.get("file", "unknown")
    line_num = diagnosis.get("line", "?")
    error_type = diagnosis.get("error_type", "unknown")

    prompt = (
        f"You are JARVIS's self-healing system. Fix the error in JARVIS's own codebase.\n"
        f"JARVIS is a voice-controlled AI assistant with PyQt6 UI and Gemini AI.\n\n"
        f"ERROR DETAILS:\n"
        f"- Error type: {error_type}\n"
        f"- File: {file_name}\n"
        f"- Line: {line_num}\n"
        f"- Full error:\n{error_text[:2500]}\n\n"
        f"CURRENT FILE CONTENT ({file_name}):\n{file_content}\n\n"
        f"FIX RULES:\n"
        f"- Output ONLY the complete fixed Python code. No explanation, no markdown, no backticks.\n"
        f"- Fix the specific error shown above.\n"
        f"- Keep ALL existing working logic. Do not remove features.\n"
        f"- Ensure all imports are correct and match the actual project structure.\n"
        f"- Do NOT introduce new bugs.\n"
        f"- If missing dependency, add try/except with fallback.\n"
        f"- If connection/API error, add retry logic with exponential backoff.\n"
        f"- If syntax error, fix only the syntax issue.\n"
        f"- Preserve UTF-8 encoding.\n\n"
        f"Fixed code for {file_name}:"
    )

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        fixed = _strip_fences(response.text)
        return fixed
    except Exception as e:
        if speak:
            speak(f"Self-heal AI hatasi: {str(e)[:80]}")
        return ""


def _apply_fix(filepath: str, fixed_code: str, speak=None) -> bool:
    try:
        p = Path(filepath)
        if not p.exists():
            p = JARVIS_DIR / filepath
        if not p.exists():
            for subdir in ["actions", "core", "memory"]:
                pc = JARVIS_DIR / subdir / filepath
                if pc.exists():
                    p = pc
                    break
                pc = JARVIS_DIR / subdir / f"{filepath}.py"
                if pc.exists():
                    p = pc
                    break
        if not p.exists():
            p = JARVIS_DIR / f"{filepath}.py"
        if not p.exists():
            if speak:
                speak(f"Dosya bulunamadi: {filepath}")
            return False

        backup_path = p.with_suffix(f".bak.{int(time.time())}")
        backup_path.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

        p.write_text(fixed_code, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(p)],
            capture_output=True, text=True, timeout=10,
        )

        if result.returncode != 0:
            p.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
            if speak:
                speak("Duzeltme syntax hatasi iceriyordu, geri alindi efendim.")
            return False

        try:
            backup_path.unlink()
        except Exception:
            pass

        return True

    except Exception as e:
        if speak:
            speak(f"Duzeltme uygulanamadi: {str(e)[:80]}")
        return False


def _try_auto_install(error_text: str) -> bool:
    pattern = re.compile(
        r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
    )
    match = pattern.search(error_text)
    if not match:
        return False

    pkg = match.group(1).replace("_", "-").split(".")[0]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def self_heal(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    p = parameters or {}
    error_text = p.get("error", "").strip()
    action = p.get("action", "fix").strip().lower()

    if action == "status":
        if ERROR_LOG.exists():
            try:
                logs = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
                recent = logs[-5:]
                summary = "\n".join(
                    f"- {e.get('time','?')} | {e.get('file','?')} | "
                    f"{e.get('error_type','?')} | "
                    f"{'Basarili' if e.get('fixed') else 'Basarisiz'}"
                    for e in recent
                )
                return f"Son self-heal girisimleri:\n{summary}"
            except Exception:
                pass
        return "Henuz self-heal kaydi yok, efendim."

    if action == "diagnose" and error_text:
        diagnosis = _diagnose_error(error_text)
        return json.dumps(diagnosis, indent=2, ensure_ascii=False)

    if action == "fix":
        if not error_text:
            return "Lutfen duzeltilecek hata mesajini verin, efendim."

        diagnosis = _diagnose_error(error_text)

        if diagnosis["error_type"] == "dependency_error":
            installed = _try_auto_install(error_text)
            if installed:
                _log_heal({
                    "time": datetime.now().isoformat(),
                    "error_type": diagnosis["error_type"],
                    "file": diagnosis["file"],
                    "fixed": True,
                    "method": "auto_install",
                })
                return f"Eksik paket otomatik kuruldu. Hata tipi: {diagnosis['error_type']}. Tekrar deneyin, efendim."

        if not diagnosis["file"]:
            return (
                f"Hata tipi: {diagnosis['error_type']}, ama hangi dosyayi "
                f"düzeltmem gerektigini bulamadim. Hata dis kaynaktan olabilir, efendim."
            )

        file_content = _read_file_safe(diagnosis["file"])
        if not file_content:
            return f"Dosya okunamadi: {diagnosis['file']}, efendim."

        if speak:
            speak(
                f"{Path(diagnosis['file']).name} dosyasindaki hatayi "
                f"analiz ediyorum, efendim. Kendi kendimi onarmaya calisiyorum..."
            )

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            fixed_code = _generate_fix(diagnosis, file_content, error_text, speak)
            if not fixed_code:
                continue

            success = _apply_fix(diagnosis["file"], fixed_code, speak)

            if success:
                _log_heal({
                    "time": datetime.now().isoformat(),
                    "error_type": diagnosis["error_type"],
                    "file": diagnosis["file"],
                    "line": diagnosis["line"],
                    "fixed": True,
                    "method": "ai_fix",
                    "attempts": attempt,
                })
                msg = (
                    f"Self-repair basarili, efendim! "
                    f"{diagnosis['error_type']} hatasi "
                    f"{Path(diagnosis['file']).name} dosyasinda {attempt} denemede duzeltildi."
                )
                if speak:
                    speak(msg)
                return msg

        _log_heal({
            "time": datetime.now().isoformat(),
            "error_type": diagnosis["error_type"],
            "file": diagnosis["file"],
            "line": diagnosis["line"],
            "fixed": False,
            "method": "ai_fix",
            "attempts": MAX_FIX_ATTEMPTS,
        })
        msg = (
            f"Self-repair basarisiz oldu, efendim. "
            f"{Path(diagnosis['file']).name} dosyasini manuel kontrol etmeniz gerekebilir."
        )
        if speak:
            speak(msg)
        return msg

    return "Bilinmeyen islem. Kullanilabilir: fix, diagnose, status"
