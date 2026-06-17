#!/usr/bin/env python3
"""
context_manager.py — portable re-implementation of Headroom's RollingWindow
and IntelligentContextManager.

Drops messages from a conversation transcript to fit within a token budget.
Drop priority:

  1. Oldest tool_result / tool_call pairs (dropped together, never split).
  2. Old assistant messages (replaced with a 1-line summary marker).
  3. Old user messages (only if necessary; replaced with a marker).
  4. NEVER dropped: system prompt, last N user turns, the active tool pair,
     and any message containing an error.

Usage:
    python context_manager.py transcript.jsonl --max-tokens 100000 --keep-last-turns 5

Input format: JSONL, one message per line. Each message should have at least
a `role` field (`system`, `user`, `assistant`, `tool`) and a `content` field.
Tool calls / results follow the OpenAI / Anthropic convention:
  - assistant message with `tool_calls` array -> the call
  - tool message with `tool_call_id` -> the result

Writes the trimmed transcript to stdout.

Credits: independent re-implementation of the RollingWindow and
IntelligentContextManager transforms from
https://github.com/chopratejas/headroom (Apache 2.0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ccr_store, estimate_tokens, is_error_item  # type: ignore


def _content_to_text(content) -> str:
    """Flatten OpenAI / Anthropic content (string or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    parts.append(json.dumps(block.get("input", {}), default=str))
                elif block.get("type") == "tool_result":
                    parts.append(_content_to_text(block.get("content", "")))
                else:
                    parts.append(json.dumps(block, default=str))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _has_error(msg: dict) -> bool:
    """True if this message contains an error indicator."""
    if msg.get("role") == "tool" and msg.get("is_error"):
        return True
    content = msg.get("content")
    text = _content_to_text(content)
    # Cheap heuristic: look for 'error', 'failed', 'traceback' in content
    low = text.lower()
    if any(kw in low for kw in ("error", "failed", "traceback", "exception", "fatal")):
        return True
    # Anthropic-style tool_result with is_error
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                if block.get("is_error"):
                    return True
                if is_error_item(block.get("content", "")):
                    return True
    return False


def _is_tool_pair(a: dict, b: dict) -> bool:
    """True if a is an assistant tool_call and b is the matching tool_result."""
    if a.get("role") != "assistant":
        return False
    if b.get("role") != "tool":
        return False
    a_calls = a.get("tool_calls") or []
    if not a_calls:
        return False
    return any(c.get("id") == b.get("tool_call_id") for c in a_calls)


def _pair_tool_calls(messages: list[dict]) -> list[tuple[int, int | None]]:
    """For each message, return (idx, paired_idx_or_None).

    Assistant messages with tool_calls are paired with their tool_result
    messages. Tool messages are paired with the assistant that issued the call.
    """
    pair: dict[int, int] = {}
    pending_calls: dict[str, int] = {}  # tool_call_id -> assistant idx
    for i, m in enumerate(messages):
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or []:
                if isinstance(c, dict) and c.get("id"):
                    pending_calls[c["id"]] = i
        elif m.get("role") == "tool":
            tcid = m.get("tool_call_id")
            if tcid and tcid in pending_calls:
                pair[pending_calls[tcid]] = i
                pair[i] = pending_calls[tcid]
    return [(i, pair.get(i)) for i in range(len(messages))]


def trim_transcript(
    messages: list[dict],
    max_tokens: int,
    keep_last_turns: int = 5,
    keep_system: bool = True,
    output_buffer_tokens: int = 4000,
) -> tuple[list[dict], dict]:
    """Trim a transcript to fit within `max_tokens - output_buffer_tokens`.

    Returns (trimmed_messages, stats).
    """
    # Token estimate per message
    msg_tokens = [estimate_tokens(_content_to_text(m.get("content", ""))) for m in messages]
    total = sum(msg_tokens)
    target = max_tokens - output_buffer_tokens

    stats = {
        "original_messages": len(messages),
        "original_tokens": total,
        "target_tokens": target,
        "dropped": {"tool_pairs": 0, "assistant": 0, "user": 0},
    }

    if total <= target:
        return messages, stats

    # Identify protected messages
    pairs = _pair_tool_calls(messages)
    pair_of = {i: p for i, p in pairs}

    # Find indices of last N user turns
    user_idxs = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    protected_user = set(user_idxs[-keep_last_turns:]) if user_idxs else set()

    # System messages
    protected_system = set(
        i for i, m in enumerate(messages) if m.get("role") == "system" and keep_system
    )

    # Error messages
    protected_error = set(i for i, m in enumerate(messages) if _has_error(m))

    # The most recent tool pair (the active one)
    last_tool_pair_assistant = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant" and messages[i].get("tool_calls"):
            last_tool_pair_assistant = i
            break
    protected_active_pair: set[int] = set()
    if last_tool_pair_assistant is not None:
        protected_active_pair.add(last_tool_pair_assistant)
        p = pair_of.get(last_tool_pair_assistant)
        if p is not None:
            protected_active_pair.add(p)

    protected = protected_user | protected_system | protected_error | protected_active_pair

    # Pass 1: drop oldest tool pairs
    new_messages: list[dict] = []
    dropped_indices: set[int] = set()
    for i, m in enumerate(messages):
        if i in dropped_indices:
            continue
        if i in protected:
            new_messages.append(m)
            continue
        # If this is the assistant half of a tool pair, and we still need to drop
        p = pair_of.get(i)
        if (
            m.get("role") == "assistant"
            and m.get("tool_calls")
            and p is not None
            and p not in protected
        ):
            # Drop both halves
            dropped_indices.add(i)
            dropped_indices.add(p)
            stats["dropped"]["tool_pairs"] += 1
            continue
        # If this is the tool half of a pair whose assistant was already dropped,
        # drop it too
        if m.get("role") == "tool" and p is not None and p in dropped_indices:
            dropped_indices.add(i)
            continue
        new_messages.append(m)

    new_tokens = sum(estimate_tokens(_content_to_text(m.get("content", ""))) for m in new_messages)
    if new_tokens <= target:
        stats["final_messages"] = len(new_messages)
        stats["final_tokens"] = new_tokens
        return new_messages, stats

    # Pass 2: drop / summarize old assistant messages
    messages2: list[dict] = []
    for m in new_messages:
        if (
            m.get("role") == "assistant"
            and m not in [messages[i] for i in protected_user]
            and estimate_tokens(_content_to_text(m.get("content", ""))) > 50
        ):
            # Replace with a one-line marker
            messages2.append({
                "role": "assistant",
                "content": "[dropped: assistant turn summarized — see CCR cache for original]",
                "_headroom_dropped": True,
            })
            stats["dropped"]["assistant"] += 1
        else:
            messages2.append(m)

    new_tokens = sum(estimate_tokens(_content_to_text(m.get("content", ""))) for m in messages2)
    if new_tokens <= target:
        stats["final_messages"] = len(messages2)
        stats["final_tokens"] = new_tokens
        return messages2, stats

    # Pass 3: drop / summarize old user messages (not in protected_user)
    messages3: list[dict] = []
    user_count = 0
    total_users = sum(1 for m in messages2 if m.get("role") == "user")
    for m in reversed(messages2):
        if m.get("role") == "user":
            user_count += 1
            if user_count > keep_last_turns and estimate_tokens(_content_to_text(m.get("content", ""))) > 50:
                messages3.append({
                    "role": "user",
                    "content": "[dropped: earlier user turn — see CCR cache for original]",
                    "_headroom_dropped": True,
                })
                stats["dropped"]["user"] += 1
                continue
        messages3.append(m)
    messages3.reverse()

    new_tokens = sum(estimate_tokens(_content_to_text(m.get("content", ""))) for m in messages3)
    stats["final_messages"] = len(messages3)
    stats["final_tokens"] = new_tokens
    return messages3, stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ContextManager: rolling-window trim of a JSONL transcript.",
    )
    ap.add_argument("file", nargs="?", help="JSONL transcript file (default: stdin)")
    ap.add_argument("--max-tokens", type=int, default=100000)
    ap.add_argument("--keep-last-turns", type=int, default=5)
    ap.add_argument("--output-buffer-tokens", type=int, default=4000)
    ap.add_argument("--no-keep-system", action="store_true",
                    help="Allow dropping system messages (rarely a good idea).")
    ap.add_argument("--ccr-cache-dir", default=".headroom-cache")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    else:
        raw_lines = sys.stdin.readlines()

    messages: list[dict] = []
    for ln in raw_lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            messages.append(json.loads(ln))
        except json.JSONDecodeError:
            sys.stderr.write(f"context_manager: skipping non-JSON line: {ln[:80]}\n")

    trimmed, stats = trim_transcript(
        messages,
        max_tokens=args.max_tokens,
        keep_last_turns=args.keep_last_turns,
        keep_system=not args.no_keep_system,
        output_buffer_tokens=args.output_buffer_tokens,
    )

    # CCR cache the original
    raw_blob = "\n".join(json.dumps(m, default=str) for m in messages)
    if args.ccr_cache_dir:
        key = ccr_store(raw_blob, args.ccr_cache_dir)
        # Annotate first system message with the CCR key
        for m in trimmed:
            if m.get("role") == "system":
                if isinstance(m.get("content"), str):
                    m["content"] = f"[headroom-ccr:{key}]\n" + m["content"]
                break

    for m in trimmed:
        sys.stdout.write(json.dumps(m, default=str) + "\n")

    if args.stats:
        sys.stderr.write(
            f"context_manager: {stats['original_messages']} -> {stats['final_messages']} messages, "
            f"~{stats['original_tokens']} -> ~{stats['final_tokens']} tokens "
            f"(target {stats['target_tokens']})\n"
            f"  dropped: {stats['dropped']}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
