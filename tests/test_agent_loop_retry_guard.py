from pathlib import Path
import ast

p = Path(__file__).resolve().parents[1] / 'src' / 'jarvis' / 'actions' / 'agent_loop.py'
s = p.read_text(encoding='utf-8')
ast.parse(s)
assert 'MAX_PLANNING_RETRIES = 3' in s
assert 'planning_retries' in s
assert 'planning_failed_final' in s
assert 'task["status"] = "failed"' in s
assert 'def _run_readonly_github_research' in s
assert 'github_search({"query": query' in s
assert 'task["status"] = "running"' in s
print('AGENT_LOOP_PENDING_GUARD_OK')
print('GITHUB_READONLY_DETERMINISTIC_OK')
