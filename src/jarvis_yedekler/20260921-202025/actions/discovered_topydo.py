import re
from datetime import date
from pathlib import Path


class TodoItem:
    def __init__(self, raw_text: str):
        self.raw = raw_text.strip()
        self.completed = False
        self.completion_date = None
        self.priority = None
        self.creation_date = None
        self.text = ""
        self.projects = []
        self.contexts = []
        self.tags = {}
        self._parse()

    def _parse(self):
        tokens = self.raw.split()
        if not tokens:
            return

        idx = 0
        if tokens[idx] == "x":
            self.completed = True
            idx += 1
            if idx < len(tokens) and re.match(r"^\d{4}-\d{2}-\d{2}$", tokens[idx]):
                self.completion_date = tokens[idx]
                idx += 1

        if idx < len(tokens) and re.match(r"^\([A-Z]\)$", tokens[idx]):
            self.priority = tokens[idx][1]
            idx += 1

        if idx < len(tokens) and re.match(r"^\d{4}-\d{2}-\d{2}$", tokens[idx]):
            self.creation_date = tokens[idx]
            idx += 1

        remaining_tokens = tokens[idx:]
        text_parts = []
        for token in remaining_tokens:
            if token.startswith("+") and len(token) > 1:
                self.projects.append(token[1:])
            elif token.startswith("@") and len(token) > 1:
                self.contexts.append(token[1:])
            elif ":" in token and not token.startswith("http"):
                k, v = token.split(":", 1)
                self.tags[k] = v
            text_parts.append(token)
        self.text = " ".join(text_parts)

    def mark_done(self):
        if self.completed:
            return
        today_str = date.today().isoformat()
        self.completed = True
        self.completion_date = today_str
        parts = ["x", today_str]
        if self.creation_date:
            parts.append(self.creation_date)
        if self.text:
            parts.append(self.text)
        self.raw = " ".join(parts)

    def set_priority(self, prio: str):
        prio = prio.strip().upper()
        if not re.match(r"^[A-Z]$", prio):
            return False
        self.priority = prio
        tokens = self.raw.split()
        idx = 0
        if tokens and tokens[0] == "x":
            return False
        if tokens and re.match(r"^\([A-Z]\)$", tokens[idx]):
            tokens[idx] = f"({prio})"
        else:
            tokens.insert(0, f"({prio})")
        self.raw = " ".join(tokens)
        self._parse()
        return True

    def to_display(self, index: int) -> str:
        status = "[Tamamlandı]" if self.completed else "[Açık]"
        prio = f"({self.priority}) " if self.priority else ""
        return f"{index}. {status} {prio}{self.text or self.raw}"


def _get_todo_file(path_str: str = None) -> Path:
    if path_str:
        p = Path(path_str).expanduser()
    else:
        p = Path.home() / ".jarvis_todo.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch()
    return p


def _read_todos(file_path: Path) -> list:
    lines = file_path.read_text(encoding="utf-8").splitlines()
    todos = []
    for line in lines:
        if line.strip():
            todos.append(TodoItem(line))
    return todos


def _write_todos(file_path: Path, todos: list):
    content = "\n".join([item.raw for item in todos]) + ("\n" if todos else "")
    file_path.write_text(content, encoding="utf-8")


def run(parameters: dict) -> str:
    action = str(parameters.get("action", "list")).strip().lower()
    custom_path = parameters.get("file_path")
    file_path = _get_todo_file(custom_path)

    todos = _read_todos(file_path)

    if action in ["add", "ekle", "yeni"]:
        task_text = parameters.get("task") or parameters.get("content") or parameters.get("text")
        if not task_text:
            return "Eklemek istediğiniz görevi belirtmediniz."

        task_str = str(task_text).strip()
        prio = parameters.get("priority")
        today_str = date.today().isoformat()

        raw_parts = []
        if prio and re.match(r"^[A-Za-z]$", str(prio).strip()):
            raw_parts.append(f"({prio.strip().upper()})")
        raw_parts.append(today_str)
        raw_parts.append(task_str)

        new_raw = " ".join(raw_parts)
        todos.append(TodoItem(new_raw))
        _write_todos(file_path, todos)
        return f"Görev eklendi: #{len(todos)} - {task_str}"

    elif action in ["list", "show", "goster", "listele"]:
        if not todos:
            return "Listenizde kayıtlı herhangi bir görev bulunmuyor."

        filter_kw = parameters.get("filter") or parameters.get("search")
        show_all = parameters.get("all", False)

        results = []
        for i, item in enumerate(todos, start=1):
            if not show_all and item.completed:
                continue
            if filter_kw:
                kw = str(filter_kw).lower()
                if kw not in item.raw.lower():
                    continue
            results.append(item.to_display(i))

        if not results:
            return "Filtreleme kriterine uyan görev bulunamadı."

        return "Görevleriniz:\n" + "\n".join(results)

    elif action in ["done", "complete", "bitir", "tamamla"]:
        task_id = parameters.get("task_id") or parameters.get("id") or parameters.get("index")
        if task_id is None:
            return "Tamamlamak istediğiniz görevin numarasını belirtmelisiniz."

        try:
            idx = int(task_id) - 1
            if idx < 0 or idx >= len(todos):
                return f"{task_id} numaralı bir görev bulunamadı."
        except ValueError:
            return "Geçerli bir görev numarası girmelisiniz."

        item = todos[idx]
        if item.completed:
            return f"{task_id} numaralı görev zaten tamamlanmış."

        item.mark_done()
        _write_todos(file_path, todos)
        return f"Görev tamamlandı: {item.text or item.raw}"

    elif action in ["delete", "remove", "sil"]:
        task_id = parameters.get("task_id") or parameters.get("id") or parameters.get("index")
        if task_id is None:
            return "Silmek istediğiniz görevin numarasını belirtmelisiniz."

        try:
            idx = int(task_id) - 1
            if idx < 0 or idx >= len(todos):
                return f"{task_id} numaralı bir görev bulunamadı."
        except ValueError:
            return "Geçerli bir görev numarası girmelisiniz."

        deleted = todos.pop(idx)
        _write_todos(file_path, todos)
        return f"Görev silindi: {deleted.text or deleted.raw}"

    elif action in ["prioritize", "oncelik"]:
        task_id = parameters.get("task_id") or parameters.get("id") or parameters.get("index")
        priority = parameters.get("priority")
        if task_id is None or not priority:
            return "Görev numarası ve öncelik harfi (A-Z) belirtmelisiniz."

        try:
            idx = int(task_id) - 1
            if idx < 0 or idx >= len(todos):
                return f"{task_id} numaralı bir görev bulunamadı."
        except ValueError:
            return "Geçerli bir görev numarası girmelisiniz."

        success = todos[idx].set_priority(str(priority))
        if success:
            _write_todos(file_path, todos)
            return f"{task_id} numaralı görevin önceliği ({priority.upper()}) olarak güncellendi."
        else:
            return "Öncelik güncellenemedi. Tamamlanmış görevlere öncelik atanamaz ve harf A-Z olmalıdır."

    elif action in ["clear", "temizle"]:
        active_todos = [t for t in todos if not t.completed]
        removed_count = len(todos) - len(active_todos)
        _write_todos(file_path, active_todos)
        return f"Tamamlanmış {removed_count} adet görev arşivlendi ve temizlendi."

    else:
        return f"Bilinmeyen işlem türü: '{action}'. Desteklenen eylemler: add, list, done, delete, prioritize, clear."