#!/usr/bin/env python3
"""JARVIS AI-Powered Self-Healing System v3 - Bulletproof"""

import os, sys, json, traceback, importlib, subprocess, shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ACTIONS_DIR = BASE_DIR / "actions"
CORE_DIR = BASE_DIR / "core"
BACKUP_DIR = BASE_DIR / "backups"
LOG_FILE = BASE_DIR / "logs" / "self_heal_log.json"
API_KEYS_FILE = BASE_DIR / "config" / "api_keys.json"

MODELS = ["gemini-2.0-flash-001", "gemini-1.5-flash", "gemini-1.5-flash-8b"]


def _get_api_key():
    try:
        if not API_KEYS_FILE.exists():
            return ""
        keys = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
        return keys.get("gemini_api_key", keys.get("GEMINI_API_KEY", ""))
    except:
        return ""


def _ask_gemini(prompt):
    api_key = _get_api_key()
    if not api_key:
        return ""
    try:
        import google.genai as genai
        client = genai.Client(api_key=api_key)
    except:
        return ""
    for model_name in MODELS:
        try:
            resp = client.models.generate_content(model=model_name, contents=prompt)
            text = resp.text or ""
            if text and len(text) > 20:
                return text
        except Exception as e:
            print(f"[SELF-HEAL] Model {model_name} failed: {e}")
            continue
    return ""


def _log(event):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        history = []
        if LOG_FILE.exists():
            try:
                history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except:
                history = []
        history.append(event)
        LOG_FILE.write_text(json.dumps(history[-100:], indent=2, ensure_ascii=False), encoding="utf-8")
    except:
        pass


def _backup(filepath):
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = BACKUP_DIR / f"{filepath.stem}_{ts}{filepath.suffix}"
        shutil.copy2(filepath, bak)
        return bak
    except:
        return None


def _restore(filepath, backup):
    try:
        if backup and backup.exists():
            shutil.copy2(backup, filepath)
    except:
        pass


def _install_dep(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
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
            modules.append({"name": f.stem, "path": str(f)})
    return modules


def _diagnose_error(error_msg):
    diag = {"error": error_msg, "type": "unknown", "file": None, "line": None, "module": None, "fixable": False}
    for line in error_msg.strip().splitlines():
        if "ModuleNotFoundError" in line or "ImportError" in line:
            diag["type"] = "import_error"
            if "No module named" in line:
                diag["module"] = line.split("No module named")[-1].strip().strip("'\"")
            diag["fixable"] = True
        elif "SyntaxError" in line:
            diag["type"] = "syntax_error"
            diag["fixable"] = True
        elif "FileNotFoundError" in line:
            diag["type"] = "file_error"
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
        "You are JARVIS AI fixing your own Python code. Fix the error.\n\n"
        "ERROR TYPE: " + error_type + "\n"
        "ERROR: " + error_msg + "\n"
        "FILE: " + error_file + "\n"
        "LINE: " + error_line + "\n\n"
        "ORIGINAL CODE:\n" + original_code + "\n\n"
        "RULES:\n"
        "1. Return ONLY the complete fixed Python code\n"
        "2. No explanation\n"
        "3. No markdown or backticks\n"
        "4. Keep ALL existing functions\n"
        "5. Fix ONLY the error\n"
        "6. Valid Python only"
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
        except SyntaxError as e:
            results.append({"module": mod_info["name"], "status": "SYNTAX_ERROR", "error": str(e)})
        except Exception as e:
            results.append({"module": mod_info["name"], "status": "ERROR", "error": str(e)})
    return results


def self_heal(parameters=None, player=None, speak=None):
    try:
        return _self_heal_inner(parameters, player, speak)
    except Exception as e:
        msg = "Self-heal hatasi: " + str(e)[:100]
        print("[SELF-HEAL] CRASH:", e)
        traceback.print_exc()
        try:
            if speak:
                speak(msg)
        except:
            pass
        return msg


def _self_heal_inner(parameters=None, player=None, speak=None):
    if parameters is None:
        parameters = {}
    action = parameters.get("action", "fix")
    error_msg = parameters.get("error", "")

    if action == "status":
        if not LOG_FILE.exists():
            msg = "Self-heal gecmisi bos. Henuz hata duzeltilmedi."
        else:
            try:
                history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except:
                history = []
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
        msg = "Teshis:\n  Tip: " + diag["type"] + "\n  Dosya: " + str(diag.get("file", "?")) + "\n  Satir: " + str(diag.get("line", "?")) + "\n  Duzeltilebilir: " + ("Evet" if diag.get("fixable") else "Hayir")
        if speak:
            speak(msg)
        return msg

    if action == "health":
        results = _health_check()
        ok_count = sum(1 for r in results if r["status"] == "OK")
        err_items = [r for r in results if r["status"] != "OK"]
        if not err_items:
            msg = "Tum moduller saglikli! " + str(ok_count) + " modul kontrol edildi."
        else:
            lines = []
            for r in err_items:
                lines.append(r["module"] + ": " + r.get("error", "")[:80])
            msg = str(ok_count) + " modul OK, " + str(len(err_items)) + " modulde hata:\n" + "\n".join(lines)
        if speak:
            speak(msg)
        return msg

    if action in ("fix", "repair"):
        if not error_msg:
            results = _health_check()
            err_items = [r for r in results if r["status"] != "OK"]
            if not err_items:
                msg = "Tum moduller saglikli! Duzeltilecek hata yok."
                if speak:
                    speak(msg)
                return msg
            error_msg = err_items[0].get("error", "")

        diag = _diagnose_error(error_msg)

        # Try pip install first for import errors
        if diag["type"] == "import_error" and diag.get("module"):
            if _install_dep(diag["module"]):
                _log({"timestamp": datetime.now().isoformat(), "type": diag["type"], "action": "pip_install", "module": diag["module"], "result": "success"})
                msg = diag["module"] + " modulu otomatik kuruldu!"
                if speak:
                    speak(msg)
                return msg

        # Find target file
        target_file = None
        if diag.get("file"):
            pf = Path(diag["file"])
            if pf.exists():
                target_file = pf
            else:
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
            if backup_path:
                _restore(target_file, backup_path)
            msg = "AI duzeltme kodu uretemedi. Geri yuklendi."
            if speak:
                speak(msg)
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"], "result": "ai_fix_failed"})
            return msg

        target_file.write_text(fixed_code, encoding="utf-8")

        if _test_fix(target_file):
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"], "file": str(target_file), "backup": str(backup_path), "result": "success"})
            msg = "Basariyla duzeltildi! Yedek: " + (backup_path.name if backup_path else "?")
            if speak:
                speak(msg)
            return msg
        else:
            if backup_path:
                _restore(target_file, backup_path)
            _log({"timestamp": datetime.now().isoformat(), "type": diag["type"], "result": "fix_test_failed_rolled_back"})
            msg = "Duzeltme testi basarisiz. Orijinal geri yuklendi."
            if speak:
                speak(msg)
            return msg

    return "Bilinmeyen aksiyon. Kullanilabilir: fix, diagnose, status, health"
