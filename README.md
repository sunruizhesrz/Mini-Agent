<div align="center">
  <h1 align="center"><span style="font-family: Consolas;">Mini Agent</span>: A Simple Code Agent Built from Scratch</h1>
</div>

<div align="center">
    <a href="https://github.com/sunruizhesrz/Mini-Agent">
        <img src="https://img.shields.io/badge/GitHub-000?logo=github&logoColor=FFE165&style=for-the-badge" alt="">
    </a>
    <a href="https://github.com/Windy3f3f3f3f/claude-code-from-scratch">
        <img src="https://img.shields.io/badge/Reference-claude--code--from--scratch-000?logo=github&style=for-the-badge" alt="">
    </a>
    <hr>
</div>

## 📖 Overview

**<span style="font-family: Consolas;">Mini Agent</span>** is a simple Code Agent built after studying the open-source implementation mechanisms of Claude Code.
It implements an LLM-driven Agent Loop (while True + LLM decision + tool execution) and a universal preprocessor
that transforms architecture documentation into complete, runnable web applications — including REST API backend, database models, and an interactive HTML/CSS/JS frontend.

The project consists of **~2,300 lines of Python across 7 source files**, supporting both a pipeline mode
(architecture documents → project scaffold) and a Chat mode (interactive coding assistant).

```
.md docs → [Phase 1: generator.py] → JSON → [Phase 2: agent.py] → project files
              regex engine                      LLM Agent Loop
```

## ✨ Features

- **Agent Loop**: Implements the core Claude Code mechanism — `while True` loop with LLM decision-making and autonomous tool invocation
- **Universal Preprocessor**: Adaptive Markdown + PlantUML parser with language detection (Node.js, Python, Go, Java, Rust) and full code generation for Node.js (Express, Koa) and Python (Django, Flask, FastAPI)
- **6-Tool System**: read_file, write_file, edit_file, list_files, grep_search, run_shell — with permission checks and read-before-write protection
- **4 Permission Modes**: default / acceptEdits / bypassPermissions / dontAsk — mirroring Claude Code's security framework
- **Dual Backend**: OpenAI-compatible API (Qwen / GPT) and native Anthropic API
- **Pipeline Mode**: Two-phase architecture — Phase 1 (generator) produces a fully runnable web application with an interactive frontend (fraction quiz game) and REST API backend (4/4 tests pass with PostgreSQL). Phase 2 (LLM) optionally enhances quality via self-verification loop (syntax check → test → fix → re-test)
- **Chat Mode**: Interactive REPL with streaming output, context compaction, and session persistence

------

## 🚀 Quick Start

### Environment Setup
Follow these steps to set up the environment for <span style="font-family: Consolas;">Mini Agent</span>:

```shell
git clone https://github.com/sunruizhesrz/Mini-Agent.git
cd Mini-Agent
pip install -e .
```

### API Key Configuration
Create a `.env` file in the project directory (auto-loaded on startup):

```shell
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### Pipeline Mode — Architecture Docs → Project Scaffold

```shell
python -m mini_agent \
  --input-doc ./example/Architecture_Documentation.md \
  --input-view ./example/Architecture_View.md \
  --output-dir ./output \
  --model qwen-max
```

**Phase 1** (0.2s, zero API cost): The preprocessor produces a **fully runnable** project — 4/4 tests pass with PostgreSQL. No LLM required.
**Phase 2** (optional, requires API): The LLM reads `structured_context.json`, enhances code, then self-verifies via a `syntax check → test → fix → re-test` loop.

### Chat Mode — Interactive Coding Assistant

```shell
python -m mini_agent --chat                      # Interactive REPL
python -m mini_agent --chat "Fix the bug in app.py"  # One-shot task
```

REPL commands: `/clear` (clear history), `/cost` (show token usage), `/compact` (compress context), `exit`

------

## 🏗️ Architecture

```
                      ┌──────────────────────────────┐
                      │  Phase 1: generator.py        │
                      │  (deterministic, 0.2s)         │
                      │                              │
  --input-doc ───────→│ parse_arch_doc()              │
  (Markdown)          │   adaptive section splitting  │
                      │   white-list tech detection   │
                      │                              │
  --input-view ──────→│ parse_arch_view()             │
  (PlantUML)          │   class/field/method/relation │
                      │                              │
                      │ merge_to_json()               │
                      │ generate_project()             │
                      │   language detection           │
                      │   framework selection          │
                      │   dynamic dependency matching  │
                      │   → runnable project (38 files) │
                      └──────────┬───────────────────┘
                                 │
                      ┌──────────▼───────────────────┐
                      │  Phase 2: agent.py (optional) │
                      │  (LLM Agent Loop, 2–5 min)     │
                      │                              │
                      │ while True:                   │
                      │   LLM → which tool to call?   │
                      │   execute tool → feed result   │
                      │   node -c → syntax check       │
                      │   npm test → failures? → fix   │
                      │   all pass? → done             │
                      └──────────────────────────────┘
```

------

## 📋 Repository Structure

```plaintext
├── mini_agent/                 # Source code (7 files, ~2,400 lines)
│   ├── __init__.py
│   ├── __main__.py             # CLI entry: pipeline / Chat dispatch
│   ├── generator.py            # Universal preprocessor: .md → JSON (1,650 lines)
│   ├── agent.py                # Agent Loop + dual-backend LLM calls (640 lines)
│   ├── tools.py                # 6 tools + permission system (370 lines)
│   ├── prompt.py               # System prompt builder (150 lines)
│   ├── session.py              # Session persistence (40 lines)
│   └── ui.py                   # Terminal rendering (140 lines)
├── example/                    # Example architecture documents (Space Fractions)
│   ├── Architecture_Documentation.md
│   └── Architecture_View.md
├── output/                     # Generated project (runnable Node.js web app)
│   ├── src/                    # Express backend + interactive frontend
│   ├── tests/                  # 4 passing Jest tests
│   └── Dockerfile              # Docker deployment
├── pyproject.toml              # Python project configuration
├── .env.example                # API key configuration template
└── README.md                   # This document
```

### Module Dependencies

```
tools.py  ← zero external dependencies, defines 6 tools
    ↑
agent.py  ← tools + prompt + ui + session
generator.py ← stdlib only (re + pathlib)
    ↑         ↑
    └────┬────┘
   __main__.py  ← dispatches to pipeline / Chat mode
```

------

## ✅ Verifying the Output

The generated project is fully runnable. To verify:

```bash
cd output

# 1. Syntax check all files
for f in $(find src -name "*.js"); do node -c "$f" && echo "OK: $f"; done

# 2. Install and test
npm install
DATABASE_URL="postgresql://localhost:5432/testdb" npx jest --forceExit
# Result: 4 passed, 4 total

# 3. Start the server
node src/server.js
```

Requirements: Node.js 18+ and PostgreSQL (or use `docker compose up -d`).

Open `http://localhost:3000/` in a browser to play the interactive fraction quiz game.

------

## 🔧 Tool System

| Tool | Description | Safety |
|------|-------------|:------:|
| `read_file` | Read file content with line numbers + absolute path | Read-only |
| `write_file` | Create/overwrite files (auto mkdir -p) | Write |
| `edit_file` | Exact string replacement with diff output | Write |
| `list_files` | Glob pattern file matching | Read-only |
| `grep_search` | Regex search (system grep + Python fallback) | Read-only |
| `run_shell` | Execute shell commands (30s timeout protection) | Write |

Tools are OpenAI Function Calling / Anthropic Tool Use compatible. Read-only tools execute in parallel.

------

## ⚙️ Configuration

| Parameter | Description |
|-----------|-------------|
| `--input-doc <path>` | Architecture documentation **(required for pipeline)** |
| `--input-view <path>` | Architecture views / PlantUML **(required for pipeline)** |
| `--output-dir <dir>` / `-o` | Output directory (default: `output`) |
| `--model <name>` / `-m` | LLM model (default: `qwen-plus`) |
| `--chat` / `-c` | Chat mode |

| Environment (.env) | Description |
|---------------------|-------------|
| `OPENAI_API_KEY` | API Key (OpenAI / Qwen) |
| `OPENAI_BASE_URL` | API base URL |
| `ANTHROPIC_API_KEY` | Anthropic API Key |

------

## 📝 Acknowledgments

This project references the following open-source works:

| Project | Role |
|----------|------|
| [claude-code-from-scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch) | Agent Loop + tool system reference implementation |
| [how-claude-code-works](https://github.com/Windy3f3f3f3f/how-claude-code-works) | Claude Code architecture analysis |
| [claw-code](https://github.com/ultraworkers/claw-code) | Rust clean-room reimplementation |
| [anthropics/claude-code](https://github.com/anthropics/claude-code) | Official Claude Code repository |
