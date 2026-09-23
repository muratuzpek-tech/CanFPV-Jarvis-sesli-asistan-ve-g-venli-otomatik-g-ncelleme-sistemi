import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import typing
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

# Onay bekleyen (henuz baslatilmamis) dev_agent istekleri - file_controller.py'deki
# confirm_code deseniyle ayni mantik: ilk cagri hicbir sey kurmaz/calistirmaz, sadece
# bir kod doner; kullanici acikca onaylayip ayni kodla tekrar cagirilana kadar pip
# install / uretilen kodu calistirma adimlarina gecilmez.
_pending_dev_agent: dict[str, dict] = {}


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

    if "cannot import name" in low:
        # Paket EKSIK degil - modul var ama beklenen isim (sinif/fonksiyon)
        # onun icinde tanimli degil. pip install bunu asla cozemez, bu yuzden
        # "no module named" kontrolunden ONCE, ayri bir tur olarak yakalanmali.
        # (Asagidaki kontrol "importerror" gecen HER SEYI yakaladigi icin, bu
        # satir olmadan bu dal asla calismazdi.)
        return "import_error"

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
  "dependencies": ["requests"],
  "shared_data_contracts": [
    "Describe here any data structure passed BETWEEN files that don't necessarily import each other directly (e.g. a dict/object built in one file and consumed in another via a function argument, not an import). Example: 'An expense is a dict with keys: amount (float), category (str), date (str, YYYY-MM-DD) - used identically by the GUI, the database layer, and any chart/report code.'"
  ],
  "expected_outputs": [
    {{"path": "database.db", "description": "What a CORRECT result looks like inside this file after the app has genuinely worked (e.g. 'contains one row per scraped URL, with a non-empty title and paragraph')."}}
  ]
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports (dot-notation, e.g. "utils.helpers").
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py", not absolute paths).
6. Standard library modules (os, sys, json, etc.) do NOT go in "dependencies".
7. CRITICAL for correctness: if two or more files exchange a data structure (a dict, a class instance, a tuple shape) — even files that never import each other, because the data actually flows through a third file like main.py — describe its EXACT shape ONCE in "shared_data_contracts" (field names, types, whether it's a dict or a specific class). Every file that touches this data MUST use the identical shape. This is the most common source of real bugs: e.g. one file builds {{"amount": ..., "category": ...}} while another expects an object with .amount/.category attributes.
8. If running the entry point is supposed to durably create or update a file (a database, a report, an exported document, a log, a generated image, etc.), list each such file's relative path in "expected_outputs" with a one-line description of what a CORRECT result looks like inside it. Leave this list EMPTY only for purely interactive/display-only programs that persist nothing (e.g. a calculator, a GUI that only shows numbers on screen). This is critical: a program can run to completion with NO Python error while silently producing nothing real (a network call that fails silently, a thread that never runs, wrong file path) — "expected_outputs" is what lets that be caught instead of wrongly reported as a success.

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

def _safe_project_path(project_dir: Path, file_path: str) -> "Path | None":
    """DUZELTME (denetim bulgusu F-02): planlayici/duzeltme modelinin urettigi
    GORECELI olmasi beklenen bir dosya yolunu, proje kokunun (project_dir)
    KESINLIKLE disina cikamayacak sekilde dogrular. Mutlak yollar (ör.
    Windows'ta "C:\\..." ya da Linux'ta "/etc/...") VE '..' ile disari tasan
    gorece yollar REDDEDILIR (None doner, HICBIR SEY diske yazilmaz).

    GERCEK RISK: model plani {"path": "../../outside.py"} ya da mutlak bir
    yol donebilirdi; eski kod `project_dir / file_path` ile dogrudan
    birlestirip relative_to() kontrolu YAPMIYORDU."""
    try:
        candidate = (project_dir / file_path).resolve()
        root = project_dir.resolve()
        candidate.relative_to(root)
        return candidate
    except (ValueError, OSError):
        return None


def _check_expected_outputs(project_dir: Path, expected_outputs: list, run_started_at: float) -> list[str]:
    """Plan'da bildirilen "expected_outputs" dosyalarinin, projenin bu
    calistirilmasi SIRASINDA gercekten olusup/guncellenip guncellenmedigini
    kontrol eder. Bos liste = sorun yok.

    GERCEK MOTIVASYON: 2026-09-23'te canli bir dev_agent testinde
    (web_scraper projesi) program HICBIR Python hatasi vermeden calisip
    "Scraping completed" yazdi, ama gercekte veritabanina TEK BIR satir bile
    yazilmamisti - once bir thread-kilitlenmesi (ThreadPoolExecutor'i "with"
    ile kullanmak mainloop()'un hic baslamamasina yol aciyordu), sonra da
    Wikipedia'nin varsayilan User-Agent'i 403 ile reddetmesi yuzunden. Ikisi
    de klasik bir Python traceback'i URETMEDI, bu yuzden _has_error()/
    _classify_error() bu hatalarin IKISINI de goremezdi - dev_agent, hicbir
    sey uretmemis bir programi "calisiyor, efendim" diye rapor ediyordu.
    Bu fonksiyon, "cokmedi" ile "gercekten dogru calisti"nin AYNI SEY
    OLMADIGINI" dogrulayan somut bir kontrol saglar."""
    problems: list[str] = []
    for item in expected_outputs or []:
        rel_path = item.get("path") if isinstance(item, dict) else str(item)
        if not rel_path:
            continue
        full_path = _safe_project_path(project_dir, rel_path)
        if full_path is None:
            continue
        if not full_path.is_file():
            problems.append(f"'{rel_path}' was never created.")
            continue
        try:
            stat = full_path.stat()
        except OSError:
            continue
        if stat.st_mtime < run_started_at - 2:
            problems.append(f"'{rel_path}' exists but was NOT updated during this run (stale - from before, or never actually touched now).")
        elif stat.st_size == 0:
            problems.append(f"'{rel_path}' was created/updated during this run but is completely empty (0 bytes).")
    return problems


def _format_output_problem_message(run_output: str, problems: list[str]) -> str:
    """"Sessiz basarisizlik" (program cokmedi ama soz verilen ciktiyi
    uretmedi) durumunu, _fix_files'a (LLM tabanli genel duzeltmeye) gercekten
    yardimci olacak somut bir teshis mesajina cevirir. Asagidaki olasi
    nedenler, 2026-09-23'teki canli hata avinda GERCEKTEN karsilasilan
    sinifllardir - varsayimsal degildir."""
    problems_text = "\n".join(f"  - {p}" for p in problems)
    output_excerpt = run_output[:800].strip() if run_output and run_output.strip() else "(no output at all)"
    return (
        "NO PYTHON ERROR OCCURRED, but the program did not produce the output "
        "it was supposed to produce:\n"
        f"{problems_text}\n\n"
        "This is a SILENT/LOGIC bug, not a crash - look for causes like: a "
        "blocking call (e.g. using ThreadPoolExecutor as a context manager, "
        "which waits for the task to finish before a GUI's mainloop() can "
        "even start) that prevents real work from ever happening; a network "
        "request that fails silently because of a missing/wrong header (many "
        "real sites, including Wikipedia, reject a plain requests.get() with "
        "no User-Agent) with the exception swallowed and never surfaced; "
        "wrong assumptions about an external page/API's structure; writing "
        "to the wrong working directory or file path; or a retry loop that "
        "looks like it retries but never actually re-attempts the failed "
        "operation. Fix the actual logic, not just the error message.\n\n"
        "Actual console output from the run (may look harmless even though "
        "nothing was produced):\n"
        f"{output_excerpt}"
    )


def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
    shared_contracts: str = "",
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

    shared_contracts_block = (
        "Shared data contracts ALL files must follow EXACTLY, even files that do not "
        "import each other (data often flows through a third file like main.py):\n"
        + shared_contracts
    ) if shared_contracts else ""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real project.

Project goal: {project_description}

Complete project file structure (in dependency order):
{file_list}

{f"Dependencies this file must import from other project files:{dependency_context}" if dependency_context else ""}

{shared_contracts_block}

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

        full_path = _safe_project_path(project_dir, file_path)
        if full_path is None:
            raise ValueError(
                f"Güvenlik: planlayıcının verdiği dosya yolu ('{file_path}') proje "
                f"klasörü dışına çıkıyor, reddedildi (path traversal koruması)."
            )
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

# run_command, planlama asamasinda MODELIN URETTIGI bir string - kullanicidan
# gelmiyor ama yine de kor guvenilmemeli. subprocess shell=False ile calistigi
# icin pipe/redirect/glob gibi shell metakarakterleri zaten yorumlanmiyor; bu
# liste, modelin literal argv olarak yikici bir komut ONERMESINE karsi son bir
# savunma katmani (defense in depth) - "gelistirici modu" degil, mevcut
# onay-kapili/sabit-workspace tasarimina eklenen ek bir kontrol.
_DANGEROUS_RUN_PATTERNS = (
    "rm -rf", "rm -fr", "rm -r -f", "rm -f -r",
    "chmod -r 777", "chmod 777 -r", "chmod -r 000",
    "chown -r", "mkfs", "dd if=", "dd of=/dev",
    ":(){", ":() {",  # fork bomb
    "sudo ", "su -", "su root",
    "shutdown", "reboot", "poweroff", "halt",
    "> /dev/sd", "> /dev/nvme",
)


def _is_dangerous_run_command(run_command: str) -> str | None:
    low = " ".join(run_command.lower().split())
    for pattern in _DANGEROUS_RUN_PATTERNS:
        if pattern in low:
            return pattern
    return None


def _run_project(run_command: str, project_dir: Path, timeout: int = 30) -> str:
    print(f"[DevAgent] 🚀 Running: {run_command}")

    danger = _is_dangerous_run_command(run_command)
    if danger:
        print(f"[DevAgent] 🛑 Reddedildi — yıkıcı komut kalıbı tespit edildi: '{danger}'")
        return (
            f"REFUSED: run_command contains a destructive pattern ('{danger}') and was "
            f"NOT executed. This is not a real failure to fix — do not attempt to work "
            f"around it, report it to the user as-is."
        )

    try:
        parts = run_command.split()
        if parts[0].lower() == "python":
            parts[0] = sys.executable

        # NOT: cikti dogrudan PIPE'a degil, gercek bir dosyaya yaziliyor ve
        # surecin sadece KENDI CIKISI (Popen.wait) bekleniyor - subprocess.run(
        # capture_output=True) KULLANMIYORUZ. SEBEP: Windows'ta bazi antivirus/
        # EDR yazilimlari (Norton dahil) yeni baslayan process'lere kendi
        # bilesenini enjekte edip cocuk surecin stdout/stderr PIPE'ina kendi
        # handle'ini da ekliyor - Python communicate()/capture_output=True
        # PIPE'in TAMAMEN kapanmasini (TUM handle'lar dahil) bekledigi icin,
        # enjekte edilen bilesen kendi handle'ini kapatmadikca sure, script
        # gercekte aninda bitmis olsa bile, TAM timeout suresi kadar "asili"
        # gorunuyor (2026-09-21'de canli testte gozlemlendi: timeout 30s->90s
        # yapilinca da SUREKLI tam o surede kesildi - gercek bir hesaplama
        # degil, bir PIPE kilitlenmesi isareti). Gercek dosyaya yazip sadece
        # process handle'ini beklemek bu sinifta bir soruna hic girmiyor.
        #
        # NOT2: tmp_dir'i "with tempfile.TemporaryDirectory()" YERINE elle
        # (mkdtemp + finally: rmtree(ignore_errors=True)) yonetiyoruz. SEBEP:
        # Flask gibi kendi reloader/alt-surecini forklayan programlarda,
        # timeout'ta sadece dogrudan cocugu (proc.kill()) oldurmek YETMIYOR -
        # reloader'in baslattigi TORUN surec (gercek sunucu) hayatta kalip log
        # dosyalarini acik tutmaya devam edebiliyor. Eski kod "with
        # TemporaryDirectory()" kullaniyordu; bu durumda dizin silinirken
        # Windows WinError 32 ("dosya baska bir islem tarafindan
        # kullaniliyor") firlatiyordu ve bu hata "Timed out..." mesajimizi
        # return ETMEDEN once with-blogundan cikarken olustugu icin asil
        # mesaji YUTUYOR, disaridaki "except Exception" bunu genel bir "Run
        # error" gibi gosteriyordu - 5 denemenin 5'i de ayni sekilde basarisiz
        # oluyordu (2026-09-21, Flask testinde canli gozlemlendi). Simdi: (1)
        # timeout'ta tum surec agacini olduruyoruz (Windows'ta taskkill /T
        # /F), (2) temizlik hatasi ASLA asil sonucu maskelemiyor.
        tmp_dir = tempfile.mkdtemp(prefix="jarvis_devagent_")
        try:
            out_path = Path(tmp_dir) / "stdout.log"
            err_path = Path(tmp_dir) / "stderr.log"
            result_text = None
            with open(out_path, "w", encoding="utf-8") as out_f, \
                 open(err_path, "w", encoding="utf-8") as err_f:
                proc = subprocess.Popen(
                    parts,
                    stdout=out_f, stderr=err_f,
                    cwd=str(project_dir),
                )
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc)
                    result_text = f"Timed out after {timeout}s — long-running app (server/GUI) is likely working."

            if result_text is not None:
                return result_text

            stdout = out_path.read_text(encoding="utf-8", errors="replace").strip()
            stderr = err_path.read_text(encoding="utf-8", errors="replace").strip()

            combined_parts = []
            if stdout:
                combined_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                combined_parts.append(f"STDERR:\n{stderr}")

            return "\n\n".join(combined_parts) if combined_parts else "Ran with no output."
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """proc'un kendisini VE (varsa) torun sureclerini oldurur. Flask'in
    reloader'i gibi kendi alt-surecini forklayan araclarda proc.kill() TEK
    BASINA yetmiyor - torun surec hayatta kalip dosya/port acik tutmaya
    devam edebiliyor. Windows'ta "taskkill /T /F" tum agaci olduruyor;
    diger platformlarda dogrudan cocugu oldurmek yeterli."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass

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


_TYPING_PUBLIC_NAMES = frozenset(n for n in dir(typing) if not n.startswith("_"))


def _try_fix_typing_import(error_output: str, project_dir: Path, project_files: list[str]) -> bool:
    """'NameError: name 'X' is not defined' hatasi, X gercekten `typing`
    modulunun bir uyesiyse (Any, Optional, Dict, List, Union, Callable, vb.),
    LLM'e tekrar sormadan DOGRUDAN, deterministik bir metin islemiyle duzeltir:
    ilgili dosyadaki 'from typing import ...' satirina eksik adi ekler (yoksa
    yeni bir import satiri ekler).

    GERCEK MOTIVASYON: 2026-09-23'te canli bir dev_agent calismasinda
    (PersonalExpenseTracker projesi) tam olarak bu hata (eksik 'Any' importu,
    gui/expense_chart.py) modelin MAX_FIX_ATTEMPTS(5) denemesinin 4'unde de
    (dosya her seferinde bastan yazildigi icin) giderilemedi - LLM'in dosyayi
    yeniden uretmesi, bu turden tek satirlik/mekanik eksiklikleri guvenilir
    sekilde yakalayamiyor. Bu fonksiyon _fix_files (LLM tabanli, olasiliksal
    yeniden yazma) cagrilmadan ONCE denenir; basarili olursa bir model
    cagrisina bile gerek kalmaz."""
    match = re.search(r"NameError: name ['\"](\w+)['\"] is not defined", error_output)
    if not match:
        return False
    missing_name = match.group(1)
    if missing_name not in _TYPING_PUBLIC_NAMES:
        return False

    error_file, _ = _parse_traceback(error_output, project_files)
    if not error_file:
        return False
    full_path = _safe_project_path(project_dir, error_file)
    if full_path is None or not full_path.is_file():
        return False

    file_text = full_path.read_text(encoding="utf-8")
    import_pattern = re.compile(r"^from typing import (.+)$", re.MULTILINE)
    existing_match = import_pattern.search(file_text)
    if existing_match:
        existing_names = [n.strip() for n in existing_match.group(1).split(",")]
        if missing_name in existing_names:
            return False  # zaten import edilmis - baska bir sey bozuk, burada cozulemez
        new_line = f"from typing import {', '.join(sorted(existing_names + [missing_name]))}"
        file_text = file_text[:existing_match.start()] + new_line + file_text[existing_match.end():]
    else:
        file_text = f"from typing import {missing_name}\n" + file_text

    full_path.write_text(file_text, encoding="utf-8")
    print(f"[DevAgent] 🔧 Eksik 'typing.{missing_name}' importu otomatik eklendi ({error_file}).")
    return True


def _try_fix_bad_symbol_import(error_output: str, project_dir: Path, project_files: list[str]) -> bool:
    """'ImportError: cannot import name 'X' from 'Y'' hatasini, LLM'e
    sormadan, deterministik bir AST analiziyle duzeltmeyi dener.

    GERCEK MOTIVASYON: 2026-09-23'te canli bir dev_agent calismasinda
    (book_reader projesi) main.py, gui.py'nin GERCEK sinifi 'BookApp' iken
    'from gui import Application' yazmisti - var olmayan bir isim. Bu hata
    5 deneme boyunca duzelemedi, cunku _classify_error onu yanlislikla
    "dependency_error" (eksik paket) sanip LLM'e o baglamda sunuyordu.

    Strateji (guvenli, iki durum):
    1) Eksik isim, ice aktaran dosyada IMPORT SATIRI DISINDA hic
       kullanilmiyorsa: dogrudan, sadece o ismi import satirindan siler
       (kullanilmayan/kirik bir import'u kaldirmak hicbir zaman yanlis
       olmaz).
    2) Eksik isim baska yerde de kullaniliyorsa VE hedef modulde tam
       olarak TEK bir public (alt cizgiyle baslamayan) sinif/fonksiyon
       tanimliysa: eksik ismin ice aktaran dosyadaki TUM (tam kelime)
       gecislerini o tek gercek isimle degistirir.
    Iki durumdan hicbiri kesin degilse (belirsizse) hicbir sey yapmaz,
    dosya LLM tabanli genel duzeltmeye (_fix_files) birakilir - boylece
    bu fonksiyon asla riskli bir tahminde bulunmaz."""
    import ast

    match = re.search(
        r"cannot import name ['\"](\w+)['\"] from ['\"]([\w\.]+)['\"]",
        error_output,
    )
    if not match:
        return False
    missing_name, module_dotted = match.group(1), match.group(2)

    module_rel = module_dotted.replace(".", "/") + ".py"
    target_path = None
    for pf in project_files:
        if pf == module_rel or pf.endswith("/" + module_rel) or Path(pf).stem == Path(module_rel).stem:
            target_path = pf
            break
    if target_path is None:
        return False
    target_full = _safe_project_path(project_dir, target_path)
    if target_full is None or not target_full.is_file():
        return False

    try:
        tree = ast.parse(target_full.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    public_top_level = [
        node.name for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    if missing_name in public_top_level:
        return False  # aslinda orada tanimli - baska bir sey bozuk, burada cozulemez

    error_file, _ = _parse_traceback(error_output, project_files)
    if not error_file:
        return False
    error_full = _safe_project_path(project_dir, error_file)
    if error_full is None or not error_full.is_file():
        return False

    file_text = error_full.read_text(encoding="utf-8")
    name_pattern = re.compile(rf"\b{re.escape(missing_name)}\b")
    occurrences = len(name_pattern.findall(file_text))

    import_line_pattern = re.compile(
        rf"^from {re.escape(module_dotted)} import (.+)$", re.MULTILINE
    )
    import_match = import_line_pattern.search(file_text)
    if not import_match:
        return False

    if occurrences <= 1:
        # Sadece import satirinda geciyor, hic kullanilmiyor - guvenle sil.
        names = [n.strip() for n in import_match.group(1).split(",")]
        remaining = [n for n in names if n != missing_name]
        if remaining:
            new_line = f"from {module_dotted} import {', '.join(remaining)}"
            file_text = file_text[:import_match.start()] + new_line + file_text[import_match.end():]
        else:
            file_text = file_text[:import_match.start()] + file_text[import_match.end():].lstrip("\n")
        error_full.write_text(file_text, encoding="utf-8")
        print(f"[DevAgent] 🔧 Kullanilmayan/kirik import '{missing_name}' kaldirildi ({error_file}).")
        return True

    if len(public_top_level) == 1:
        real_name = public_top_level[0]
        file_text = name_pattern.sub(real_name, file_text)
        error_full.write_text(file_text, encoding="utf-8")
        print(
            f"[DevAgent] 🔧 Yanlis isim '{missing_name}' -> gercek isim "
            f"'{real_name}' ile degistirildi ({error_file}, {target_path}'de tanimli tek public isim)."
        )
        return True

    return False  # belirsiz (0 ya da 2+ aday) - LLM tabanli genel duzeltmeye birak


# Bazi paketlerin IMPORT adi (kod icinde "import X") ile PyPI'daki GERCEK
# paket adi FARKLI - bunu bilmeden "No module named X" -> "pip install X"
# yapmak calisir gibi gorunur ama bazilari icin asla basarili olmaz:
# ozellikle 'sklearn', PyPI'da KASITLI OLARAK bozuk/deprecated bir stub -
# gercek paket 'scikit-learn'. Bu yuzden bu eslemeyi kontrol etmeden pip'e
# ham import adini vermek, ayni hatanin sonsuz dongu gibi tekrar tekrar
# denenmesine yol aciyordu (2026-09-21'de canli dev_agent testinde
# gozlemlendi: kmeans_clustering projesi 5 denemede de duzelemedi, gercek
# sebep 'sklearn' paketinin hicbir zaman kurulamamasiydi).
_IMPORT_TO_PYPI = {
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "cv2": "opencv-python",
    "pil": "Pillow",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "PyMuPDF",
    "serial": "pyserial",
    "usb": "pyusb",
    "attr": "attrs",
    "nmap": "python-nmap",
    "openssl": "pyOpenSSL",
    "win32com": "pywin32",
    "win32api": "pywin32",
    "crypto": "pycryptodome",
    "gi": "PyGObject",
    "opengl": "PyOpenGL",
}


def _try_auto_install(error_output: str, project_dir: Path) -> bool:
    """ModuleNotFoundError varsa eksik paketi otomatik kurmaya çalışır."""
    pattern = re.compile(
        r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
    )
    match = pattern.search(error_output)
    if not match:
        return False

    module_name = match.group(1).split(".")[0]
    pkg = _IMPORT_TO_PYPI.get(module_name.lower(), module_name.replace("_", "-"))
    print(f"[DevAgent] 🔧 Auto-installing missing package: {pkg} (import: {module_name})")
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
    shared_contracts: str = "",
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

        shared_contracts_block = (
            "Shared data contracts ALL files must follow EXACTLY:\n" + shared_contracts
        ) if shared_contracts else ""

        prompt = f"""You are an expert {language} debugger. Fix the broken file below.

Project goal: {project_description}

All project files:
{chr(10).join(f"  - {f['path']}: {f.get('description', '')}" for f in all_files)}

Other files for context (read-only — fix only the target file):
{other_ctx[:3500]}

{shared_contracts_block}

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

            full_path = _safe_project_path(project_dir, fix_path)
            if full_path is None:
                print(f"[DevAgent] 🛑 Güvenlik: düzeltme yolu ('{fix_path}') proje "
                      f"klasörü dışına çıkıyor, atlandı (path traversal koruması).")
                continue
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                from datetime import datetime as _dt
                stamp  = _dt.now().strftime("%Y%m%d-%H%M%S")
                backup = full_path.with_name(f"{full_path.stem}.{stamp}.bak{full_path.suffix}")
                # F-10: yedek BYTE duzeyinde (birebir kopya) - encoding
                # round-trip'i yedegin ORIJINALLE ayni olmasini bozabiliyordu.
                backup.write_bytes(full_path.read_bytes())
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
    shared_contracts_text = "\n".join(f"- {c}" for c in plan.get("shared_data_contracts", []) if c)
    expected_outputs = plan.get("expected_outputs", [])

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
                    shared_contracts=shared_contracts_text,
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

    last_output      = ""
    auto_installs    = 0
    timeout_extended = False
    current_timeout  = timeout

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")
        run_started_at = time.time()
        last_output = _run_project(run_command, project_dir, current_timeout)
        log(f"Output preview: {last_output[:150]}")

        if last_output.startswith("REFUSED:"):
            # Bu bir kod hatasi degil, bir GUVENLIK reddi - self-fix dongusune
            # asla girmez (model farkli bir yikici komut denemeye kalkabilir).
            # Dogrudan, durumu oldugu gibi kullaniciya bildirerek durur.
            msg = (
                f"'{proj_name}' projesi için üretilen çalıştırma komutu yıkıcı bir "
                f"kalıp içerdiği için ÇALIŞTIRILMADI (güvenlik reddi), efendim. "
                f"Dosyalar {project_dir} içinde duruyor, elle kontrol etmeniz gerekiyor."
            )
            if speak: speak(msg)
            return f"{msg}\n\n{last_output}"

        is_timeout = last_output.startswith("Timed out")

        if is_timeout and not timeout_extended and attempt < MAX_FIX_ATTEMPTS:
            # _has_error() timeout'u kasitli olarak hata SAYMIYOR (bir sunucu/
            # GUI kasitli olarak surekli calisabilir), AMA bu hicbir sey
            # DOGRULANMADI demektir - antivirus/soguk-import gecikmesi ya da
            # gercekten takili kalmis bozuk bir betik de ayni ciktiyi verir
            # (2026-09-21'de canli testte gozlemlendi: Norton 360 taramasi
            # yuzunden ilk import 30sn'yi asti). Once, henuz kullanilmadiysa,
            # BIR KEZ uzatilmis timeout ile tekrar denenir - fresh bir pip
            # install sonrasi soguk import gecikmesini karsilamak icin.
            timeout_extended = True
            current_timeout = timeout * 3
            log(f"Zaman asimi - {current_timeout}s ile bir kez daha deneniyor (soguk import/antivirus taramasi olabilir)...")
            time.sleep(1)
            continue

        has_crash_error = _has_error(last_output, run_command)

        # DUZELTME (2026-09-23, web_scraper canli testi): "cokmedi" ile
        # "gercekten dogru calisti" AYNI SEY DEGIL. O testte program hicbir
        # Python hatasi vermeden calisip bitti ("Scraping completed" yazdi),
        # ama gercekte hicbir satir veritabanina yazilmamisti. _has_error()
        # SADECE Python traceback'lerini arar, boyle sessiz/mantik
        # hatalarini asla goremez. Plan "expected_outputs" bildirdiyse, o
        # dosyalarin bu calistirmada GERCEKTEN olusup/guncellenip
        # guncellenmedigini kendimiz kontrol ediyoruz.
        output_problems = (
            _check_expected_outputs(project_dir, expected_outputs, run_started_at)
            if expected_outputs and not has_crash_error else []
        )
        if output_problems:
            log(f"Program çökmedi ama beklenen çıktı üretilmedi: {output_problems}")
            last_output = _format_output_problem_message(last_output, output_problems)

        if not has_crash_error and not output_problems:
            if is_timeout:
                if expected_outputs:
                    verified_note = f" Beklenen çıktılar gerçekten doğrulandı ({', '.join(str(o.get('path', o)) if isinstance(o, dict) else str(o) for o in expected_outputs)})."
                else:
                    verified_note = " AMA betiğin gerçekten doğru çalıştığını DOĞRULAYAMADIM, takılı kalmış da olabilir."
                msg = (
                    f"'{proj_name}' projesi {current_timeout} saniye içinde tamamlanmadı, efendim. "
                    f"Bu, kasıtlı olarak sürekli çalışan bir sunucu/GUI uygulaması olabilir.{verified_note} "
                    f"Dosyalar {project_dir} içinde duruyor, lütfen VSCode'dan elle kontrol edin."
                )
            else:
                verified_note = (
                    f" Verified outputs: {', '.join(str(o.get('path', o)) if isinstance(o, dict) else str(o) for o in expected_outputs)}."
                    if expected_outputs else ""
                )
                msg = (
                    f"Project '{proj_name}' is working, sir. "
                    f"Built in {attempt} attempt{'s' if attempt > 1 else ''}.{verified_note} "
                    f"Saved to: {project_dir}"
                )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_type = "output_missing" if output_problems else _classify_error(last_output, project_dir)

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

        if error_type == "runtime_error":
            fixed_typing = _try_fix_typing_import(last_output, project_dir, list(file_codes.keys()))
            if fixed_typing:
                log("Eksik 'typing' importu otomatik eklendi (model cagrilmadan), tekrar deneniyor...")
                time.sleep(1)
                continue

        if error_type == "import_error":
            fixed_symbol = _try_fix_bad_symbol_import(last_output, project_dir, list(file_codes.keys()))
            if fixed_symbol:
                log("Yanlis/kirik isim importu otomatik duzeltildi (model cagrilmadan), tekrar deneniyor...")
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
                shared_contracts=shared_contracts_text,
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
    confirm_code = (p.get("confirm_code") or "").strip()

    if not description:
        return "Please describe the project you want me to build, sir."

    # ONAY KAPISI: bu adim pip ile paket kurar ve modelin urettigi kodu
    # gercekten calistirir - confirm_code verilmeden hicbiri yapilmaz.
    if not confirm_code:
        code = secrets.token_hex(3)
        _pending_dev_agent[code] = {
            "description": description, "language": language,
            "project_name": project_name, "timeout": timeout,
        }
        return (
            f"ONAY GEREKLİ: \"{description}\" açıklamasıyla yeni bir {language} projesi "
            f"oluşturulacak. Bu adım gerekli paketleri pip ile kurar ve üretilen kodu "
            f"gerçekten çalıştırır. Kullanıcıya bunu tarif et; kullanıcı SESLİ/YAZILI olarak "
            f"açıkça onaylarsa (bir sonraki mesajında), dev_agent'ı aynı description/language/"
            f"project_name ile ve confirm_code='{code}' parametresiyle TEKRAR çağır. "
            f"Kullanıcı onaylamadan bu kodu kendi kendine kullanma."
        )
    pending = _pending_dev_agent.pop(confirm_code, None)
    if pending is None:
        return "Onay kodu geçersiz veya süresi dolmuş. Önce confirm_code vermeden çağırıp yeni kod alın."

    return _build_project(
        description  = pending["description"],
        language     = pending["language"],
        project_name = pending["project_name"],
        timeout      = pending["timeout"],
        speak        = speak,
        player       = player,
    )
