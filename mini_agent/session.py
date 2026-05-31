"""会话管理，包含保存和加载会话数据的功能"""

from __future__ import annotations

import json
from pathlib import Path

SESSION_DIR = Path.home() / ".mini-agent" / "sessions"

def _ensure_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

def save_session(session_id: str, data: dict) -> None:
    _ensure_dir()
    (SESSION_DIR / f"{session_id}.json").write_text(json.dumps(data, indent=2, default=str))

def load_session(session_id: str) -> dict | None:
    path = SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

def get_latest_session_id() -> str | None:
    _ensure_dir()
    sessions = []
    for f in SESSION_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if "metadata" in data:
                sessions.append(data["metadata"])
        except Exception:
            pass
    if not sessions:
        return None
    sessions.sort(key=lambda s: s.get("startTime", ""), reverse=True)
    return sessions[0].get("id")
