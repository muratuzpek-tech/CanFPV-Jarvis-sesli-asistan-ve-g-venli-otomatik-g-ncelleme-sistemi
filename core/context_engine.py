"""Short-term context engine for Jarvis.

Keeps a bounded recent transcript locally, extracts lightweight signals without
calling a model, and creates a compact context block for the next LLM request.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "memory" / "session_context.json"
MAX_TURNS = 20
MAX_CHARS = 9000

@dataclass
class Turn:
    role: str
    content: str
    timestamp: float

class ContextEngine:
    def __init__(self, max_turns: int = MAX_TURNS) -> None:
        self.turns: deque[Turn] = deque(maxlen=max(4, max_turns))
        self.entities: dict[str, str] = {}
        self.preferences: dict[str, str] = {}
        self.load()

    def add(self, role: str, content: str) -> None:
        clean = re.sub(r"\s+", " ", str(content)).strip()
        if not clean:
            return
        self.turns.append(Turn(role, clean[:4000], time.time()))
        if role == "user":
            self._extract_signals(clean)
        self.save()

    def _extract_signals(self, text: str) -> None:
        patterns = [
            (r"(?:benim adım|adım)\s+([\wçğıöşüÇĞİÖŞÜ -]{2,40})", "name"),
            (r"(?:bana|beni)\s+([\wçğıöşüÇĞİÖŞÜ -]{2,30})\s+diye hitap", "address"),
            (r"(?:tercih ediyorum|seviyorum|istiyorum)\s+(.{2,100})", "preference"),
        ]
        for pattern, key in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" .,!?")
                if key == "preference":
                    self.preferences[str(len(self.preferences) + 1)] = value
                else:
                    self.entities[key] = value

    def build_prompt_block(self) -> str:
        recent = list(self.turns)
        lines = ["[ACTIVE SESSION CONTEXT]"]
        if self.entities:
            lines.append("Known session facts: " + json.dumps(self.entities, ensure_ascii=False))
        if self.preferences:
            lines.append("Session preferences: " + json.dumps(self.preferences, ensure_ascii=False))
        if recent:
            lines.append("Recent conversation:")
            for turn in recent[-12:]:
                lines.append(f"{turn.role}: {turn.content}")
        result = "\n".join(lines)
        return result[:MAX_CHARS]

    def save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"turns": [asdict(t) for t in self.turns], "entities": self.entities, "preferences": self.preferences}
        STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            for item in data.get("turns", [])[-self.turns.maxlen:]:
                self.turns.append(Turn(str(item["role"]), str(item["content"]), float(item.get("timestamp", time.time()))))
            self.entities = dict(data.get("entities", {}))
            self.preferences = dict(data.get("preferences", {}))
        except (OSError, ValueError, TypeError, KeyError):
            return

    def clear(self) -> None:
        self.turns.clear()
        self.entities.clear()
        self.preferences.clear()
        try:
            STATE_PATH.unlink()
        except FileNotFoundError:
            pass

    def status(self) -> dict[str, Any]:
        return {"turn_count": len(self.turns), "entities": self.entities, "preferences": self.preferences}
