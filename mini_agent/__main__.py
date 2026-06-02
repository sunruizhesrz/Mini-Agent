"""Simple Code Agent — preprocess architecture docs then let LLM generate the project."""

import argparse
import asyncio
import os
import signal
import sys

from .agent import Agent
from .ui import print_welcome, print_user_prompt, print_error, print_info


def _load_dotenv():
    """Load .env file from current directory if it exists."""
    env_file = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_file):
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mini-agent", description="Simple Code Agent")
    p.add_argument("prompt", nargs="*", help="Chat mode: one-shot task")
    p.add_argument("--chat", "-c", action="store_true",
                   help="Chat mode: interactive REPL or one-shot task (no preprocessing)")
    p.add_argument("--input-doc", default=None,
                   help="Path to architecture documentation markdown (required for pipeline mode)")
    p.add_argument("--input-view", default=None,
                   help="Path to architecture views / PlantUML markdown (required for pipeline mode)")
    p.add_argument("--output-dir", "-o", default="output")
    p.add_argument("--model", "-m", default=None)
    return p.parse_args()


async def _run_repl(agent: Agent) -> None:
    """Interactive REPL loop for Chat mode."""

    async def _confirm(message: str) -> bool:
        try:
            return input("  Allow? (y/n): ").lower().startswith("y")
        except EOFError:
            return False

    agent.set_confirm_fn(_confirm)

    sigint_count = 0

    def _handle_sigint(sig, frame):
        nonlocal sigint_count
        if agent.is_processing:
            agent.abort()
            print("\n  (interrupted)")
            sigint_count = 0
            print_user_prompt()
        else:
            sigint_count += 1
            if sigint_count >= 2:
                print("\nBye!\n")
                sys.exit(0)
            print("\n  Press Ctrl+C again to exit.")
            print_user_prompt()

    signal.signal(signal.SIGINT, _handle_sigint)
    print_welcome()

    while True:
        print_user_prompt()
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!\n")
            break

        inp = line.strip()
        sigint_count = 0

        if not inp:
            continue
        if inp in ("exit", "quit"):
            print("\nBye!\n")
            break
        if inp == "/clear":
            agent.clear_history()
            continue
        if inp == "/cost":
            agent.show_cost()
            continue
        if inp == "/compact":
            try:
                await agent.compact()
            except Exception as e:
                print_error(str(e))
            continue

        try:
            await agent.chat(inp)
        except Exception as e:
            if "abort" not in str(e).lower():
                print_error(str(e))


def main() -> None:
    args = _parse_args()

    # 加载环境
    _load_dotenv()

    # 配置模型API
    api_base = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        api_base = api_base or os.environ.get("ANTHROPIC_BASE_URL")

    if not api_key:
        print_error("Set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        sys.exit(1)

    model = args.model or os.environ.get("MINI_AGENT_MODEL", "qwen-plus")
    if "anthropic" in (api_base or "").lower() and not args.model:
        model = "claude-opus-4-6"

    # Chat模式：直接与Agent对话，无需预处理阶段
    if args.chat or args.prompt:
        agent = Agent(
            permission_mode="default",
            model=model,
            api_base=api_base,
            api_key=api_key,
        )

        if args.prompt:
            prompt = " ".join(args.prompt)
            try:
                asyncio.run(agent.chat(prompt))
            except Exception as e:
                print_error(str(e))
                sys.exit(1)
        else:
            asyncio.run(_run_repl(agent))
        return

    # 默认模式：预处理架构文档后让Agent生成项目，共有两阶段
    if not args.input_doc or not args.input_view:
        print_error(
            "Pipeline mode requires --input-doc and --input-view.\n"
            "  Usage: python -m mini_agent --input-doc <doc.md> --input-view <view.md>\n"
            "  Or try Chat mode: python -m mini_agent --chat"
        )
        sys.exit(1)

    output_dir = os.path.abspath(args.output_dir)

    # 阶段一: 预处理架构文档 → 生成结构化上下文 + 基础脚手架
    from .generator import run as generate_run

    print_info("Phase 1: Preprocessing architecture docs...")
    try:
        result = generate_run(args.input_doc, args.input_view, output_dir)
        print_info(f"  Extracted: {result['project']}")
        print_info(f"  Files: {result['files']} scaffold files + structured_context.json")
    except FileNotFoundError as e:
        print_error(f"File not found: {e}")
        sys.exit(1)

    # 阶段二: Agent验证项目并修复测试错误（不重新生成文件）
    ctx_path = os.path.join(output_dir, "structured_context.json")
    prompt = f"""You are a Code Agent. Your task: verify a pre-generated project scaffold and fix any remaining issues.

## Phase 1 has already completed — a FULLY GENERATED project exists

A deterministic preprocessor (generator.py) has already:
1. Parsed the architecture documentation (.md files) into `{ctx_path}`
2. Parsed all PlantUML diagrams (class, sequence, deployment, etc.)
3. Generated a COMPLETE, runnable project at `{output_dir}/` — including ALL source code, config files, Dockerfile, tests, and frontend

The Phase 1 generator uses deterministic regex + template logic (NOT an LLM), so its output is consistent and reliable. It has been verified to produce 4/4 passing tests on previous runs.

## Your task: verify and fix (NOT regenerate)

**CRITICAL: Do NOT use write_file to overwrite existing files.** Phase 1 generates correct code; your role is to verify and apply minimal targeted fixes via edit_file. Rewriting entire files with write_file introduces regressions because LLM output varies between runs.

### Step 1 — Quick survey
Use list_files to see the project structure at `{output_dir}/`, then read a few key files to understand the codebase (start with package.json and src/app.js).

Optionally read `{ctx_path}` to understand the architecture specification, but do NOT use it to regenerate files — the files already exist and are correct.

### Step 2 — Syntax check all .js files
Run `node -c` on every .js file:
```bash
for f in $(find {output_dir}/src -name "*.js"); do node -c "$f" && echo "OK: $f" || echo "FAIL: $f"; done
```
If any syntax error is found:
1. **read_file** the failing file to see the current code
2. **edit_file** with a precise, minimal fix (e.g., add a missing closing brace)
3. Re-run `node -c` to confirm the fix
4. Move on — do NOT rewrite the entire file

### Step 3 — Install dependencies
```bash
cd {output_dir} && npm install
```
If install fails:
- Missing package in devDependencies? → **edit_file** to add just that one dependency to package.json, then re-run `npm install`
- Do NOT rewrite the entire package.json

### Step 4 — Run tests and fix failures (ITERATE UNTIL ALL PASS)
```bash
cd {output_dir} && npm test
```

**This is the core loop.** For each test failure:
1. Read the full error output carefully
2. **read_file** the failing test file AND the source file it depends on
3. Diagnose the root cause (see common patterns below)
4. **edit_file** with the minimal fix
5. Re-run `npm test`
6. Repeat until ALL tests pass

**Common failure patterns and their fixes:**

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `Cannot find module '../../src/server'` in test | Test imports wrong path | edit_file the test: change require path to `../src/app` |
| `Cannot find module '../services/xxx.service'` | Wrong relative path in controller | edit_file the controller: fix the require path |
| Test expects `/api/game` but returns 500 | Route prefix mismatch with test expectations | edit_file EITHER the test path OR the route prefix to match |
| `game.service.js` has `throw new Error(...not implemented)` | Phase 1 backup stub was not replaced | edit_file the service: implement the actual logic |
| `Sequelize.sync is not a function` | sequelize instance not exported as expected | read_file database.js first, then fix the import in models |
| Test response body doesn't match expected | Controller returns different shape | read the controller, then edit_file to align test expectation with actual response |
| Route has `/:id` but controller uses `req.query` | Controller doesn't match route params | edit_file the controller: use `req.params.id` instead of `req.query` |
| `npm ci` in Dockerfile fails | No package-lock.json committed | edit_file Dockerfile: change `npm ci` to `npm install --production` |
| `helmet` CSP blocks inline scripts | Missing CSP config | edit_file app.js: add `contentSecurityPolicy: false` to helmet config |

### Step 5 — Verify application startup
```bash
cd {output_dir} && timeout 5 node src/server.js || true
```
If the server crashes:
1. Read the error message
2. **read_file** the file mentioned in the stack trace
3. **edit_file** with the fix
4. Re-test startup

### Step 6 — Report
When all checks pass, report:
- Number of files edited (not rewritten)
- Each fix applied and why
- Final test results (all passing)

---

**CRITICAL CONSTRAINT: You MUST NOT exit until ALL of the following pass:**
1. Every .js file passes `node -c <file>`
2. `npm install` succeeds
3. `npm test` returns all tests passing (e.g. "4 passed, 4 total")
4. `timeout 5 node src/server.js` starts without error

If ANY of these fail, you MUST read the error, apply a minimal edit_file fix, and re-verify. Do NOT exit with failures. Do NOT rewrite entire files — use edit_file for surgical fixes.

Output directory: `{output_dir}/`"""

    print_info("Phase 2: Agent generating project...\n")

    agent = Agent(
        permission_mode="acceptEdits",
        model=model,
        api_base=api_base,
        api_key=api_key,
    )

    try:
        asyncio.run(agent.chat(prompt))
        print_info(f"\nDone. Project generated at {output_dir}/")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
