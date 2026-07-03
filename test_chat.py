#!/usr/bin/env python3
"""
SkipperBot Chat Test Harness
=============================
Simulates full chat conversations with the same system prompts, tools,
memory, knowledge, and guides as the live agent — but in a CLI.

Usage:
  Interactive mode:
    python3 test_chat.py
    python3 test_chat.py --user alice

  Scripted mode (pipe messages):
    echo "show me g3" | python3 test_chat.py
    printf "show me g3\\nshow me p1\\n" | python3 test_chat.py

  Verbose mode (show tool calls, routing, etc.):
    python3 test_chat.py -v

  Show system prompt:
    python3 test_chat.py --show-prompt

  Dry-run (show tool routing + tools selected, but don't call LLM):
    python3 test_chat.py --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
import time

# Ensure project root is importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from config import logger, load_system_prompt, get_dynamic_system_context
# Dev harness (out of scope for the provider-neutral product path): resolve the SMART tier's
# connector+model+key (MODEL_FLEXIBILITY #44/#71) instead of the removed config.openai_client /
# the OPENAI_API_KEY env assumption. The connector's own client factory threads the per-tier key.
from providers.tier_resolver import resolve_chat as _resolve_chat
_smart_provider, OPENAI_MODEL, _smart_key = _resolve_chat("smart")
openai_client = _smart_provider._get_client(_smart_key)
import mcp_client
from local_tools import LOCAL_TOOLS, LOCAL_TOOL_NAMES, handle_local_tool
from memory_store import get_relevant_memories, format_memories_for_context, MEMORY_FILE, get_embedding
from knowledge_store import get_relevant_knowledge, format_knowledge_for_context, CHUNKS_FILE
from chatlog_store import generate_turn_id
from tool_router import (
    get_tools_for_message, get_guides_for_message,
    get_category_tool_names, META_TOOL_NAMES, _match_categories,
)

# ---------------------------------------------------------------------------
# ANSI colors for readable output
# ---------------------------------------------------------------------------
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


def _trunc(s: str, n: int = 200) -> str:
    return s[:n] + "..." if len(s) > n else s


# ---------------------------------------------------------------------------
# Core test harness
# ---------------------------------------------------------------------------
class ChatTestHarness:
    def __init__(self, user_id: str = "alice", verbose: bool = False, dry_run: bool = False):
        self.user_id = user_id
        self.verbose = verbose
        self.dry_run = dry_run
        self.session: list[dict] = []
        self.mcp_connected = False

    async def connect_mcp(self):
        """Connect to MCP server and fetch tools."""
        if self.mcp_connected:
            return
        print(f"{C.DIM}Connecting to MCP server...{C.RESET}")
        try:
            tools = await mcp_client.connect_to_mcp()
            print(f"{C.GREEN}MCP connected: {len(tools)} tools available{C.RESET}")
            self.mcp_connected = True
        except Exception as e:
            print(f"{C.RED}MCP connection failed: {e}{C.RESET}")
            print(f"{C.YELLOW}Continuing without MCP tools (local tools only){C.RESET}")

    def show_system_prompt(self):
        """Print the full system prompt."""
        prompt = load_system_prompt(self.user_id)
        print(f"\n{C.CYAN}{'='*60}")
        print(f"SYSTEM PROMPT ({len(prompt)} chars)")
        print(f"{'='*60}{C.RESET}")
        print(prompt)
        print(f"{C.CYAN}{'='*60}{C.RESET}\n")

    async def send(self, user_message: str) -> str:
        """Send a message through the full chat pipeline and return the response."""
        print(f"\n{C.BOLD}{C.BLUE}USER [{self.user_id}]:{C.RESET} {user_message}")
        print(f"{C.DIM}{'─'*60}{C.RESET}")

        if not self.mcp_connected and not self.dry_run:
            await self.connect_mcp()

        self.session.append({"role": "user", "content": user_message})

        current_turn_id = generate_turn_id()

        # ── Build system prompt ──
        system_prompt = load_system_prompt(self.user_id)
        system_prompt += f"\n\n{get_dynamic_system_context(self.user_id)}"
        system_prompt += f"\n\nCurrent chat turn ID: {current_turn_id}"

        # ── Memory + knowledge retrieval ──
        has_memories = os.path.exists(MEMORY_FILE) and os.path.getsize(MEMORY_FILE) > 0
        has_knowledge = os.path.exists(CHUNKS_FILE) and os.path.getsize(CHUNKS_FILE) > 0

        t0 = time.monotonic()
        shared_embedding = None
        if has_memories or has_knowledge:
            try:
                shared_embedding = get_embedding(user_message)
            except Exception as e:
                print(f"{C.YELLOW}  Embedding failed: {e}{C.RESET}")

        relevant = get_relevant_memories(user_message, user_id=self.user_id, query_embedding=shared_embedding) if has_memories else []
        knowledge_chunks = get_relevant_knowledge(user_message, query_embedding=shared_embedding) if has_knowledge else []
        t_retrieval = time.monotonic() - t0

        memory_context = format_memories_for_context(relevant)
        knowledge_context = format_knowledge_for_context(knowledge_chunks)

        if memory_context:
            system_prompt += "\n\n" + memory_context
        if knowledge_context:
            system_prompt += "\n\n" + knowledge_context

        if self.verbose:
            print(f"{C.DIM}  Retrieval: {t_retrieval:.2f}s | {len(relevant)} memories | {len(knowledge_chunks)} knowledge chunks{C.RESET}")

        # ── Tool routing ──
        context_window = self.session[-20:]
        context_text = user_message + "\n" + "\n".join(
            m["content"] for m in context_window if m.get("content")
        )
        matched_cats = _match_categories(context_text)
        routed_tool_names = get_tools_for_message(context_text)

        guide_content = get_guides_for_message(context_text)
        if guide_content:
            system_prompt += "\n\n" + guide_content

        print(f"{C.MAGENTA}  Categories: {sorted(matched_cats)}{C.RESET}")
        print(f"{C.MAGENTA}  Tools ({len(routed_tool_names)}): {sorted(routed_tool_names)}{C.RESET}")
        if guide_content and self.verbose:
            guide_names = [line.split("# ")[1] for line in guide_content.split("\n") if line.startswith("# ")]
            print(f"{C.MAGENTA}  Guides injected: {guide_names}{C.RESET}")

        if self.dry_run:
            print(f"{C.YELLOW}  [DRY RUN — skipping LLM call]{C.RESET}")
            return "(dry run)"

        # ── Build tool list ──
        allowed = routed_tool_names | META_TOOL_NAMES
        extra_categories: set[str] = set()

        def _build_tools():
            all_allowed = allowed.copy()
            for cat in extra_categories:
                all_allowed |= get_category_tool_names(cat)
            mcp_tools = []
            if mcp_client.mcp_tools:
                all_mcp = mcp_client.get_openai_tools()
                mcp_tools = [t for t in all_mcp if t["function"]["name"] in all_allowed]
            local_tools = [t for t in LOCAL_TOOLS if t["function"]["name"] in all_allowed]
            return (mcp_tools + local_tools) or None

        tools = _build_tools()

        # ── Messages ──
        messages = [
            {"role": "system", "content": system_prompt},
            *self.session,
        ]

        # ── First LLM call ──
        total_prompt = 0
        total_completion = 0
        t_llm = time.monotonic()

        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
        )
        t_llm_done = time.monotonic() - t_llm

        if completion.usage:
            total_prompt += completion.usage.prompt_tokens
            total_completion += completion.usage.completion_tokens

        if self.verbose:
            print(f"{C.DIM}  LLM call 1: {t_llm_done:.2f}s | {total_prompt:,} in / {total_completion:,} out{C.RESET}")

        assistant_message = completion.choices[0].message
        tool_loop = 0
        direct_display_sent = None

        # ── Tool loop ──
        while assistant_message.tool_calls:
            tool_loop += 1
            messages.append(assistant_message)

            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                print(f"{C.CYAN}  ⚡ TOOL [{tool_loop}]: {tool_name}({json.dumps(tool_args, ensure_ascii=False)}){C.RESET}")

                t_tool = time.monotonic()
                if tool_name in LOCAL_TOOL_NAMES:
                    tool_result = await handle_local_tool(tool_name, tool_args, from_user=self.user_id)
                else:
                    tool_result = await mcp_client.call_mcp_tool(tool_name, tool_args, chat_turn_id=current_turn_id)
                t_tool_done = time.monotonic() - t_tool

                # Direct display handling
                if tool_result and tool_result.lstrip().startswith('{"__direct_display__"'):
                    try:
                        dd = json.loads(tool_result)
                        if isinstance(dd, dict) and dd.get("__direct_display__"):
                            display = dd.get("display", "")
                            print(f"\n{C.GREEN}  ┌── DIRECT DISPLAY ──{C.RESET}")
                            for line in display.split("\n"):
                                print(f"{C.GREEN}  │ {line}{C.RESET}")
                            print(f"{C.GREEN}  └─────────────────────{C.RESET}")
                            direct_display_sent = display
                            tool_result = dd.get("context") or tool_result
                    except (json.JSONDecodeError, TypeError):
                        pass

                if self.verbose:
                    print(f"{C.DIM}    Result ({t_tool_done:.2f}s): {_trunc(tool_result or '(empty)', 300)}{C.RESET}")
                else:
                    print(f"{C.DIM}    Result ({t_tool_done:.2f}s): {_trunc(tool_result or '(empty)', 120)}{C.RESET}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result or "(no output)",
                })

                if tool_name == "request_tools":
                    category = tool_args.get("category", "").lower().strip()
                    if category:
                        extra_categories.add(category)
                        tools = _build_tools()

            if direct_display_sent:
                messages.append({
                    "role": "system",
                    "content": (
                        "The tool output above was ALREADY displayed directly to the user in the chat. "
                        "Do NOT repeat, summarize, rephrase, or echo ANY of that content. "
                        "The user can already see it. If you have nothing new to add, "
                        "respond with an empty message. Only speak if the user asked a "
                        "question that needs answering beyond what was displayed."
                    ),
                })

            t_loop = time.monotonic()
            completion = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=tools,
            )
            t_loop_done = time.monotonic() - t_loop
            if completion.usage:
                total_prompt += completion.usage.prompt_tokens
                total_completion += completion.usage.completion_tokens

            if self.verbose:
                print(f"{C.DIM}  LLM loop {tool_loop}: {t_loop_done:.2f}s | {completion.usage.prompt_tokens:,} in / {completion.usage.completion_tokens:,} out{C.RESET}")

            assistant_message = completion.choices[0].message

        response_text = assistant_message.content or ""

        # Duplicate suppression
        if direct_display_sent and response_text:
            display_lines = {l.strip() for l in direct_display_sent.split("\n") if l.strip()}
            response_lines = [l for l in response_text.split("\n") if l.strip()]
            if display_lines and response_lines:
                overlap = sum(1 for l in response_lines if l.strip() in display_lines)
                if overlap > len(response_lines) * 0.5:
                    print(f"{C.YELLOW}  [Suppressed duplicate LLM response — {overlap}/{len(response_lines)} lines overlapped]{C.RESET}")
                    response_text = ""

        self.session.append({"role": "assistant", "content": response_text})

        print(f"\n{C.BOLD}{C.GREEN}SKIPPER:{C.RESET} {response_text or '(empty — direct display only)'}")
        print(f"{C.DIM}  [{total_prompt:,} in / {total_completion:,} out | {tool_loop} tool loops]{C.RESET}")

        return response_text


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="SkipperBot Chat Test Harness")
    parser.add_argument("--user", default="alice", help="User ID (default: alice)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed tool routing, results, and timing")
    parser.add_argument("--show-prompt", action="store_true", help="Print the full system prompt and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show tool routing only, don't call LLM")
    parser.add_argument("messages", nargs="*", help="Messages to send (interactive if none)")
    args = parser.parse_args()

    harness = ChatTestHarness(user_id=args.user, verbose=args.verbose, dry_run=args.dry_run)

    if args.show_prompt:
        harness.show_system_prompt()
        return

    # If messages provided as args, run them and exit
    if args.messages:
        for msg in args.messages:
            await harness.send(msg)
        return

    # If stdin is piped, read messages from it
    if not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line:
                await harness.send(line)
        return

    # Interactive mode
    print(f"\n{C.BOLD}SkipperBot Chat Test Harness{C.RESET}")
    print(f"User: {args.user} | Model: {OPENAI_MODEL} | Verbose: {args.verbose}")
    print(f"Type a message, or: /quit, /clear, /prompt, /verbose, /dry\n")

    while True:
        try:
            user_input = input(f"{C.BOLD}> {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            break
        if user_input.lower() == "/clear":
            harness.session.clear()
            print(f"{C.YELLOW}Session cleared.{C.RESET}")
            continue
        if user_input.lower() == "/prompt":
            harness.show_system_prompt()
            continue
        if user_input.lower() == "/verbose":
            harness.verbose = not harness.verbose
            print(f"{C.YELLOW}Verbose: {harness.verbose}{C.RESET}")
            continue
        if user_input.lower() == "/dry":
            harness.dry_run = not harness.dry_run
            print(f"{C.YELLOW}Dry-run: {harness.dry_run}{C.RESET}")
            continue

        await harness.send(user_input)


if __name__ == "__main__":
    asyncio.run(main())
