"""Core agent loop — dual backend (Anthropic + OpenAI/Qwen), streaming, retry, compaction."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Callable, Awaitable

import anthropic
import openai

from .tools import (
    tool_definitions,
    execute_tool,
    check_permission,
    CONCURRENCY_SAFE_TOOLS,
)
from .ui import (
    print_assistant_text,
    print_tool_call,
    print_tool_result,
    print_confirmation,
    print_divider,
    print_cost,
    print_retry,
    print_info,
    start_spinner,
    stop_spinner,
)
from .session import save_session
from .prompt import build_system_prompt


# 带有指数退避的重试机制，针对网络错误和速率限制

def _is_retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 503, 529):
        return True
    msg = str(error)
    return any(kw in msg for kw in ("overloaded", "ECONNRESET", "ETIMEDOUT"))


async def _with_retry(fn, max_retries: int = 3):
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as error:
            if attempt >= max_retries or not _is_retryable(error):
                raise
            delay = min(1000 * (2 ** attempt), 30000) / 1000 + (hash(str(time.time())) % 1000) / 1000
            status = getattr(error, "status_code", None) or getattr(error, "status", None)
            reason = f"HTTP {status}" if status else "network error"
            print_retry(attempt + 1, max_retries, reason)
            await asyncio.sleep(delay)


# 模型上下文窗口大小估算，用于触发自动压缩机制

MODEL_CONTEXT = {
    "claude-opus-4-6": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-haiku-4-5-20251001": 200000,
    "qwen-plus": 131072,
    "qwen-max": 32768,
    "qwen-turbo": 131072,
    "gpt-4o": 128000,
}


def _get_context_window(model: str) -> int:
    for key, val in MODEL_CONTEXT.items():
        if key in model.lower():
            return val
    return 128000


def _max_output_tokens(model: str) -> int:
    m = model.lower()
    if "claude" in m:
        if "opus-4-6" in m:
            return 64000
        if any(x in m for x in ("sonnet-4", "haiku-4", "opus-4")):
            return 32000
    return 8192  # safe default for Qwen/GPT


# Anthropic的工具调用格式与OpenAI函数调用不同，这里做个适配转换

def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


# Agent类封装了与LLM的对话、工具调用、权限检查、自动压缩、会话管理等核心功能，支持OpenAI和Anthropic两种后端，提供统一接口给上层使用。

class Agent:
    def __init__(
        self,
        *,
        permission_mode: str = "default",
        model: str = "qwen-plus",
        api_base: str | None = None,
        api_key: str | None = None,
        thinking: bool = False,
        max_cost_usd: float | None = None,
        max_turns: int | None = None,
        confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.permission_mode = permission_mode
        self.model = model
        self.thinking = thinking
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns
        self.confirm_fn = confirm_fn
        self.use_openai = bool(api_base)
        self.effective_window = _get_context_window(model) - 8000
        self.session_id = uuid.uuid4().hex[:8]
        self.session_start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_token_count = 0
        self.current_turns = 0

        self._aborted = False
        self._current_task: asyncio.Task | None = None
        self._confirmed_paths: set[str] = set()
        self._read_file_state: dict[str, float] = {}
        # In acceptEdits/bypassPermissions mode, skip read-before-write check
        # since files may have been just generated (e.g. pipeline Phase 1 output)
        if permission_mode in ("acceptEdits", "bypassPermissions"):
            self._read_file_state = None  # None disables the check

        # 构建系统提示，包含工具定义和权限模式说明
        self._system_prompt = build_system_prompt()

        # 根据是否提供api_base来决定使用OpenAI还是Anthropic客户端，并初始化消息列表
        if self.use_openai:
            self._openai_client = openai.AsyncOpenAI(
                base_url=api_base,
                api_key=api_key,
            )
            self._anthropic_client = None
            # OpenAI模式下，系统提示作为第一条消息固定存在，方便后续压缩时保留
            self._messages: list[dict] = [
                {"role": "system", "content": self._system_prompt}
            ]
        else:
            self._openai_client = None
            kwargs: dict = {}
            if api_key:
                kwargs["api_key"] = api_key
            if api_base:
                kwargs["base_url"] = api_base
            self._anthropic_client = anthropic.AsyncAnthropic(**kwargs)
            self._messages: list[dict] = []

    @property
    def is_processing(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    def abort(self) -> None:
        self._aborted = True
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]]) -> None:
        self.confirm_fn = fn

    def get_token_usage(self) -> dict:
        return {"input": self.total_input_tokens, "output": self.total_output_tokens}

    # 主聊天接口

    async def chat(self, user_message: str) -> None:
        self._aborted = False
        coro = self._chat(user_message)
        self._current_task = asyncio.current_task()
        try:
            await coro
        except asyncio.CancelledError:
            self._aborted = True
        finally:
            self._current_task = None
        print_divider()
        self._auto_save()

    # 工具调用相关接口

    def clear_history(self) -> None:
        self._messages = []
        if self.use_openai:
            self._messages.append({"role": "system", "content": self._system_prompt})
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_token_count = 0
        print_info("Conversation cleared.")

    def show_cost(self) -> None:
        total = (self.total_input_tokens / 1_000_000) * 3 + (self.total_output_tokens / 1_000_000) * 15
        budget_info = f" / ${self.max_cost_usd} budget" if self.max_cost_usd else ""
        turn_info = f" | Turns: {self.current_turns}/{self.max_turns}" if self.max_turns else ""
        print_info(f"Tokens: {self.total_input_tokens} in / {self.total_output_tokens} out\n  Estimated cost: ${total:.4f}{budget_info}{turn_info}")

    async def compact(self) -> None:
        await self._compact()

    # 会话管理接口
    def restore_session(self, data: dict) -> None:
        if data.get("messages"):
            self._messages = data["messages"]
            print_info(f"Session restored ({len(self._messages)} messages).")

    def _auto_save(self) -> None:
        try:
            save_session(self.session_id, {
                "metadata": {
                    "id": self.session_id,
                    "model": self.model,
                    "cwd": str(Path.cwd()),
                    "startTime": self.session_start_time,
                    "messageCount": len(self._messages),
                },
                "messages": self._messages,
            })
        except Exception:
            pass

    # 自动压缩

    async def _check_and_compact(self) -> None:
        if self.last_input_token_count > self.effective_window * 0.85:
            print_info("Context window filling up, compacting...")
            await self._compact()

    async def _compact(self) -> None:
        if self.use_openai:
            await self._compact_openai()
        else:
            await self._compact_anthropic()
        print_info("Conversation compacted.")

    async def _compact_openai(self) -> None:
        if len(self._messages) < 5:
            return
        system_msg = self._messages[0]
        last_msg = self._messages[-1]
        resp = await self._openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer. Be concise."},
                *self._messages[1:-1],
                {"role": "user", "content": "Summarize the conversation in a concise paragraph, preserving key decisions, file paths, and context."},
            ],
        )
        summary = resp.choices[0].message.content or "No summary available."
        self._messages = [
            system_msg,
            {"role": "user", "content": f"[Previous conversation summary]\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from our previous conversation."},
        ]
        if last_msg.get("role") == "user":
            self._messages.append(last_msg)
        self.last_input_token_count = 0

    async def _compact_anthropic(self) -> None:
        if len(self._messages) < 4:
            return
        last_msg = self._messages[-1]
        resp = await self._anthropic_client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="You are a conversation summarizer. Be concise but preserve important details.",
            messages=[
                *self._messages[:-1],
                {"role": "user", "content": "Summarize the conversation so far in a concise paragraph, preserving key decisions, file paths, and context."},
            ],
        )
        summary = "".join(b.text for b in resp.content if b.type == "text") or "No summary available."
        self._messages = [
            {"role": "user", "content": f"[Previous conversation summary]\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from our previous conversation."},
        ]
        if last_msg.get("role") == "user":
            self._messages.append(last_msg)
        self.last_input_token_count = 0

    # 核心聊天逻辑

    async def _chat(self, user_message: str) -> None:
        if self.use_openai:
            await self._chat_openai(user_message)
        else:
            await self._chat_anthropic(user_message)

    # Anthropic后端的聊天实现，包含工具调用的特殊处理逻辑

    async def _chat_anthropic(self, user_message: str) -> None:
        self._messages.append({"role": "user", "content": user_message})
        await self._check_and_compact()

        while True:
            if self._aborted:
                break

            start_spinner()

            early_executions: dict[str, asyncio.Task] = {}

            def _on_tool_block(block: dict) -> None:
                if block["name"] in CONCURRENCY_SAFE_TOOLS:
                    perm = check_permission(block["name"], block["input"], self.permission_mode)
                    if perm["action"] == "allow":
                        task = asyncio.create_task(execute_tool(block["name"], block["input"], self._read_file_state))
                        early_executions[block["id"]] = task

            response = await self._call_anthropic_stream(on_tool_block_complete=_on_tool_block)
            stop_spinner()

            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.last_input_token_count = response.usage.input_tokens

            tool_uses = [b for b in response.content if b.type == "tool_use"]

            self._messages.append({
                "role": "assistant",
                "content": [_anth_block_to_dict(b) for b in response.content if b.type != "thinking"],
            })

            if not tool_uses:
                print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            self.current_turns += 1
            if self.max_turns and self.current_turns >= self.max_turns:
                print_info(f"Turn limit reached ({self.current_turns} >= {self.max_turns})")
                break

            tool_results: list[dict] = []
            for tu in tool_uses:
                if self._aborted:
                    break
                inp = dict(tu.input) if hasattr(tu.input, 'items') else tu.input
                print_tool_call(tu.name, inp)

                early_task = early_executions.get(tu.id)
                if early_task:
                    raw = await early_task
                    res = _persist_large_result(tu.name, raw)
                    print_tool_result(tu.name, res)
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})
                    continue

                perm = check_permission(tu.name, inp, self.permission_mode)
                if perm["action"] == "deny":
                    print_info(f"Denied: {perm.get('message', '')}")
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"Action denied: {perm.get('message', '')}"})
                    continue
                if perm["action"] == "confirm" and perm.get("message") and perm["message"] not in self._confirmed_paths:
                    confirmed = await self._confirm_dangerous(perm["message"])
                    if not confirmed:
                        tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "User denied this action."})
                        continue
                    self._confirmed_paths.add(perm["message"])

                raw = await execute_tool(tu.name, inp, self._read_file_state)
                res = _persist_large_result(tu.name, raw)
                print_tool_result(tu.name, res)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})

            if tool_results:
                self._messages.append({"role": "user", "content": tool_results})

    async def _call_anthropic_stream(self, on_tool_block_complete=None):
        async def _do():
            max_output = _max_output_tokens(self.model)
            create_params: dict = {
                "model": self.model,
                "max_tokens": max_output,
                "system": self._system_prompt,
                "tools": [{k: v for k, v in t.items()} for t in tool_definitions],
                "messages": self._messages,
            }

            first_text = True
            tool_blocks: dict[int, dict] = {}

            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for event in stream:
                    if not hasattr(event, 'type'):
                        continue

                    if event.type == "content_block_start":
                        cb = getattr(event, 'content_block', None)
                        if cb and getattr(cb, 'type', None) == "tool_use":
                            tool_blocks[event.index] = {"id": cb.id, "name": cb.name, "input_json": ""}

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, 'text'):
                            if first_text:
                                stop_spinner()
                                print_assistant_text("\n")
                                first_text = False
                            print_assistant_text(delta.text)
                        elif hasattr(delta, 'partial_json'):
                            tb = tool_blocks.get(event.index)
                            if tb:
                                tb["input_json"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        tb = tool_blocks.pop(event.index, None)
                        if tb and on_tool_block_complete:
                            try:
                                parsed = json.loads(tb["input_json"] or "{}")
                            except json.JSONDecodeError:
                                parsed = {}
                            on_tool_block_complete({"type": "tool_use", "id": tb["id"], "name": tb["name"], "input": parsed})

                return await stream.get_final_message()

        return await _with_retry(_do)

    # OpenAI后端的聊天实现，包含工具调用的特殊处理逻辑

    async def _chat_openai(self, user_message: str) -> None:
        self._messages.append({"role": "user", "content": user_message})
        await self._check_and_compact()

        while True:
            if self._aborted:
                break

            start_spinner()
            response = await self._call_openai_stream()
            stop_spinner()

            if response.get("usage"):
                self.total_input_tokens += response["usage"]["prompt_tokens"]
                self.total_output_tokens += response["usage"]["completion_tokens"]
                self.last_input_token_count = response["usage"]["prompt_tokens"]

            choice = response.get("choices", [{}])[0] if response.get("choices") else {}
            message = choice.get("message", {})

            self._messages.append(message)

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            self.current_turns += 1
            if self.max_turns and self.current_turns >= self.max_turns:
                print_info(f"Turn limit reached ({self.current_turns} >= {self.max_turns})")
                break

            # 阶段一：权限检查，收集工具调用信息，并行安全的工具调用可以先行执行
            oai_checked: list[dict] = []
            for tc in tool_calls:
                if self._aborted:
                    break
                if tc.get("type") != "function":
                    continue
                fn_name = tc["function"]["name"]
                try:
                    inp = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    # LLM produced malformed JSON → tell it to retry
                    oai_checked.append({
                        "tc": tc, "fn": fn_name, "inp": {},
                        "allowed": False,
                        "result": f"Error: failed to parse arguments. Please output valid JSON."
                    })
                    continue

                print_tool_call(fn_name, inp)

                perm = check_permission(fn_name, inp, self.permission_mode)
                if perm["action"] == "deny":
                    print_info(f"Denied: {perm.get('message', '')}")
                    oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False, "result": f"Action denied: {perm.get('message', '')}"})
                    continue
                if perm["action"] == "confirm" and perm.get("message") and perm["message"] not in self._confirmed_paths:
                    confirmed = await self._confirm_dangerous(perm["message"])
                    if not confirmed:
                        oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False, "result": "User denied this action."})
                        continue
                    self._confirmed_paths.add(perm["message"])
                oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": True})

            # 阶段二：执行工具调用，安全的可以并行执行，其他的依次执行，收集结果并追加到消息列表中供下一轮对话使用
            oai_batches: list[dict] = []
            for ct in oai_checked:
                safe = ct["allowed"] and ct["fn"] in CONCURRENCY_SAFE_TOOLS
                if safe and oai_batches and oai_batches[-1]["concurrent"]:
                    oai_batches[-1]["items"].append(ct)
                else:
                    oai_batches.append({"concurrent": safe, "items": [ct]})

            for batch in oai_batches:
                if self._aborted:
                    break
                if batch["concurrent"]:
                    async def _run_safe(ct_item: dict) -> tuple[dict, str]:
                        raw = await execute_tool(ct_item["fn"], ct_item["inp"], self._read_file_state)
                        res = _persist_large_result(ct_item["fn"], raw)
                        print_tool_result(ct_item["fn"], res)
                        return ct_item, res

                    results = await asyncio.gather(*[_run_safe(ct) for ct in batch["items"]])
                    for ct_item, res in results:
                        self._messages.append({"role": "tool", "tool_call_id": ct_item["tc"]["id"], "content": res})
                else:
                    for ct in batch["items"]:
                        if not ct["allowed"]:
                            self._messages.append({"role": "tool", "tool_call_id": ct["tc"]["id"], "content": ct["result"]})
                            continue
                        raw = await execute_tool(ct["fn"], ct["inp"], self._read_file_state)
                        res = _persist_large_result(ct["fn"], raw)
                        print_tool_result(ct["fn"], res)
                        self._messages.append({"role": "tool", "tool_call_id": ct["tc"]["id"], "content": res})

    async def _call_openai_stream(self) -> dict:
        async def _do():
            stream = await self._openai_client.chat.completions.create(
                model=self.model,
                tools=_to_openai_tools(tool_definitions),
                messages=self._messages,
                stream=True,
                stream_options={"include_usage": True},
            )

            content = ""
            first_text = True
            tool_calls: dict[int, dict] = {}
            finish_reason = ""
            usage = None

            async for chunk in stream:
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta and delta.content:
                    if first_text:
                        stop_spinner()
                        print_assistant_text("\n")
                        first_text = False
                    print_assistant_text(delta.content)
                    content += delta.content

                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        existing = tool_calls.get(tc.index)
                        if existing:
                            if tc.function and tc.function.arguments:
                                existing["arguments"] += tc.function.arguments
                        else:
                            tool_calls[tc.index] = {
                                "id": tc.id or "",
                                "name": (tc.function.name if tc.function else "") or "",
                                "arguments": (tc.function.arguments if tc.function else "") or "",
                            }

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

            assembled = None
            if tool_calls:
                assembled = [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for _, tc in sorted(tool_calls.items())
                ]

            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": assembled,
                    },
                    "finish_reason": finish_reason or "stop",
                }],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }

        return await _with_retry(_do)

    # 对于需要用户确认的敏感操作，调用这个函数来获取确认结果

    async def _confirm_dangerous(self, command: str) -> bool:
        print_confirmation(command)
        if self.confirm_fn:
            return await self.confirm_fn(command)
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False


# Anthropic的消息块格式转换成统一的字典格式，方便后续处理和打印。对于文本块直接提取文本，对于工具调用块提取工具名、输入等信息，其他类型的块则保留类型信息。

def _anth_block_to_dict(block) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        inp = dict(block.input) if hasattr(block.input, 'items') else block.input
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": inp}
    return {"type": block.type}


def _persist_large_result(tool_name: str, result: str) -> str:
    THRESHOLD = 30 * 1024  # 30 KB
    if len(result.encode()) <= THRESHOLD:
        return result
    d = Path.home() / ".mini-agent" / "tool-results"
    d.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time() * 1000)}-{tool_name}.txt"
    filepath = d / filename
    filepath.write_text(result, encoding="utf-8")
    lines = result.split("\n")
    preview = "\n".join(lines[:200])
    size_kb = len(result.encode()) / 1024
    return (
        f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines). "
        f"Full output saved to {filepath}. Use read_file to see the full result.]\n\n"
        f"Preview (first 200 lines):\n{preview}"
    )
