"""Tool definitions, execution, and permission system."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# 权限模式分类

PermissionMode = str  # "default" | "acceptEdits" | "bypassPermissions" | "dontAsk"

READ_TOOLS = {"read_file", "list_files", "grep_search", "web_fetch"}
EDIT_TOOLS = {"write_file", "edit_file"}
CONCURRENCY_SAFE_TOOLS = {"read_file", "list_files", "grep_search", "web_fetch"}

IS_WIN = sys.platform == "win32"

# 工具定义

tool_definitions: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to write"},
                "content": {"type": "string", "description": "The content to write to the file"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Edit a file by replacing an exact string match with new content. The old_string must match exactly (including whitespace and indentation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to edit"},
                "old_string": {"type": "string", "description": "The exact string to find and replace"},
                "new_string": {"type": "string", "description": "The string to replace it with"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern. Returns matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": 'Glob pattern (e.g., "**/*.py", "src/**/*")'},
                "path": {"type": "string", "description": "Base directory to search from. Defaults to current directory."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The regex pattern to search for"},
                "path": {"type": "string", "description": "Directory or file to search in. Defaults to current directory."},
                "include": {"type": "string", "description": 'File glob pattern to include (e.g., "*.py")'},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": "Execute a shell command and return its output. Use for running tests, git, installing packages, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "number", "description": "Timeout in milliseconds (default: 30000)"},
            },
            "required": ["command"],
        },
    },
]

# 工具实现

def _read_file(inp: dict) -> str:
    try:
        p = Path(inp["file_path"]).resolve()
        content = p.read_text(encoding="utf-8")
        lines = content.split("\n")
        return "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
    except FileNotFoundError:
        p = Path(inp["file_path"]).resolve()
        return f"File not found: {p}\n  (working directory: {Path.cwd()})"
    except Exception as e:
        return f"Error reading file: {e}"

def _write_file(inp: dict) -> str:
    try:
        p = Path(inp["file_path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"], encoding="utf-8")
        lines = inp["content"].split("\n")
        preview = "\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines[:30]))
        trunc = f"\n  ... ({len(lines)} lines total)" if len(lines) > 30 else ""
        return f"Successfully wrote to {inp['file_path']} ({len(lines)} lines)\n\n{preview}{trunc}"
    except Exception as e:
        return f"Error writing file: {e}"

def _edit_file(inp: dict) -> str:
    try:
        p = Path(inp["file_path"])
        content = p.read_text(encoding="utf-8")
        old_str = inp["old_string"]
        new_str = inp["new_string"]

        if old_str not in content:
            return f"Error: old_string not found in {inp['file_path']}"
        if content.count(old_str) > 1:
            return f"Error: old_string found {content.count(old_str)} times. Must be unique."

        new_content = content.replace(old_str, new_str, 1)
        p.write_text(new_content, encoding="utf-8")

        # 产生一个简单的 diff 输出
        before = content.split(old_str)[0]
        line_num = before.count("\n") + 1
        old_lines = old_str.split("\n")
        new_lines = new_str.split("\n")
        diff_parts = [f"@@ -{line_num},{len(old_lines)} +{line_num},{len(new_lines)} @@"]
        for l in old_lines:
            diff_parts.append(f"- {l}")
        for l in new_lines:
            diff_parts.append(f"+ {l}")
        return f"Successfully edited {inp['file_path']}\n\n" + "\n".join(diff_parts)
    except Exception as e:
        return f"Error editing file: {e}"

def _list_files(inp: dict) -> str:
    try:
        base = Path(inp.get("path") or ".")
        files = []
        for p in sorted(base.glob(inp["pattern"])):
            if p.is_file() and "node_modules" not in str(p) and ".git" not in p.parts:
                rel = str(p.relative_to(base) if base != Path(".") else p)
                files.append(rel)
                if len(files) >= 200:
                    break
        if not files:
            return "No files found matching the pattern."
        result = "\n".join(files[:200])
        if len(files) > 200:
            result += f"\n... and {len(files) - 200} more"
        return result
    except Exception as e:
        return f"Error listing files: {e}"

def _grep_search(inp: dict) -> str:
    pattern = inp["pattern"]
    path = inp.get("path") or "."
    include = inp.get("include")

    # 尝试使用系统grep命令进行搜索，速度更快（仅限非Windows系统）
    if not IS_WIN:
        try:
            args = ["grep", "--line-number", "--color=never", "-r"]
            if include:
                args.append(f"--include={include}")
            args.extend(["--", pattern, path])
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            if result.returncode == 1:
                return "No matches found."
            if result.returncode == 0:
                lines = [l for l in result.stdout.split("\n") if l]
                output = "\n".join(lines[:100])
                if len(lines) > 100:
                    output += f"\n... and {len(lines) - 100} more matches"
                return output
        except Exception:
            pass

    # 如果系统grep不可用或在Windows上，则使用Python实现递归搜索
    regex = re.compile(pattern)
    matches: list[str] = []

    def walk(d: str) -> None:
        if len(matches) >= 200:
            return
        try:
            entries = os.listdir(d)
        except OSError:
            return
        for name in entries:
            if name.startswith(".") or name == "node_modules":
                continue
            full = os.path.join(d, name)
            if os.path.isdir(full):
                walk(full)
                continue
            if include and not fnmatch.fnmatch(name, include):
                continue
            try:
                text = Path(full).read_text(errors="replace")
                for i, line in enumerate(text.split("\n")):
                    if regex.search(line):
                        matches.append(f"{full}:{i+1}:{line}")
                        if len(matches) >= 200:
                            return
            except Exception:
                pass

    walk(path)
    if not matches:
        return "No matches found."
    output = "\n".join(matches[:100])
    if len(matches) > 100:
        output += f"\n... and {len(matches) - 100} more matches"
    return output

def _run_shell(inp: dict) -> str:
    try:
        timeout_s = inp.get("timeout", 30000) / 1000
        result = subprocess.run(
            inp["command"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            stderr = f"\nStderr: {result.stderr}" if result.stderr else ""
            stdout = f"\nStdout: {result.stdout}" if result.stdout else ""
            return f"Command failed (exit code {result.returncode}){stdout}{stderr}"
        return result.stdout or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {inp.get('timeout', 30000)}ms"
    except Exception as e:
        return f"Error: {e}"

# 权限系统

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s"),
    re.compile(r"\bgit\s+(push|reset|clean|checkout\s+\.)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bkill\b"),
    re.compile(r"\bpkill\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\bdel\s", re.IGNORECASE),
    re.compile(r"\brmdir\s", re.IGNORECASE),
    re.compile(r"\bformat\s", re.IGNORECASE),
    re.compile(r"\btaskkill\s", re.IGNORECASE),
    re.compile(r"\bRemove-Item\s", re.IGNORECASE),
]

def is_dangerous(command: str) -> bool:
    return any(p.search(command) for p in DANGEROUS_PATTERNS)

def check_permission(
    tool_name: str,
    inp: dict,
    mode: str = "default",
) -> dict:
    """Returns {"action": "allow"|"deny"|"confirm", "message": ...}"""
    if mode == "bypassPermissions":
        return {"action": "allow"}

    # 读操作加入默认允许列表，免去频繁确认的麻烦
    if tool_name in READ_TOOLS:
        return {"action": "allow"}

    # acceptEdits模式下允许编辑工具
    if mode == "acceptEdits" and tool_name in EDIT_TOOLS:
        return {"action": "allow"}

    # 并发安全工具允许在acceptEdits模式下使用
    needs_confirm = False
    confirm_message = ""

    if tool_name == "run_shell" and is_dangerous(inp.get("command", "")):
        needs_confirm = True
        confirm_message = inp.get("command", "")
    elif tool_name == "write_file":
        p = Path(inp.get("file_path", ""))
        if not p.exists():
            needs_confirm = True
            confirm_message = f"write new file: {inp.get('file_path', '')}"
    elif tool_name == "edit_file":
        p = Path(inp.get("file_path", ""))
        if not p.exists():
            needs_confirm = True
            confirm_message = f"edit non-existent file: {inp.get('file_path', '')}"

    if needs_confirm:
        if mode == "dontAsk":
            return {"action": "deny", "message": f"Auto-denied (dontAsk mode): {confirm_message}"}
        return {"action": "confirm", "message": confirm_message}

    return {"action": "allow"}

# 工具执行函数，包含读-before-edit保护和结果截断

async def execute_tool(
    name: str,
    inp: dict,
    read_file_state: dict[str, float] | None = None,
) -> str:
    # read-before-edit protection
    if name == "read_file":
        result = _read_file(inp)
        if read_file_state is not None and not result.startswith("Error"):
            abs_path = str(Path(inp["file_path"]).resolve())
            try:
                read_file_state[abs_path] = os.path.getmtime(abs_path)
            except OSError:
                pass
        return _truncate(result)

    if name in ("write_file", "edit_file") and read_file_state is not None:
        if "file_path" not in inp:
            return f"Error: missing file_path for {name}"
        abs_path = str(Path(inp["file_path"]).resolve())
        if os.path.exists(abs_path):
            if abs_path not in read_file_state:
                verb = "writing" if name == "write_file" else "editing"
                return f"Error: You must read this file before {verb}. Use read_file first."
            if os.path.getmtime(abs_path) != read_file_state[abs_path]:
                verb = "writing" if name == "write_file" else "editing"
                return f"Warning: {inp['file_path']} was modified externally. Please read_file again before {verb}."

    handlers = {
        "write_file": _write_file,
        "edit_file": _edit_file,
        "list_files": _list_files,
        "grep_search": _grep_search,
        "run_shell": _run_shell,
    }
    handler = handlers.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    result = _truncate(handler(inp))

    # Update mtime after successful write/edit
    if name in ("write_file", "edit_file") and read_file_state is not None and not result.startswith("Error"):
        abs_path = str(Path(inp["file_path"]).resolve())
        try:
            read_file_state[abs_path] = os.path.getmtime(abs_path)
        except OSError:
            pass

    return result

MAX_RESULT_CHARS = 50000

def _truncate(result: str) -> str:
    if len(result) <= MAX_RESULT_CHARS:
        return result
    keep = (MAX_RESULT_CHARS - 60) // 2
    return result[:keep] + f"\n\n[... truncated {len(result) - keep * 2} chars ...]\n\n" + result[-keep:]
