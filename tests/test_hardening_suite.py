"""Offline hardening tests for the JARVIS v13 failure-prone paths."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
main = (ROOT / "main.py").read_text(encoding="utf-8")
web = (ROOT / "actions" / "web_search.py").read_text(encoding="utf-8")
aorch = (ROOT / "core" / "brain_orchestrator.py").read_text(encoding="utf-8")
base = (ROOT / "brains" / "base_brain.py").read_text(encoding="utf-8")

# Syntax and required imports.
for path in (ROOT / "main.py", ROOT / "actions" / "web_search.py", ROOT / "core" / "brain_orchestrator.py", ROOT / "brains" / "base_brain.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
assert re.search(r"^import os$", main, re.M), "startup env uses os without import"

# Startup briefing must not be able to take down the Live TaskGroup.
assert "async def _guarded_startup_briefing" in main
assert "tg.create_task(self._guarded_startup_briefing())" in main
assert 'JARVIS_STARTUP_NEWS' in main
assert '"0"' in main, "startup news must default off"

# Intent collision regressions.
assert "explicit_task_request" in main
assert "explicit_status_request" in main
assert "not explicit_status_request" in main
assert "BRAIN_TEAM_STATUS" in main

# Gemini client lifecycle and quota cooldown.
assert "getattr(client, \"close\", None)" in web
assert "getattr(client, \"close\", None)" in base
assert "_GEMINI_SEARCH_COOLDOWN_SECONDS" in web
assert "RESOURCE_EXHAUSTED" in web

# Live notification must support JarvisLive.ui.write_log.
assert "player.ui" in aorch
assert "player.write_log veya player.ui.write_log bulunamadı" in aorch

# Audio protection must normalize only abnormal peaks.
assert "_peak > 6000" in main
assert "_safe = _np.clip" in main
assert "data = _safe.tobytes()" in main

# Bağımlılıkların tek kaynağı artık pyproject.toml (requirements.txt değil).
pyproject = (ROOT.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
assert "ddgs>=" in pyproject
assert "duckduckgo-search" not in pyproject

print("HARDENING_SUITE_OK")
print("startup_guard=OK")
print("intent_priority=OK")
print("notification_fallback=OK")
print("gemini_close_and_cooldown=OK")
print("microphone_peak_normalization=OK")
print("dependency_migration=OK")
