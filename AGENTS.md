# AGENTS.md — Headroom token-reduction rules for any coding agent

> **Read this file at the start of every session.** It teaches you how to
> compress tool output, logs, search results, source code, and conversation
> history the same way the [Headroom](https://github.com/chopratejas/headroom)
> proxy does — but in-context, with no binary install.

## Why this exists

You (the agent) pay for every token you send to the LLM and every token you
write back. A typical agentic loop wastes 60–95% of its tokens on:

- 1000-row JSON tool results when only 5 rows matter
- 5000-line build logs when only the `FAILED` line matters
- 200-result grep output when only 3 matches are relevant
- Full source files when only the function signatures matter
- Preambles like "Great, let me help you with that" before every reply
- Re-printing code that's already on the user's screen

This file tells you how to avoid each of those wastes, with concrete
heuristics and helper scripts.

---

## Rule 1 — Compress before paste

**Before** pasting any tool result over ~200 tokens into your next message,
compress it with the matching transform. The threshold matters: below ~200
tokens, the compression overhead (and the tokens you spend narrating it) costs
more than it saves.

How to compress:

1. Identify the content type (see the table below).
2. If a helper script exists, run it. The scripts live in `scripts/` next to
   this file.
3. If no script exists, apply the heuristic by hand (the heuristics are below).
4. **Always** narrate what you did, in one short line:
   `Compressed 1,432 → 187 tokens with SmartCrusher (kept first 3, last 2, all errors, top 5 by BM25 to "user signup error").`
5. **Always** write the original to `.headroom-cache/<sha256>.txt` before
   compressing, so you or a later turn can retrieve it. Cite the SHA in your
   narration: `CCR key: a3f9c1…`.

Content-type routing:

| Content                                              | Transform           | Script                              |
|------------------------------------------------------|---------------------|-------------------------------------|
| JSON array (tool results, API responses, search hits) | SmartCrusher        | `scripts/smart_crusher.py`          |
| Build / test logs (pytest, npm, cargo, make, mvn)    | LogCompressor       | `scripts/log_compressor.py`         |
| grep / ripgrep / ag output (`file:line:content`)     | SearchCompressor    | `scripts/search_compressor.py`      |
| Source code (Python, JS, TS, Go, Rust, Java, C/C++)  | CodeCompressor      | `scripts/code_compressor.py`        |
| Conversation transcript over the token budget        | RollingWindow       | `scripts/context_manager.py`        |
| Plain prose (docs, READMEs)                          | (no transform; read selectively) | —                         |

---

## Rule 2 — Never drop errors

Errors, stack traces, `is_error: true` tool results, `FAILED` lines, `ERROR`
log lines, and Python `Traceback (most recent call last):` blocks are
**sacred**. Preserve them 100%, no matter how aggressively you compress the
surrounding content. The single most common compression failure mode is
dropping the one line that explains the bug.

This applies to every transform. SmartCrusher keeps every error item even if
it's an outlier in the wrong direction. LogCompressor keeps every `ERROR`,
`FAILED`, `Exception`, and the full traceback that follows it. SearchCompressor
keeps every match containing an error keyword.

---

## Rule 3 — Keep first N and last N

For any ordered collection (JSON array, log lines, search results):

- **First 3** items — give pagination context ("here's what page 1 looks
  like") and setup state ("the test run started like this").
- **Last 2** items — give recency ("the most recent error") and terminal state
  ("the final summary line").

These are always kept, even if their BM25 score is zero and they aren't
anomalies. Without them, the LLM loses its sense of where in the sequence it
is.

---

## Rule 4 — Stabilise the prefix (CacheAligner)

LLM providers (Anthropic, OpenAI, Gemini) cache request prefixes — typically
the system prompt plus the first few turns. Any byte change ahead of a
`cache_control` breakpoint invalidates everything after it. That means a
single date in your system prompt can bust the cache on every request.

When you build prompts:

1. Keep the **system prompt** byte-identical across requests. No timestamps,
   no "Today is…", no per-request session IDs at the head.
2. Keep the **first user turn** byte-identical when possible.
3. Move **dynamic content** (date, session ID, current working directory,
   recent file list) to the **tail** of the system prompt, after the last
   `cache_control` breakpoint.
4. If you must include a date, include it once, at the tail.

Example:

```text
# BAD — date in the middle busts the cache
You are a coding agent. Today is 2026-06-18. The user is in /home/z/project.
Your job is to ...

# GOOD — static prefix, dynamic tail
You are a coding agent. Your job is to ... (long static text) ...
[cache_control]
---
[Dynamic context]
Today: 2026-06-18
CWD: /home/z/project
```

---

## Rule 5 — Drop oldest tool outputs first (RollingWindow)

When the conversation exceeds the token budget, drop complete
`tool_call` + `tool_result` pairs from the oldest end. Drop priority:

1. **Oldest tool outputs** — first to go. They're the least likely to be
   referenced again.
2. **Old assistant messages** — second. If the assistant explained something
   three turns ago and hasn't been referenced since, it's probably safe to
   drop. Keep a one-line summary in its place: `[dropped: explained how the
   auth middleware works]`.
3. **Old user messages** — only if necessary. Replace with a summary marker.
4. **Never dropped**: the system prompt, the last 2 user turns, the active
   tool pair (the most recent tool_call + its result), and any message
   containing an error.

**Never split a tool_call from its tool_result.** If you drop one, drop both.
An orphaned tool_call makes the model hallucinate a result; an orphaned
tool_result confuses it about what produced the data.

The `scripts/context_manager.py` helper applies these rules automatically over
a JSONL transcript.

---

## Rule 6 — Shape your own output (Output Shaper)

The default output verbosity is **L2**. The five levels, cumulative:

| Level | What to do                                                                 |
|------:|-----------------------------------------------------------------------------|
| L0    | Off. Write naturally.                                                       |
| L1    | Skip preambles ("Great, let me…") and postambles ("Let me know if…").     |
| L2    | L1 + don't restate code/output already on screen. Reference by `path:line`. |
| L3    | L2 + conclusions only. Skip reasoning unless the user asks for it.         |
| L4    | Fragments. Minimum tokens. No full sentences unless safety requires.       |

**Why L2 is the default.** It's the level at which we've measured no
accuracy loss on standard benchmarks (GSM8K, TruthfulQA, SQuAD v2, BFCL) while
still saving ~28% of output tokens. Levels 3 and 4 trade accuracy for tokens
and should only be used when the user asks for brevity or when the turn is
purely mechanical.

The "effort routing" companion: classify the current turn before generating.

| Last user message contains…                             | Classification           | Verbosity | Effort  |
|---------------------------------------------------------|--------------------------|-----------|---------|
| A new question or instruction (text, image, document)   | `NEW_USER_ASK`           | L2        | full    |
| Only `tool_result`, all `is_error: false`               | `MECHANICAL_CONTINUATION`| L3        | low     |
| Any `tool_result` with `is_error: true`                 | `ERROR_CONTINUATION`     | L2        | full    |
| Anything else                                           | `UNKNOWN`                | L2        | full    |

On `MECHANICAL_CONTINUATION`, you're just resuming after a tool ran. The user
doesn't need you to re-reason about the whole problem. Reply at L3, skip the
reasoning, and move on.

See `prompts/verbosity_steering.md` and `prompts/effort_routing.md` for the
exact system-prompt fragments to embed.

---

## Rule 7 — Be reversible (CCR)

Every compression is potentially lossy. The mitigation: **always** write the
original to a cache file before compressing, and cite the cache key.

Convention:

```bash
# Before compressing a tool result:
sha=$(printf '%s' "$original" | sha256sum | cut -c1-12)
mkdir -p .headroom-cache
printf '%s' "$original" > ".headroom-cache/${sha}.txt"
# Then compress, and include in your narration:
# "Compressed with SmartCrusher. CCR key: ${sha}."
```

If a later turn needs the original (the user asks "what was the full error
log?" or you find you need more context), retrieve it:

```bash
cat ".headroom-cache/${sha}.txt"
```

The cache is local, never sent to the LLM unless retrieved. Clean it up
periodically: `find .headroom-cache -mtime +7 -delete`.

---

## The selection heuristics, in detail

When you're applying a transform by hand (no script), the selection order is:

1. **Errors** — always keep. Match on `is_error`, `ERROR`, `FAILED`,
   `Exception`, `Traceback`, status codes `>= 400`, exit codes `!= 0`.
2. **First 3 items** — always keep.
3. **Last 2 items** — always keep.
4. **Anomalies** — for numeric fields, keep items whose value is >2 standard
   deviations from the mean. For string fields, keep items whose value
   differs from the field's modal value.
5. **Relevant** — top-K (default 5) items by BM25 similarity to the user's
   current question. If you can't compute BM25, fall back to "items that
   contain any token from the user's question".
6. **Change points** — items where a field value transitions (status flips
   from `running` to `done`, counter resets, type changes).
7. **Sample** — of the remaining items, keep a random sample large enough
   that the LLM has a sense of the distribution (default: 10% of the
   remainder, capped at 20 items).

After selection, **deduplicate** by content hash — duplicate tool results are
common (the same file read twice, the same search run twice) and waste tokens.

The total cap is typically 50 items. If selection produces more, sample down.

---

## When NOT to compress

- **Small content** (< 200 tokens). The overhead isn't worth it.
- **User-authored text.** Never compress user messages or assistant messages.
  Only tool results and other machine-generated content.
- **Single-item JSON.** SmartCrusher is for arrays. A single dict passes
  through.
- **Content the user explicitly asked for in full.** If the user says "show me
  the entire log", show them the entire log.
- **Content you'll need verbatim.** If the next step is to diff against this
  output, don't compress — you'll lose the diff baseline.

---

## Worked example

User asks: "Why is user signup failing in production?"

Before compression, you ran a search and got 1000 grep hits, then ran a tool
that returned a 5000-line JSON log. Naive paste: ~30k tokens. With this skill:

1. **SearchCompressor** on the grep output:
   `python scripts/search_compressor.py grep.out --query "user signup failing"`
   → 1000 hits → 12 most relevant (~600 tokens). CCR key written.
2. **SmartCrusher** on the JSON log, with `--query "user signup"`:
   `python scripts/smart_crusher.py log.json --query "user signup" --keep-first 3 --keep-last 2`
   → 5000 lines → ~40 items, all errors kept (~2k tokens). CCR key written.
3. **Verbosity L2** on your reply: skip the "Let me analyse this…" preamble,
   state the root cause, cite `path:line`, suggest the fix in 3 lines.

Total: ~3k tokens instead of ~30k. ~90% savings. The user gets the same
answer.

---

## File map

- `scripts/smart_crusher.py` — JSON array compressor
- `scripts/log_compressor.py` — build / test log compressor
- `scripts/search_compressor.py` — grep / ripgrep result compressor
- `scripts/code_compressor.py` — source code compressor
- `scripts/context_manager.py` — conversation rolling window
- `scripts/_common.py` — shared helpers (token estimate, BM25, entropy)
- `prompts/verbosity_steering.md` — L0–L4 system-prompt fragments
- `prompts/effort_routing.md` — turn classification rules
- `prompts/cache_alignment.md` — prefix stability rules
- `docs/techniques.md` — deep dive per transform
- `docs/integrations.md` — per-agent setup
- `docs/reversible-ccr.md` — CCR cache convention
- `examples/` — before/after for each transform

---

## Credits

This file is a portable re-implementation of the rules in
[chopratejas/headroom](https://github.com/chopratejas/headroom) by Tejas Chopra
and contributors (Apache 2.0). The original project is faster, more accurate,
and ML-backed; install it if you can.
