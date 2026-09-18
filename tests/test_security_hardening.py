"""Security regression tests for untrusted desktop automation paths."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"

def calls_named(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id == name) or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]

def main():
    desktop = ast.parse((ROOT / "actions/desktop.py").read_text(encoding="utf-8"))
    assert not calls_named(desktop, "exec"), "desktop.py must not execute LLM-generated Python"
    open_app = (ROOT / "actions/open_app.py").read_text(encoding="utf-8")
    assert "shell=True" not in open_app, "open_app.py must not invoke a shell"
    assert "LLM-generated desktop code execution is disabled" in (ROOT / "actions/desktop.py").read_text(encoding="utf-8")
    print("SECURITY_HARDENING_OK")

if __name__ == "__main__":
    main()
