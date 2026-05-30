from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CrawlState:
    completed: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "CrawlState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            completed=dict(data.get("completed", {})),
            failed=dict(data.get("failed", {})),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "completed": self.completed,
            "failed": self.failed,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
