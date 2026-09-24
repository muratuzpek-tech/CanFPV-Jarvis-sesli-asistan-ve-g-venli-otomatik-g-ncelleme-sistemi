from pathlib import Path
import json
import sqlite3
import tempfile

from jarvis.actions.dev_agent import _check_output_contents, _validate_plan

plan = {
    "entry_point": "main.py",
    "files": [{"path": "main.py"}],
    "expected_outputs": [{"path": "database.db", "description": "contains one row per result"}],
}
assert _validate_plan(plan, "write results to a SQLite database") == plan
try:
    _validate_plan({"entry_point": "main.py", "files": [{"path": "main.py"}]}, "save results to database")
except ValueError:
    pass
else:
    raise AssertionError("missing persistence output was accepted")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    db = root / "database.db"
    with sqlite3.connect(db) as con:
        con.execute("create table results (id integer primary key, value text)")
        con.execute("insert into results(value) values ('ok')")
        con.commit()
    assert _check_output_contents(root, [{"path": "database.db", "description": "contains result rows"}]) == []
print("DEV_AGENT_CONTRACT_SMOKE_OK")
