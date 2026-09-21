import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
API_CONFIG_PATH  = BASE_DIR / "config" / "api_keys.json"
PROJECTS_DIR     = Path.home() / "Desktop" / "JarvisProjects"
MAX_FIX_ATTEMPTS = 5
MODEL_PLANNER    = "gemini-flash-latest"
MODEL_WRITER     = "gemini-flash-latest"

def _get_api_key() -> str:
    from jarvis.core.secure_config import get_gemini_api_key
    return get_gemini_api_key()


def _get_model(model_name: str):
    """Once yerel Ollama'yi (qwen2.5-coder) dener - Google Gemini kesintilerinde
    bile calisir. Ollama kapaliysa/kurulu degilse otomatik olarak Gemini'ye
    (orijinal davranis) duser."""
    import requests as _requests

    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "qwen2.5-coder:7b"

    class _OllamaResponse:
        def __init__(self, text):
            self.text = text

    class _OllamaWrapper:
        def generate_content(self, contents):
            prompt = contents if isinstance(contents, str) else str(contents)
            resp = _requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return _OllamaResponse(data.get("response", ""))

    # Ollama gercekten calisiyor mu, hizli bir saglik kontrolu (1sn)
    try:
        _requests.get("http://localhost:11434/api/version", timeout=5)
        print("[DevAgent] Yerel Ollama kullaniliyor (Gemini'ye bagimli degil).")
        return _OllamaWrapper()
    except Exception:
        pass

    from google import genai
    from jarvis.actions.resilience import call_with_resilience, ModelFallbackNeeded, AllAttemptsFailed
    _c = genai.Client(api_key=_get_api_key())
    _breaker = _get_gemini_breaker()

    class _W:
        def generate_content(self, contents):
            try:
                return call_with_resilience(
                    lambda: _c.models.generate_content(model=model_name, contents=contents),
                    breaker=_breaker,
                )
            except ModelFallbackNeeded as e:
                print(f"[DevAgent] ⚠️ Model '{model_name}' kullanılamıyor (muhtemelen kaldırılmış): {e}")
                raise
            except AllAttemptsFailed as e:
                print(f"[DevAgent] ❌ Gemini'ye ulaşılamıyor, tüm denemeler başarısız: {e.last_error}")
                raise

    return _W()


_GEMINI_BREAKER = None


def _get_gemini_breaker():
    """Tek, paylasilan bir devre kesici - modul yeniden import edilse bile
    hata sayaci sifirlanmaz (process omru boyunca kalici)."""
    global _GEMINI_BREAKER
    if _GEMINI_BREAKER is None:
        from jarvis.actions.resilience import CircuitBreaker
        _GEMINI_BREAKER = CircuitBreaker(name="gemini-devagent", failure_threshold=3, cooldown_seconds=60)
    return _GEMINI_BREAKER


def _strip_fences(text: str) -> str:
    text = text.strip()
    # Modeller kod bloğundan SONRA sıkça açıklama ekler (örn. "### API anahtarı
    # nasıl alınır"). Sadece bastaki/sondaki tek tırnağı silmek, bu durumda
    # kapanış tırnağını ve arkasındaki Markdown metnini dosyada bırakıp
    # SyntaxError'a yol açıyordu. Bunun yerine, İLK tam kod bloğunu (açılış...
    # kapanış) bulup SADECE onu alıyoruz - öncesi/sonrası ne olursa olsun atılır.
    match = re.search(r"```[a-zA-Z]*\r?\n?(.*?)\r?\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Üçlü tırnak hiç bulunamadıysa (nadir durum), eski davranışa dön.
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _parse_traceback(output: str, project_files: list[str]) -> tuple[str | None, int | None]:

    pattern = re.compile(r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE)
    matches = pattern.findall(output)

    for raw_path, line_str in reversed(matches):
        raw_name = Path(raw_path).name
        for pf in project_files:
            if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                return pf, int(line_str)

    return None, None


def _classify_error(output: str, project_dir: Path | None = None) -> str:

    low = output.lower()

    if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
        # "No module named X" HER ZAMAN eksik harici paket anlamina gelmez -
        # projenin KENDI dosyalarindan biri de olabilir (ornegin utils/helpers.py
        # var ama __init__.py eksik oldugu icin import calismiyor). Boyle
        # durumda pip install denemek bosuna zaman kaybettirir (5 deneme
        # boyunca ayni hatayi tekrar tekrar gorduren tam olarak bu bug'du).
        if project_dir is not None:
            match = re.search(r"No module named ['\"]([a-zA-Z0-9_\.]+)['\"]", output, re.IGNORECASE)
            if match:
                top_level = match.group(1).split(".")[0]
                if (project_dir / top_level).exists() or (project_dir / f"{top_level}.py").exists():
                    return "local_import_error"
        return "dependency_error"

    if "syntaxerror" in low or "invalid syntax" in low:
        return "syntax_error"
    
    if "cannot import" in low or "importerror" in low:
        return "import_error"

    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
    )):
        return "runtime_error"

    return "none"


def _has_error(output: str, run_command: str) -> bool:
    
    low = output.lower()

    if "timed out" in low:
        return False

    if not output.strip():
        return False

    error_type = _classify_error(output)
    return error_type != "none"

class RateLimitError(Exception):
    pass


def _plan_project(description: str, language: str) -> dict:
    model = _get_model(MODEL_PLANNER)

    prompt = f"""You are a senior software architect. Create a minimal, complete file plan for this project.

Language: {language}
Description: {description}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "jarvis.core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": ["requests"]
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports (dot-notation, e.g. "utils.helpers").
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py", not absolute paths).
6. Standard library modules (os, sys, json, etc.) do NOT go in "dependencies".

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}") from e
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e)) from e
        raise

def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    model = _get_model(MODEL_WRITER)

    file_path = file_info["path"]
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep_dotted in file_imports:
        dep_path = dep_dotted.replace(".", "/") + ".py"
        if dep_path in already_written:
            code_snippet = already_written[dep_path][:2000]
            dependency_context += f"\n\n--- {dep_path} (you must import from this) ---\n{code_snippet}"

    lang_rules = ""
    if language.lower() == "python":
        lang_rules = """
Python-specific rules:
- Use type hints for all function signatures.
- Add docstrings for all public functions and classes.
- Use if __name__ == "__main__": guard in the entry point.
- For relative imports within the project, use: from utils.helpers import foo  (match the project structure exactly).
- Do NOT use implicit relative imports (from . import ...) unless it's a proper package with __init__.py.
- If this is a package subdirectory, create __init__.py files where needed."""
    elif language.lower() in ("javascript", "typescript", "js", "ts"):
        lang_rules = """
JS/TS-specific rules:
- Use ES modules (import/export), not CommonJS (require).
- Add JSDoc comments for all exported functions.
- Handle promise rejections with try/catch in async functions."""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real project.

Project goal: {project_description}

Complete project file structure (in dependency order):
{file_list}

{f"Dependencies this file must import from other project files:{dependency_context}" if dependency_context else ""}

Your task: Write the complete, working code for: {file_path}
Purpose of this file: {file_desc}
{f"This file imports from: {', '.join(file_imports)}" if file_imports else "This file has no project-internal imports."}

{lang_rules}

General rules:
- Output ONLY raw code. Absolutely no explanation, no markdown, no triple backticks.
- Write COMPLETE, RUNNABLE code — no placeholders, no "# TODO", no "pass" stubs.
- Every import must either be from the standard library, listed dependencies, or the project files shown above.
- Match import paths EXACTLY to the file paths in the project structure (e.g. if file is "utils/helpers.py", import as "from utils.helpers import ...").
- Use proper error handling (try/except) where I/O or network calls are made.
- The code must work correctly when the project entry point is run from the project root directory.

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        # Yazmadan ONCE sozdizimi kontrolu (sadece Python icin): hatali kod
        # hic diske yazilmasin, mumkunse hatayi modele gosterip bir kez
        # daha denensin.
        if file_path.endswith(".py"):
            try:
                compile(code, file_path, "exec")
            except SyntaxError as syntax_err:
                print(f"[DevAgent] ⚠️ Sözdizimi hatası tespit edildi ({file_path}), düzeltme deneniyor...")
                fix_prompt = (
                    f"{prompt}\n\n"
                    f"NOT: Bir önceki denemen şu sözdizimi hatasını içeriyordu: "
                    f"satır {syntax_err.lineno}: {syntax_err.msg}. "
                    f"Bu hatayı düzelterek TAM ve GEÇERLİ kodu tekrar yaz."
                )
                retry_response = model.generate_content(fix_prompt)
                retry_code = _strip_fences(retry_response.text)
                try:
                    compile(retry_code, file_path, "exec")
                    code = retry_code
                    print(f"[DevAgent] ✅ Düzeltme başarılı: {file_path}")
                except SyntaxError as second_err:
                    print(f"[DevAgent] ❌ İkinci denemede de sözdizimi hatası var "
                          f"({file_path}, satır {second_err.lineno}): {second_err.msg}. "
                          f"Yine de yazılıyor, sonraki adımda (_fix_files) düzeltilmeye çalışılacak.")

        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")

        print(f"[DevAgent] ✅ Written: {file_path} ({len(code)} chars)")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e)) from e
        raise

def _install_dependencies(dependencies: list[str], project_dir: Path) -> str:
    if not dependencies:
        return "No external dependencies."

    to_install = []
    for dep in dependencies:
        pkg_name = re.split(r"[>=<!]", dep)[0].strip()
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            to_install.append(dep)
        else:
            print(f"[DevAgent] ✓ Already installed: {pkg_name}")

    if not to_install:
        return f"All dependencies already installed: {', '.join(dependencies)}"

    print(f"[DevAgent] 📦 Installing: {to_install}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + to_install,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, cwd=str(project_dir)
        )
        if result.returncode == 0:
            return f"Installed: {', '.join(to_install)}"
        return f"Install warning (non-fatal): {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "Dependency install timed out (non-fatal)."
    except Exception as e:
        return f"Install error (non-fatal): {e}"

def _open_vscode(project_dir: Path) -> bool:
    vscode_candidates = [
        "code",
        rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
    ]
    for cmd in vscode_candidates:
        try:
            launch = [cmd, str(project_dir)]
            # Windows .cmd launcherları shell=True olmadan cmd.exe üzerinden,
            # sabit ve kullanıcı girdisi içermeyen argümanlarla çalıştırılır.
            if os.name == "nt" and cmd.lower().endswith(".cmd"):
                launch = ["cmd.exe", "/d", "/c", cmd, str(project_dir)]
            subprocess.Popen(
                launch,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.5)
            print(f"[DevAgent] 💻 VSCode opened: {project_dir}")
            return True
        except Exception:
            continue
    return False

def _run_project(run_command: str, project_dir: Path, timeout: int = 30) -> str:
    print(f"[DevAgent] 🚀 Running: {run_command}")
    try:
        parts = run_command.split()
        if parts[0].lower() == "python":
            parts[0] = sys.executable

        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout,
            cwd=str(project_dir)
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        combined_parts = []
        if stdout:
            combined_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            combined_parts.append(f"STDERR:\n{stderr}")

        return "\n\n".join(combined_parts) if combined_parts else "Ran with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s — long-running app (server/GUI) is likely working."
    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"

def _try_fix_local_import(error_output: str, project_dir: Path) -> bool:
    """'No module named X' hatasi, X projenin KENDI klasoru/dosyasiysa,
    en yaygin sebep eksik __init__.py'dir. Projedeki her alt klasore
    (varsa) bunu ekler - guvenli, tekrar calistirilabilir bir islem."""
    added_any = False
    for sub in project_dir.rglob("*"):
        if sub.is_dir() and not sub.name.startswith((".", "__")):
            init_file = sub / "__init__.py"
            if not init_file.exists():
                # Klasorde en az bir .py dosyasi varsa paket say
                if any(sub.glob("*.py")):
                    init_file.write_text("", encoding="utf-8")
                    added_any = True
    if added_any:
        print("[DevAgent] 🔧 Eksik __init__.py dosyaları eklendi (yerel modül içe aktarma düzeltmesi).")
    return added_any


def _try_auto_install(error_output: str, project_dir: Path) -> bool:
    """ModuleNotFoundError varsa eksik paketi otomatik kurmaya çalışır."""
    pattern = re.compile(
        r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
    )
    match = pattern.search(error_output)
    if not match:
        return False

    pkg = match.group(1).replace("_", "-").split(".")[0]
    print(f"[DevAgent] 🔧 Auto-installing missing package: {pkg}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=60, cwd=str(project_dir)
        )
        return result.returncode == 0
    except Exception:
        return False

def _search_error_context(error_output: str) -> str:
    """Hata mesaji icin internette gercek coz umler arar - tipki bir
    gelistiricinin hata mesajini Google'da aramasi gibi. Basarisiz
    olursa sessizce bos dondurur (arama olmadan da calismaya devam eder)."""
    try:
        from jarvis.actions.web_search import _ddg_search
        # Hata ciktisinin SON satiri genelde en spesifik/aranabilir kismidir
        # (ornek: "ModuleNotFoundError: No module named 'x'")
        lines = [ln.strip() for ln in error_output.strip().splitlines() if ln.strip()]
        query = lines[-1][:150] if lines else error_output[:150]
        results = _ddg_search(f"python {query}", max_results=3)
        if not results:
            return ""
        formatted = "\n".join(
            f"- {r['title']}: {r['snippet'][:200]}" for r in results if r.get("snippet")
        )
        return f"\n\nWeb search results for this error (for reference, verify before applying):\n{formatted}\n" if formatted else ""
    except Exception:
        return ""


def _fix_files(
    error_output: str,
    project_description: str,
    all_files: list[dict],
    file_codes: dict[str, str],
    language: str,
    project_dir: Path,
    entry_point: str,
) -> dict[str, str]:

    model = _get_model(MODEL_PLANNER)

    error_file, error_line = _parse_traceback(error_output, list(file_codes.keys()))
    error_type = _classify_error(error_output)
    web_context = _search_error_context(error_output)

    files_to_fix: list[str] = []

    if error_file:
        files_to_fix.append(error_file)
        if error_type == "import_error":
            for fi in all_files:
                if error_file.replace("/", ".").replace(".py", "") in fi.get("imports", []):
                    p = fi["path"]
                    if p not in files_to_fix:
                        files_to_fix.append(p)
    else:
        files_to_fix.append(entry_point)

    updated_codes: dict[str, str] = {}

    for fix_path in files_to_fix:
        current_code = file_codes.get(fix_path, "")

        other_ctx = ""
        for fp, code in file_codes.items():
            if fp != fix_path and code:
                snippet = code[:1500] + ("..." if len(code) > 1500 else "")
                other_ctx += f"\n--- {fp} ---\n{snippet}\n"

        line_hint = f"\nError appears to be near line {error_line} in this file." if (
            error_line and fix_path == error_file
        ) else ""

        prompt = f"""You are an expert {language} debugger. Fix the broken file below.

Project goal: {project_description}

All project files:
{chr(10).join(f"  - {f['path']}: {f.get('description', '')}" for f in all_files)}

Other files for context (read-only — fix only the target file):
{other_ctx[:3500]}

File to fix: {fix_path}{line_hint}
Error type: {error_type}

Error output:
{error_output[:2500]}
{web_context}
Current (broken) code:
{current_code}

Rules:
- Output ONLY the complete fixed code. No explanation, no markdown, no backticks.
- Fix ALL errors visible in the error output.
- Keep all existing correct logic — do not remove working features.
- Ensure import paths match the actual project file structure exactly.
- Do NOT introduce new bugs or remove error handling.

Fixed code for {fix_path}:"""

        try:
            response = model.generate_content(prompt)
            fixed = _strip_fences(response.text)

            full_path = project_dir / fix_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                from datetime import datetime as _dt
                stamp  = _dt.now().strftime("%Y%m%d-%H%M%S")
                backup = full_path.with_name(f"{full_path.stem}.{stamp}.bak{full_path.suffix}")
                backup.write_text(full_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            full_path.write_text(fixed, encoding="utf-8")

            updated_codes[fix_path] = fixed
            print(f"[DevAgent] 🔧 Fixed: {fix_path}")

        except Exception as e:
            if _is_rate_limit(e):
                raise RateLimitError(str(e)) from e
            print(f"[DevAgent] ⚠️ Could not fix {fix_path}: {e}")

    return updated_codes

def _build_project(
    description: str,
    language: str,
    project_name: str,
    timeout: int,
    speak=None,
    player=None,
) -> str:

    def log(msg: str):
        print(f"[DevAgent] {msg}")
        if player:
            player.write_log(f"[DevAgent] {msg}")

    log("Planning project structure...")
    try:
        plan = _plan_project(description, language)
    except RateLimitError:
        msg = "Rate limit reached, sir. Please try again in a moment."
        if speak: speak(msg)
        return msg
    except ValueError as e:
        msg = f"Planning failed: {e}"
        if speak: speak(msg)
        return msg

    proj_name    = project_name or plan.get("project_name", "jarvis_project")
    proj_name    = re.sub(r"[^\w\-]", "_", proj_name)
    project_dir  = PROJECTS_DIR / proj_name
    project_dir.mkdir(parents=True, exist_ok=True)

    files        = plan.get("files", [])
    entry_point  = plan.get("entry_point", "main.py")
    run_command  = plan.get("run_command", f"python {entry_point}")
    dependencies = plan.get("dependencies", [])

    log(f"Project: {proj_name} | Files: {len(files)} | Entry: {entry_point}")

    def _dep_sort_key(fi: dict) -> int:
        return len(fi.get("imports", []))

    sorted_files = sorted(files, key=_dep_sort_key)

    file_codes: dict[str, str] = {}

    for file_info in sorted_files:
        file_path = file_info.get("path", "")
        if not file_path:
            continue

        log(f"Writing {file_path}...")
        for attempt in range(2):
            try:
                code = _write_file(
                    file_info=file_info,
                    project_description=description,
                    all_files=files,
                    language=language,
                    project_dir=project_dir,
                    already_written=file_codes,
                )
                file_codes[file_path] = code
                time.sleep(0.4)
                break
            except RateLimitError:
                if attempt == 0:
                    log("Rate limit — waiting 20s...")
                    time.sleep(20)
                else:
                    log(f"Rate limit retry failed for {file_path}, skipping.")
            except Exception as e:
                log(f"Failed to write {file_path}: {e}")
                break

    if not file_codes:
        msg = "I could not write any project files, sir."
        if speak: speak(msg)
        return msg

    if dependencies:
        install_result = _install_dependencies(dependencies, project_dir)
        log(install_result)

    _open_vscode(project_dir)

    last_output   = ""
    auto_installs = 0  

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")
        last_output = _run_project(run_command, project_dir, timeout)
        log(f"Output preview: {last_output[:150]}")

        if not _has_error(last_output, run_command):
            msg = (
                f"Project '{proj_name}' is working, sir. "
                f"Built in {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Saved to: {project_dir}"
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_type = _classify_error(last_output, project_dir)

        if error_type == "local_import_error":
            fixed = _try_fix_local_import(last_output, project_dir)
            if fixed:
                log("Yerel modül içe aktarma sorunu düzeltildi (eksik __init__.py), tekrar deneniyor...")
                time.sleep(1)
                continue

        if error_type == "dependency_error" and auto_installs < 3:
            installed = _try_auto_install(last_output, project_dir)
            if installed:
                auto_installs += 1
                log("Missing dependency installed, retrying...")
                time.sleep(1)
                continue

        log(f"Fixing errors (type: {error_type})...")
        try:
            updated = _fix_files(
                error_output=last_output,
                project_description=description,
                all_files=files,
                file_codes=file_codes,
                language=language,
                project_dir=project_dir,
                entry_point=entry_point,
            )
            file_codes.update(updated)
            time.sleep(1)
        except RateLimitError:
            msg = "Rate limit reached during fix. Project saved, check it manually in VSCode."
            if speak: speak(msg)
            return msg
        except Exception as e:
            log(f"Fix step failed: {e}")

    msg = (
        f"I couldn't fully fix '{proj_name}' after {MAX_FIX_ATTEMPTS} attempts, sir. "
        f"Project is saved at {project_dir} — open it in VSCode and check manually."
    )
    if speak: speak(msg)
    return f"{msg}\n\nLast error:\n{last_output[:600]}"


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python").strip()
    project_name = p.get("project_name", "").strip()
    timeout      = int(p.get("timeout", 30))

    if not description:
        return "Please describe the project you want me to build, sir."

    return _build_project(
        description  = description,
        language     = language,
        project_name = project_name,
        timeout      = timeout,
        speak        = speak,
        player       = player,
    )
