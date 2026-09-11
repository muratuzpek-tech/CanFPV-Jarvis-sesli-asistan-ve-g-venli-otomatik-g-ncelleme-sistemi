import pathlib
content = r'''#!/usr/bin/env python3
"""JARVIS AI-Powered Self-Healing and Auto-Update System v2"""

import os, sys, json, traceback, importlib, subprocess, shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ACTIONS_DIR = BASE_DIR / "actions"
CORE_DIR = BASE_DIR / "core"
BACKUP_DIR = BASE_DIR / "backups"
LOG_FILE = BASE_DIR / "logs" / "self_heal_log.json"
API_KEYS_FILE = BASE_DIR / "config" / "api_keys.json"


def _get_gemini_client():
    try:
        import google.genai as genai
        if not API_KEYS_FILE.exists():
            return None
        keys = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
        api_key = keys.get("gemini_api_key", keys.get("GEMINI_API_KEY", ""))
        if not api_key:
            return None
        return genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[SELF-HEAL] Gemini client error: {e}")
        return None


def _ask_gemini(prompt):
    client = _get_gemini_client()
    if not client:
        return ""
    try:
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return resp.text or ""
    except Exception as e:
        print(f"[SELF-HEAL] Gemini API error: {e}")
        return ""


def _log(event):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if LOG_FILE.exists():
        try:
            history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except:
            history = []
    history.append(event)
    LOG_FILE.write_text(json.dumps(history[-100:], indent=2, ensure_ascii=False), encoding="utf-8")


def _backup(filepath):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = BACKUP_DIR / f"{filepath.stem}_{ts}{filepath.suffix}"
    shutil.copy2(filepath, bak)
    return bak


def _restore(filepath, backup):
    shutil.copy2(backup, filepath)


def _install_dep(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False


def _scan_modules():
    modules = []
    for d in [ACTIONS_DIR, CORE_DIR]:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if f.name.startswith("__"):
                continue
            modules.append({"name": f.stem, "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    return modules


def _diagnose_error(error_msg):
    diag = {"error": error_msg, "timestamp": datetime.now().isoformat(),
        "type": "unknown", "file": None, "line": None, "module": None, "fixable": False}
    for line in error_msg.strip().splitlines():
        if "ModuleNotFoundError" in line or "ImportError" in line:
            diag["type"] = "import_error"
            if "No module named" in line:
                diag["module"] = line.split("No module named")[-1].strip().strip("'\"")
            diag["fixable"] = True
        elif "FileNotFoundError" in line:
            diag["type"] = "file_error"
            diag["fixable"] = True
        elif "SyntaxError" in line:
            diag["type"] = "syntax_error"
            diag["fixable"] = True
        elif "Error" in line:
            diag["type"] = "runtime_error"
            diag["fixable"] = True
        if 'File "' in line:
            start = line.find('"') + 1
            end = line.find('"', start)
            diag["file"] = line[start:end]
            if ", line " in line:
                try:
                    diag["line"] = int(line.split(", line ")[-1].split(",")[0].strip())
                except:
                    pass
    return diag


def _ai_fix(diag, original_code):
    error_type = diag.get("type", "unknown")
    error_file = diag.get("file", "unknown")
    error_line = str(diag.get("line", "unknown"))
    error_msg = diag.get("error", "")
    prompt = (
        "You are JARVIS AI fixing your own code. Fix the error.\n\n"
        "ERROR TYPE: " + error_type + "\n"
        "ERROR MESSAGE: " + error_msg + "\n"
        "FILE: " + error_file + "\n"
        "LINE: " + error_line + "\n\n"
        "ORIGINAL CODE:\n`python\n" + original_code + "\n`\n\n"
        "RULES:\n"
        "1. Return ONLY the complete fixed Python code, nothing else\n"
        "2. No explanation, no markdown\n"
        "3. No triple backtick wrapping\n"
        "4. Keep ALL existing functions intact\n"
        "5. Fix ONLY the error\n"
        "6. Make sure code is valid Python"
    )
    fix = _ask_gemini(prompt)
    for prefix in ["`python", "`"]:
        if fix.startswith(prefix):
            fix = fix[len(prefix):]
    if fix.endswith("`"):
        fix = fix[:-3]
    return fix.strip()


def _test_fix(filepath):
    try:
        spec = importlib.util.spec_from_file_location(filepath.stem, str(filepath))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return True
    except SyntaxError:
        return False
    except:
        return True


def _health_check():
    results = []
    for mod_info in _scan_modules():
        filepath = Path(mod_info["path"])
        try:
            spec = importlib.util.spec_from_file_location(filepath.stem, str(filepath))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            results.append({"module": mod_info["name"], "status": "OK"})
        except Exception as e:
            results.append({"module": mod_info["name"], "status": "ERROR", "error": str(e)})
    return results


def self_heal(parameters=None, player=None, speak=None):
    if parameters is None:
        parameters = {}
    action = parameters.get("action", "fix")
    error_msg = parameters.get("error", "")

    if action == "status":
        if not LOG_FILE.exists():
            msg = "Self-heal gecmisi bos. Henuz hata duzeltilmedi."
        else:
            history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            if not history:
                msg = "Self-heal gecmisi bos."
            else:
                items = []
                for h in history[-10:]:
                    ts = h.get("timestamp", "?")
                    tp = h.get("type", "?")
                    rs = h.get("result", "?")
                    items.append(ts + " | " + tp + " | " + rs)
                msg = "Son " + str(len(items)) + " self-heal kaydi:\n" + "\n".join(items)
        if speak:
            speak(msg)
        return msg

    if action == "diagnose":
        if not error_msg:
            msg = "Diyagnostik icin hata mesaji gerekiyor."
            if speak:
                speak(msg)
            return msg
        diag = _diagnose_error(error_msg)
        tp = diag.get("type", "?")
        fl = diag.get("file", "?")
        ln = str(diag.get("line", "?"))
        fx = "Evet" if diag.get("fixable") else "Hayir"
        msg = "Teshis sonucu:\n  Tip: " + tp + "\n  Dosya: " + fl + "\n  Satir: " + ln + "\n  Duzeltilebilir: " + fx
        if speak:
            speak(msg)
        return msg

    if action == "health":
        results = _health_check()
        ok_count = sum(1 for r in results if r["status"] == "OK")
        err_count = sum(1 for r in results if r["status"] == "ERROR")
        errors = [r for r in results if r["status"] == "ERROR"]
        if err_count == 0:
            msg = "Tum moduller saglikli! " + str(ok_count) + " modul kontrol edildi."
        else:
            lines = []
            for r in errors:
                lines.append(r["module"] + ": " + r.get("error", "")[:80])
            msg = str(ok_count) + " modul OK, " + str(err_count) + " modulde hata:\n" + "\n".join(lines)
        if speak:
            speak(msg)
        return msg

    if action in ("fix", "repair"):
        if not error_msg:
            results = _health_check()
            errors = [r for r in results if r["status"] == "ERROR"]
            if not errors:
                msg = "Tum moduller saglikli! Duzeltilecek hata yok."
                if speak:
                    speak(msg)
                return msg
            error_msg = errors[0].get("error", "")

        diag = _diagnose_error(error_msg)

        if diag["type"] == "import_error" and diag.get("module"):
            if _install_dep(diag["module"]):
                _log({"timestamp": datetime.now().isoformat(), "type": diag["type"],
                    "action": "pip_install", "module": diag["module"], "result": "success"})
                msg = diag["module"] + " modulu otomatik kuruldu!"
                if speak:
                    speak(msg)
                return msg

        target_file = None
        if diag.get("file") and Path(diag["file"]).exists():
            target_file = Path(diag["file"])
        elif diag.get("file"):
            candidate = BASE_DIR / diag["file"]
            if candidate.exists():
                target_file = candidate

        if not target_file or not target_file.exists():
            msg = "Hata dosyasi bulunamadi: " + str(diag.get("file", "?"))
            if speak:
                speak(msg)
            return msg

        original_code = target_file.read_text(encoding="utf-8")
        backup_path = _backup(target_file)

        if speak:
            speak(target_file.name + " dosyasinda hata tespit edildi. AI ile duzeltme baslatiliyor...")

        fixed_code = _ai_fix(diag, original_code)

        if not fixed_code or len(fixed_code) < 20:
            _restore(target_file, backup_path)
            msg = "AI duzeltme kodu uretemedi. Geri yuklendi."
            if speak:
                speak(msg)
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"], "result": "ai_fix_failed"})
            return msg

        target_file.write_text(fixed_code, encoding="utf-8")

        if _test_fix(target_file):
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"],
                "file": str(target_file), "backup": str(backup_path), "result": "success"})
            msg = "Basariyla duzeltildi! Yedek: " + backup_path.name
            if speak:
                speak(msg)
            return msg
        else:
            _restore(target_file, backup_path)
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"],
                "file": str(target_file), "backup": str(backup_path), "result": "fix_test_failed_rolled_back"})
            msg = "Duzeltme testi basarisiz. Orijinal geri yuklendi."
            if speak:
                speak(msg)
            return msg

    return "Bilinmeyen aksiyon. Kullanilabilir: fix, diagnose, status, health"
'''
outpath = pathlib.Path(r'C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3\actions\self_heal.py')
outpath.write_text(content, encoding='utf-8')
print('self_heal.py CREATED!')
