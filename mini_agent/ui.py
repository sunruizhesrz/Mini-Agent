"""Terminal UI — colored output, spinner, tool display."""

from __future__ import annotations

import sys
import threading
import time

# 确保Windows终端支持ANSI转义序列（颜色）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ANSI 颜色和样式代码
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
WHITE = "\033[37m"
RESET = "\033[0m"

def _c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}"


def print_welcome() -> None:
    print(f"\n  {_c(BOLD + CYAN, 'Mini Agent')}{_c(DIM, ' — a minimal coding agent')}\n")
    print(_c(DIM, "  Type your request, or 'exit' to quit."))
    print(_c(DIM, "  Commands: /clear /cost /compact\n"))

def print_user_prompt() -> None:
    print(f"\n{_c(BOLD + GREEN, '> ')}", end="", flush=True)

def print_assistant_text(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()

def print_tool_call(name: str, inp: dict) -> None:
    icon = _icon(name)
    summary = _summary(name, inp)
    print(f"\n  {_c(YELLOW, icon + ' ' + name)} {_c(DIM, summary)}")

def print_tool_result(name: str, result: str) -> None:
    if name in ("edit_file", "write_file") and not result.startswith("Error"):
        _print_diff(result)
        return
    max_len = 500
    truncated = result if len(result) <= max_len else result[:max_len] + f"\n  ... ({len(result)} chars total)"
    lines = "\n".join("  " + l for l in truncated.split("\n"))
    print(_c(DIM, lines))

def _print_diff(result: str) -> None:
    lines = result.split("\n")
    print(_c(DIM, "  " + lines[0]))
    for line in lines[1:41]:
        if not line.strip():
            continue
        if line.startswith("@@"):
            print(_c(CYAN, "  " + line))
        elif line.startswith("- "):
            print(_c(RED, "  " + line))
        elif line.startswith("+ "):
            print(_c(GREEN, "  " + line))
        else:
            print(_c(DIM, "  " + line))

def print_error(msg: str) -> None:
    print(f"\n  {_c(RED, 'Error: ' + msg)}")

def print_confirmation(command: str) -> None:
    print(f"\n  {_c(YELLOW, 'Dangerous command:')} {_c(WHITE, command)}")

def print_divider() -> None:
    print(f"\n{_c(DIM, '  ' + '-' * 50)}")

def print_cost(input_tokens: int, output_tokens: int) -> None:
    cost = (input_tokens / 1_000_000) * 3 + (output_tokens / 1_000_000) * 15
    print(f"\n{_c(DIM, f'  Tokens: {input_tokens} in / {output_tokens} out (~${cost:.4f})')}")

def print_retry(attempt: int, max_retries: int, reason: str) -> None:
    print(f"\n  {_c(YELLOW, f'Retry {attempt}/{max_retries}: {reason}')}")

def print_info(msg: str) -> None:
    print(f"\n  {_c(CYAN, msg)}")


# 旋转加载指示器

SPINNER_FRAMES = ["|", "/", "-", "\\"]
_spinner_thread: threading.Thread | None = None
_spinner_stop = threading.Event()

def start_spinner(label: str = "Thinking") -> None:
    global _spinner_thread
    if _spinner_thread is not None:
        return
    _spinner_stop.clear()

    def _run() -> None:
        frame = 0
        sys.stdout.write(f"\n  {SPINNER_FRAMES[0]} {label}...")
        sys.stdout.flush()
        while not _spinner_stop.is_set():
            time.sleep(0.1)
            frame = (frame + 1) % len(SPINNER_FRAMES)
            sys.stdout.write(f"\r  {SPINNER_FRAMES[frame]} {label}...")
            sys.stdout.flush()

    _spinner_thread = threading.Thread(target=_run, daemon=True)
    _spinner_thread.start()

def stop_spinner() -> None:
    global _spinner_thread
    if _spinner_thread is None:
        return
    _spinner_stop.set()
    _spinner_thread.join(timeout=1)
    _spinner_thread = None
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


# 工具调用显示，包括图标和摘要

_ICONS = {
    "read_file": "[read]", "write_file": "[write]", "edit_file": "[edit]",
    "list_files": "[list]", "grep_search": "[grep]", "run_shell": "[shell]",
}

def _icon(name: str) -> str:
    return _ICONS.get(name, "[tool]")

def _summary(name: str, inp: dict) -> str:
    if name in ("read_file", "write_file", "edit_file"):
        return inp.get("file_path", "")
    if name == "list_files":
        return inp.get("pattern", "")
    if name == "grep_search":
        return f'"{inp.get("pattern", "")}" in {inp.get("path", ".")}'
    if name == "run_shell":
        cmd = inp.get("command", "")
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    return ""
