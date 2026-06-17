# Cache alignment — prefix stabilization rules

LLM providers (Anthropic, OpenAI, Gemini) cache request prefixes —
typically the system prompt plus the first few turns. Cache hits cut
latency by ~80% and cost by ~90% on the cached portion. But cache hits
require byte-identical prefixes; a single character change ahead of a
`cache_control` breakpoint invalidates everything after it.

This file gives the rules for keeping prefixes stable.

## The rule, in one sentence

> Static content goes at the head. Dynamic content goes at the tail, after
> the last `cache_control` breakpoint.

## What counts as "dynamic"

Anything that changes between requests:

- **Timestamps** — "Today is 2026-06-18", "Current time: …"
- **Session IDs** — "Session: abc123"
- **Current working directory** — "CWD: /home/z/project/src"
- **Recent file lists** — "Recently edited: foo.py, bar.py"
- **Git state** — "On branch main, commit abc123"
- **Per-user preferences** — "User likes terse answers"
- **Random examples** — "Here's a random tip: …"
- **Conversation counters** — "Turn 5 of N"

If it would change between two consecutive requests, it's dynamic.

## What counts as "static"

Anything that stays the same across all requests in a session:

- The agent's identity ("You are a coding agent…")
- The agent's capabilities ("You can read files, run commands, …")
- The agent's style guidelines (the verbosity steering block, if level
  doesn't change)
- The list of available tools (their schemas, not their call counts)
- Project conventions ("This codebase uses 4-space indentation, …")
- Long reference documents loaded once at session start

## How to structure the system prompt

```
[STATIC PREFIX]                                          ← cacheable
You are a coding agent. …
Your tools are: …
Project conventions: …
[cache_control breakpoint]
---
[DYNAMIC CONTEXT]                                        ← re-processed
Today: 2026-06-18
CWD: /home/z/project
Session: abc123
Recent files: foo.py, bar.py
---
[STEERING]                                               ← re-processed
[Output style — L2]
… verbosity rules …
```

## Common mistakes

### 1. Date in the system prompt body

```text
# BAD — date busts the cache every day
You are a coding agent. Today is 2026-06-18. Your job is to …
```

```text
# GOOD — date moved to dynamic tail
You are a coding agent. Your job is to …
[cache_control]
---
Today: 2026-06-18
```

### 2. Session ID at the head

```text
# BAD — session ID changes every session
[Session: abc123] You are a coding agent. …
```

```text
# GOOD — session ID in dynamic tail
You are a coding agent. …
[cache_control]
---
Session: abc123
```

### 3. Recent file list at the head

```text
# BAD — file list changes constantly
You are a coding agent. Recent files: foo.py, bar.py, baz.py, …
```

```text
# GOOD — recent files in dynamic tail
You are a coding agent. …
[cache_control]
---
Recent files: foo.py, bar.py, baz.py
```

### 4. Verbosity steering at the head

```text
# BAD — steering text changes when level changes
[Output style — L2] You are a coding agent. …
```

```text
# GOOD — steering text in tail, after cache_control
You are a coding agent. …
[cache_control]
---
[Output style — L2]
… steering rules …
```

### 5. Whitespace normalization

Even a trailing space or different newline style busts the cache. If you
normalize whitespace, do it once at session start and keep the
normalization byte-stable thereafter.

## How much does this matter?

Cache hit improvement (from upstream Headroom benchmarks):

| Scenario                       | Before | After  |
|--------------------------------|--------|--------|
| Daily date in prompt           | 0%     | ~95%   |
| Dynamic user context           | ~10%   | ~80%   |
| Consistent prompts (already)   | ~90%   | ~95%   |

A 0% → 95% cache hit rate on a 100k-token system prompt is the difference
between $0.50 and $0.025 per request, and 2s vs 0.4s latency. It's the
single highest-leverage optimization in this whole skill.

## Agent-level rules

1. Build the system prompt once at session start. Don't rebuild it per
   request.
2. Identify dynamic fields at session start. Move them to the tail.
3. Place `cache_control` breakpoints strategically:
   - One at the end of the static system prompt (the long part).
   - Optionally one at the end of the static prefix of the conversation
     (e.g., after the first user turn if it's identical across
     sessions — rare).
4. Don't change verbosity level mid-session if you can avoid it. Each
   level change replaces the steering block, which is fine, but every
   change is a cache miss on the tail.
5. If you must include a counter or timestamp, include it once, in the
   dynamic tail.

## Provider-specific notes

### Anthropic
- `cache_control: {type: "ephemeral"}` on the last system block.
- Cache TTL is 5 minutes (default) or 1 hour (with the 1h beta header).
- Cache breakpoints max 4. Use them at: end of system prompt, end of
  long reference docs, end of long tool results you want cached.

### OpenAI
- Automatic caching on the first 1024+ tokens of the prompt. No
  `cache_control` markers needed.
- Cache TTL is 5-10 minutes of inactivity.
- Don't change the system prompt mid-session.

### Gemini
- Implicit prefix caching on the first 32k+ tokens.
- No explicit markers.
- TTL ~1 hour.

### Open-source / local
- Most local runtimes (vLLM, llama.cpp, Ollama) support prefix caching
  transparently. Same rule: keep the prefix byte-stable.
