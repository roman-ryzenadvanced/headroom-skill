# Techniques — deep dive

This document explains each compression transform in detail, with worked
examples. It's the reference for agents that want to apply the heuristics
by hand (without calling the helper scripts).

Each transform follows the same meta-pattern:

1. **Detect** the content type.
2. **Extract** the structure (keys, signatures, anchors).
3. **Select** the most informative items / lines / nodes.
4. **Reassemble** a shorter representation that preserves the structure.
5. **Cache** the original (CCR) for retrieval.

The selection heuristics are the same across transforms, in priority order:

1. Errors
2. First N
3. Last N
4. Anomalies
5. Relevant (by BM25 to the user's question)
6. Change points
7. Sample of the remainder

---

## 1. SmartCrusher — JSON arrays

**When**: the content is a JSON array of dicts (tool results, API responses,
search hits, telemetry events).

**Why**: a 1000-row JSON array often has 5 rows that matter and 995 that
don't. SmartCrusher picks the 5.

### Selection algorithm

Given an array `items` and a `query` (the user's current question):

1. **Errors**. For each item, check if it `is_error_item` — has
   `is_error: true`, `level: error`, `status >= 400`, `success: false`,
   `ok: false`, an `error` field, or any string value containing an error
   keyword (`error`, `failed`, `exception`, `traceback`, …). Keep all
   error items.
2. **First 3**. Keep the first 3 items in the array. They give pagination
   context and setup state.
3. **Last 2**. Keep the last 2 items. They give recency and terminal state.
4. **Anomalies**. Compute the mean and standard deviation of all numeric
   values across all items. Keep items with any numeric value >2σ from the
   mean. (Skip if the array has no numeric values.)
5. **Relevant**. Tokenize the query and each item (item is serialized to
   JSON for tokenization). Compute BM25 scores. Keep the top-K items
   (default 5) with score > 0.
6. **Change points**. For items that are dicts, watch a small set of
   likely-state keys: `status`, `level`, `state`, `phase`, `stage`,
   `event`. Keep items where any of these keys transitions from its
   previous value.
7. **Sample**. If the total selected so far is under the cap (default 50),
   fill the remainder with an evenly-spaced sample of unselected items.

After selection, deduplicate by content hash (identical items appear
often — the same file read twice, the same error repeated).

### Example

Input (1,000-item API response, abbreviated):

```json
{
  "results": [
    {"id": 1, "status": "ok", "msg": "user 1 signed up"},
    {"id": 2, "status": "ok", "msg": "user 2 signed up"},
    …
    {"id": 500, "status": "error", "msg": "FATAL: db connection refused"},
    {"id": 501, "status": "ok", "msg": "user 501 signed up"},
    …
    {"id": 999, "status": "ok", "msg": "user 999 signed up"},
    {"id": 1000, "status": "ok", "msg": "user 1000 signed up"}
  ],
  "total": 1000
}
```

Query: `"signup error in production"`

Selected (5 items, ~95% reduction):

```json
{
  "results": [
    {"id": 1, "status": "ok", "msg": "user 1 signed up"},        // first
    {"id": 2, "status": "ok", "msg": "user 2 signed up"},        // first
    {"id": 3, "status": "ok", "msg": "user 3 signed up"},        // first
    {"id": 500, "status": "error", "msg": "FATAL: db connection refused"},  // error + relevant
    {"id": 1000, "status": "ok", "msg": "user 1000 signed up"}   // last
  ],
  "total": 1000,
  "_headroom": {
    "compressed": true,
    "original_count": 1000,
    "selected_count": 5,
    "ccr_key": "a3f9c1b2d4e6"
  }
}
```

### What the agent narrates

> Compressed 1,000 → 5 items with SmartCrusher (kept first 3, last 1, all
> errors [1], top 0 by BM25 to "signup error in production"). CCR key:
> `a3f9c1b2d4e6`.

### Helper script

```bash
python scripts/smart_crusher.py results.json \
    --query "signup error in production" \
    --keep-first 3 --keep-last 2 --max-items 50 --stats
```

---

## 2. LogCompressor — build/test logs

**When**: the content is a build or test log (pytest, npm, cargo, make,
mvn, gradle, go test).

**Why**: a 5,000-line pytest log typically has 1 FAILED line, 1 stack
trace, and 4,997 PASSED lines. The 4,997 PASSED lines are useless.

### Selection algorithm

1. **Error lines**. Keep every line that matches `\b(error|failed|failure|
   exception|traceback|fatal|panic|segfault|abort|crash|denied|refused|
   timeout|undefined|nullreference|outofrange|overflow|deadlock)\b` or
   contains a 4xx/5xx status code or `[ERR`.
2. **Stack trace continuation**. After an error line, keep up to 15
   following lines that look like traceback continuation (indented, `File
   "…", line N, in <func>`, `^~~`, `|…|`).
3. **Section headers**. Keep lines like `===== test session starts =====`,
   `----- summary -----`, `***** ERROR *****`.
4. **Summary lines**. Keep lines matching `N passed`, `N failed`, `N
   skipped`, `N errors`, `Ran N tests`, `Result:`, `Tests: N`.
5. **First 3 lines and last 5 lines**. Setup context and terminal state.
6. **Warnings** (optional, off by default). Keep `WARN` and
   `DeprecationWarning` lines if `--keep-warnings` is set.

Other lines are dropped. Between kept sections, insert `... [elided N
lines] ...` markers so the LLM knows there was content there.

### Example

Input (408-line pytest log):

```
===== test session starts =====
collected 500 items
tests/test_a.py::test_1 PASSED
tests/test_a.py::test_2 PASSED
... 400 more PASSED lines ...
tests/test_d.py::test_99 FAILED
AssertionError: expected 5, got 3
Traceback (most recent call last):
  File "tests/test_d.py", line 99, in test_99
    assert calc() == 5
  File "src/calc.py", line 12, in calc
    return a + b
tests/test_e.py::test_100 PASSED
===== 1 failed, 499 passed in 5.3s =====
```

Output (11 lines, ~95% reduction):

```
[headroom-log ccr:bb5b11469a04]
===== test session starts =====
collected 500 items
tests/test_a.py::test_1 PASSED
... [elided 5 lines] ...
tests/test_d.py::test_99 FAILED
... [elided 1 lines] ...
Traceback (most recent call last):
  File "tests/test_d.py", line 99, in test_99
    assert calc() == 5
  File "src/calc.py", line 12, in calc
    return a + b
tests/test_e.py::test_100 PASSED
===== 1 failed, 499 passed in 5.3s =====
```

### Helper script

```bash
python scripts/log_compressor.py pytest.log --keep-warnings --stats
```

---

## 3. SearchCompressor — grep/ripgrep output

**When**: the content is search output in `file:line:content` format
(grep, ripgrep, ag, ack).

**Why**: a grep for `foo` in a large codebase can return 1,000 matches.
The 3 that match the user's actual question are buried in noise.

### Selection algorithm

1. **Error matches**. Keep every match whose content contains an error
   keyword.
2. **First 3 matches**.
3. **Last 2 matches**.
4. **Top-K by BM25**. Tokenize the query and each match's content.
   Compute BM25 scores. Keep the top 10 (default) with score > 0.
5. **Per-file diversity**. For each unique file path, keep up to 3 matches
   (default), highest-scored first. This ensures one heavily-matched file
   doesn't crowd out matches from other files.
6. **Cap at 50** (default). If still over, sample.

### Example

Input (201 matches):

```
src/module_0.py:1:def func_0(): pass
src/module_1.py:2:def func_1(): pass
...
src/module_199.py:200:def func_199(): pass
src/auth.py:42:    raise AuthenticationError('token expired')
```

Query: `"auth token expired"`

Output (20 matches, ~90% reduction):

```
[headroom-search ccr:d4e6a3f9c1b2 query='auth token expired']
src/module_0.py:1:def func_0(): pass
src/module_1.py:2:def func_1(): pass
src/module_2.py:3:def func_2(): pass
... [elided 39 matches] ...
src/auth.py:42:    raise AuthenticationError('token expired')
... [elided 156 matches] ...
src/module_199.py:200:def func_199(): pass
```

### Helper script

```bash
rg "auth" src/ | python scripts/search_compressor.py --query "auth token expired" --max-items 20
```

---

## 4. CodeCompressor — source code

**When**: the content is a source file the agent needs to read but not
modify (for understanding, not editing).

**Why**: when you're trying to understand a 1000-line module, you usually
need the imports, the class/function signatures, the type annotations,
and the error handlers. You don't need the implementations of every
helper function.

### Selection algorithm

This is the one transform where the portable version is weaker than
upstream Headroom. Headroom uses tree-sitter for accurate AST parsing;
the portable version uses regex heuristics.

For each line, decide:

- **Always keep**: imports (`import`, `from X import`, `using`, `use`,
  `include`, `#include`, `require`, `extern crate`), package/module
  declarations, decorators (`@…`), class/struct/interface/enum/trait
  declarations, function signatures, type annotations, return statements,
  try/except/catch/finally/raise/throw, if/elif/else/for/while/switch/
  case/match, closing braces.
- **Keep first N lines of each function body** (default 3): the first few
  lines after a signature often contain the key setup logic.
- **Keep the first line of each docstring** (configurable: full / first
  line / remove).
- **Compress the rest**: replace with `# ... (N lines compressed) ...`.

### Example

Input (Python, 27 lines):

```python
import os
import sys
from typing import List

def process_items(items: List[str]) -> List[str]:
    """Process a list of items.
    
    This is a long docstring that goes on for multiple lines.
    It explains the algorithm in detail.
    """
    results = []
    for item in items:
        if not item:
            continue
        processed = item.strip().lower()
        results.append(processed)
    return results
```

Output (~50% reduction):

```python
import os
import sys
from typing import List

def process_items(items: List[str]) -> List[str]:
    """Process a list of items. ..."""
    results = []
    for item in items:
    # ... (5 lines compressed) ...
    return results
```

### Helper script

```bash
python scripts/code_compressor.py module.py --language python --max-body-lines 3 --docstring-mode first_line
```

---

## 5. RollingWindow / IntelligentContext — conversation history

**When**: the conversation transcript exceeds the token budget.

**Why**: agentic loops accumulate tool results. A 30-turn debugging
session can easily hit 200k tokens. Naive truncation breaks tool_call /
tool_result pairs and drops the wrong messages.

### Drop priority

1. **Oldest tool outputs first**. The least likely to be referenced
   again. Always drop the complete `tool_call` + `tool_result` pair
   together — never split them.
2. **Old assistant messages**. If the assistant explained something three
   turns ago and hasn't been referenced since, replace it with a one-line
   marker: `[dropped: explained how the auth middleware works]`.
3. **Old user messages**. Only if necessary. Replace with a marker.
4. **Never dropped**: the system prompt, the last N user turns (default
   2), the active tool pair (the most recent tool_call + its result), and
   any message containing an error.

### IntelligentContext (score-based, optional)

Instead of dropping strictly by position, score each message by:

| Factor                | Weight | Description                              |
|-----------------------|-------:|------------------------------------------|
| Recency               | 20%    | Exponential decay from conversation end  |
| Semantic similarity   | 20%    | Embedding similarity to recent context   |
| Importance            | 25%    | Learned from retrieval patterns          |
| Error indicators      | 15%    | Messages with errors score higher        |
| Forward references    | 15%    | Messages referenced by later messages    |
| Token density         | 5%     | Unique tokens / total tokens             |

Drop the lowest-scored messages first, subject to the same "never drop"
rules.

The portable `context_manager.py` uses position-based dropping (RollingWindow
behaviour). Score-based dropping requires embeddings and is left as a
future extension.

### Helper script

```bash
python scripts/context_manager.py transcript.jsonl --max-tokens 100000 --keep-last-turns 5
```

---

## 6. CacheAligner — prefix stabilization

**When**: building prompts to send to the LLM.

**Why**: providers cache request prefixes. Byte-identical prefixes hit
the cache; any change ahead of a `cache_control` breakpoint invalidates
everything after it.

### Rules

1. **Static content at the head**. System prompt, tool schemas, project
   conventions, long reference docs.
2. **Dynamic content at the tail**. Dates, session IDs, CWD, recent file
   lists, git state — all go after the last `cache_control` breakpoint.
3. **Byte-stable steering**. The verbosity steering text should be
   byte-identical across requests at the same level. Don't embed dynamic
   content in the steering block.

See `prompts/cache_alignment.md` for full detail.

---

## 7. Output Shaper — what the model writes back

**When**: generating the model's reply.

**Why**: output tokens cost 5× input on Opus-class models. A lot of
output is waste: preambles, re-printed code, deep thinking on routine
turns.

### Two levers

1. **Verbosity steering** (L0–L4). Append a "be terse, don't restate
   context" instruction to the tail of the system prompt. Default L2.
   See `prompts/verbosity_steering.md`.
2. **Effort routing**. On mechanical continuations (the previous turn
   was a successful tool call, no new user ask), lower the model's
   thinking effort. See `prompts/effort_routing.md`.

### Measured impact

From upstream Headroom's benchmarks:

- L2 (default): no accuracy loss on GSM8K / TruthfulQA / SQuAD v2 / BFCL,
  ~28% output token reduction.
- L3: ~35% output token reduction, minor accuracy loss on reasoning-heavy
  tasks.
- L4: ~50% output token reduction, noticeable accuracy loss; use only
  when explicitly requested.

### Counterfactual measurement

We can't directly observe what the model *would have* written without
steering. Upstream Headroom reports an estimate with a confidence range,
or — if you opt into a 10% holdout — a measured number. The portable
skill doesn't measure; it just applies the steering.

---

## 8. CCR — reversible compression

Every transform above writes the original to a cache file before
compressing:

```
.headroom-cache/<sha256_first_12>.txt
```

The compressed output cites the SHA in a header:

```
[headroom-log ccr:bb5b11469a04]
... compressed content ...
```

If a later turn needs the original (the user asks "what was the full
log?"), retrieve it:

```bash
cat .headroom-cache/bb5b11469a04.txt
```

The cache is local, never sent to the LLM unless retrieved. Clean it up
periodically:

```bash
find .headroom-cache -mtime +7 -delete
```

For the on-disk format and retrieval convention, see
`docs/reversible-ccr.md`.

---

## Safety invariants (do not violate)

These mirror upstream Headroom's safety rules. Each prevents a concrete
failure mode.

1. **Never drop user or assistant text.** Tool results can be compressed;
   human-authored messages cannot.
2. **Never split a tool_call / tool_result pair.** Dropping one half
   orphans the other and the model will hallucinate a result.
3. **Parse failures are no-ops.** If the input doesn't parse as the
   expected type, pass it through unchanged.
4. **Always preserve recency.** The last N turns (default 2 user turns)
   are never dropped.
5. **Always preserve the system prompt.** Never.
6. **100% error preservation.** No exceptions.
7. **Idempotent.** Running the compressor on already-compressed output
   should be a no-op (or close to it).

---

## Credits

These techniques are portable re-implementations of transforms from
[chopratejas/headroom](https://github.com/chopratejas/headroom) by Tejas
Chopra and contributors (Apache 2.0). The upstream implementations are
in Rust + Python with ML backing (Kompress-v2-base); the portable
versions in this skill are pure Python stdlib and capture the same
selection heuristics but not the ML compression.
