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

    # 阶段二: Agent读取结构化上下文 → 生成完整项目
    ctx_path = os.path.join(output_dir, "structured_context.json")
    prompt = f"""You are a Code Agent. Your task: read a structured architecture specification and generate a complete project scaffold.

## Phase 1 has already completed

A preprocessor has:
1. Parsed the architecture documentation (.md files)
2. Extracted structured information into `{ctx_path}`
3. Generated a basic scaffold at `{output_dir}/` with package.json, config files, and placeholder source code

## Your task

1. **Read the structured context**: Use read_file to read `{ctx_path}`. This JSON contains:
   - `project_name`, `architectural_style`, `stack` (tech stack: lang, fw, db, cache...)
   - `classes` (all entities from PlantUML diagrams with their fields and methods)
   - `relations` (relationships between classes: composition, association, message)
   - `tables` (SQL table definitions with columns and types)
   - `endpoints` (API paths and methods from OpenAPI specs)
   - `k8s_resources` (Kubernetes deployment configs)
   - `traceability` (requirements-to-components mapping)

2. **Review the existing scaffold**: Use list_files and read_file to inspect what the preprocessor already created in `{output_dir}/`.

3. **Generate the COMPLETE project**. Read `{ctx_path}` first, then for every class and table, create proper source files:

### For each class (Game, Question, User, Admin):
- **Model** (`src/{{module}}/models/`): Sequelize model. Use SQL table columns if available, otherwise use PlantUML class fields. Map types correctly (SERIAL→INTEGER, JSONB→JSONB, string→STRING, int→INTEGER, List<T>→ARRAY).
- **Service** (`src/{{module}}/services/`): Implement EVERY method from the PlantUML class diagram. Do NOT leave TODO stubs — write actual logic with proper error handling.
- **Controller** (`src/{{module}}/controllers/`): Wire service methods to Express request/response with try-catch blocks.
- **Route** (`src/{{module}}/routes/`): Map API endpoints from structured_context to controller methods. Add full CRUD routes for each module.

### Relations & Foreign Keys:
- If ClassA --* ClassB (composition), add a foreign key field (e.g., `game_id`) to ClassB's model.

### Config files:
- **package.json**: Dependencies must match the tech stack (PostgreSQL→pg+sequelize, Redis→ioredis, RabbitMQ→amqplib).
- **Dockerfile**: Multi-stage build, non-root user, healthcheck, node:18-alpine base.
- **docker-compose.yml**: App + PostgreSQL + Redis services.
- **README.md**: Project description, architecture overview, tech stack table, full API endpoint table, getting started guide.
- **api/openapi.yaml**: Complete OpenAPI 3.0 spec based on endpoints from structured_context.
- **k8s/deployment.yaml**: Kubernetes deployment from k8s_resources in the context.
- **sql/*.sql**: CREATE TABLE statements from tables in the context.
- **Tests**: One test file per module, testing all endpoints.
- **.env.example** and **.gitignore**.

### Quality:
- Consistent import paths (no broken requires)
- snake_case table names, camelCase JS variables
- Clean formatting
- Meaningful comments

4. **Verify and self-fix**: This is the MOST IMPORTANT step. After generating files, you MUST verify them and fix any errors:

### Phase A: Syntax check every generated file
Run this for EVERY .js file you created or edited:
```bash
node -c {output_dir}/src/game/models/game.model.js
```
If it reports a syntax error, read the file, fix it, and re-check. Repeat until clean.

### Phase B: Install and test
After ALL syntax checks pass:
```bash
cd {output_dir} && npm install
```
If install fails with "missing supertest" or other missing packages, add them to package.json devDependencies and re-run `npm install`.
Then run the tests:
```bash
cd {output_dir} && npm test
```
If any test fails, read the error output carefully, find the root cause (missing controller method? wrong table name? broken import?), fix the source file, and re-run `npm test`. Repeat until ALL tests pass.

### Phase C: Application startup
After tests pass:
```bash
cd {output_dir} && timeout 5 node src/server.js || true
```
If the server crashes with a require error or Sequelize error, fix it and re-test.
Also check that `sequelize.sync()` is called during startup — if not, add it.

### Common errors to proactively fix:
- Routes reference `controller.getAll` but the controller only has custom methods → add `getAll` and `getById` to the controller
- `npm ci` in Dockerfile but no `package-lock.json` exists → change to `npm install --production`
- SQL table name is `games` but Sequelize model says `tableName: 'project_games'` → make them match
- Controller uses `req.params` but the route has no parameters → use `req.query` or `req.body` instead
- Tests require `supertest` but it's not in devDependencies → add it

5. **Report**: When done, list every file you created or modified AND the test results showing all tests passing.

Output directory: `{output_dir}/`

Begin by reading `{ctx_path}`. Then generate, test, fix, and re-test until everything passes.

**CRITICAL CONSTRAINT: You MUST NOT exit until ALL of the following pass:**
1. Every .js file passes `node -c <file>`
2. `npm install` succeeds
3. `npm test` returns "4 passed, 4 total" (or equivalent for the detected language)
4. `timeout 5 node src/server.js` starts without error (or equivalent for the detected language)

If ANY of these fail, you MUST read the error, fix the source file, and re-verify. Do NOT exit with failures. This is a hard requirement."""

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
