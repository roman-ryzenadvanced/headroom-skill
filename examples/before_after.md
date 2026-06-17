# Before / after — worked examples

This file shows the headroom-skill transforms in action, with realistic
inputs and the compressed outputs each script produces.

## Table of contents

- [SmartCrusher — JSON array](#smartcrusher--json-array)
- [LogCompressor — pytest log](#logcompressor--pytest-log)
- [SearchCompressor — grep output](#searchcompressor--grep-output)
- [CodeCompressor — Python source](#codecompressor--python-source)
- [ContextManager — long conversation](#contextmanager--long-conversation)

---

## SmartCrusher — JSON array

### Input (1,000-item API response, abbreviated here)

```json
{
  "results": [
    {"id": 1, "status": "ok", "msg": "user 1 signed up", "latency_ms": 42},
    {"id": 2, "status": "ok", "msg": "user 2 signed up", "latency_ms": 38},
    {"id": 3, "status": "ok", "msg": "user 3 signed up", "latency_ms": 45},
    {"id": 4, "status": "ok", "msg": "user 4 signed up", "latency_ms": 41},
    {"id": 5, "status": "ok", "msg": "user 5 signed up", "latency_ms": 39},
    ... 990 more items, all status=ok, latency 38-50ms ...
    {"id": 500, "status": "error", "msg": "FATAL: db connection refused", "latency_ms": 5000},
    ... 499 more items ...
    {"id": 1000, "status": "ok", "msg": "user 1000 signed up", "latency_ms": 43}
  ],
  "total": 1000
}
```

Tokens before: ~25,000

### Command

```bash
python scripts/smart_crusher.py results.json \
    --query "signup error in production" \
    --keep-first 3 --keep-last 2 --max-items 50 --stats
```

### Output

```json
{
  "results": [
    {"id": 1, "status": "ok", "msg": "user 1 signed up", "latency_ms": 42},
    {"id": 2, "status": "ok", "msg": "user 2 signed up", "latency_ms": 38},
    {"id": 3, "status": "ok", "msg": "user 3 signed up", "latency_ms": 45},
    {"id": 500, "status": "error", "msg": "FATAL: db connection refused", "latency_ms": 5000},
    {"id": 1000, "status": "ok", "msg": "user 1000 signed up", "latency_ms": 43}
  ],
  "total": 1000,
  "_headroom": {
    "compressed": true,
    "original_count": 1000,
    "selected_count": 5,
    "kept": {
      "errors": 1,
      "first": 3,
      "last": 2,
      "anomalies": 1,
      "relevant": 1,
      "change_points": 0
    },
    "ccr_key": "a3f9c1b2d4e6",
    "query": "signup error in production"
  }
}
```

Tokens after: ~250

**Savings: 99%**

The agent's narration would be:

> Compressed 1,000 → 5 items with SmartCrusher (kept first 3, last 1, all
> errors [1], top 1 by BM25 to "signup error in production", 1 anomaly
> with latency 5000ms vs mean ~42ms). CCR key: `a3f9c1b2d4e6`.

---

## LogCompressor — pytest log

### Input (408-line pytest log, abbreviated here)

```
===== test session starts =====
collected 500 items
tests/test_a.py::test_1 PASSED
tests/test_a.py::test_2 PASSED
tests/test_a.py::test_3 PASSED
tests/test_a.py::test_4 PASSED
tests/test_a.py::test_5 PASSED
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

Tokens before: ~3,500

### Command

```bash
python scripts/log_compressor.py pytest.log --keep-warnings --stats
```

### Output

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

Tokens after: ~250

**Savings: 93%**

Note that:
- The FAILED line and its full traceback are preserved.
- The summary line is preserved.
- The first and last PASSED lines are preserved for context.
- The 400+ intermediate PASSED lines are elided with a marker.

---

## SearchCompressor — grep output

### Input (201 matches)

```
src/module_0.py:1:def func_0(): pass
src/module_1.py:2:def func_1(): pass
src/module_2.py:3:def func_2(): pass
... 196 more matches, all "def func_N(): pass" ...
src/auth.py:42:    raise AuthenticationError('token expired')
src/module_198.py:199:def func_198(): pass
src/module_199.py:200:def func_199(): pass
```

Tokens before: ~5,000

### Command

```bash
rg "auth\|func" src/ | python scripts/search_compressor.py \
    --query "auth token expired" --max-items 20 --stats
```

### Output

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

Tokens after: ~300

**Savings: 94%**

The error match (`AuthenticationError`) is preserved 100%. The first 3
and last 2 matches are preserved for context. The 200 noise matches are
elided.

---

## CodeCompressor — Python source

### Input (27 lines)

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

Tokens before: ~150

### Command

```bash
python scripts/code_compressor.py module.py \
    --language python --max-body-lines 3 --docstring-mode first_line --stats
```

### Output

```python
# [headroom-code ccr:9f2a1c7e3b5d language=python]
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

Tokens after: ~75

**Savings: 50%**

What's preserved:
- All imports
- The function signature with type annotations
- The first line of the docstring
- The first 3 lines of the body (`results = []`, `for item in items:`,
  `if not item:`)
- The `return results` line
- The closing structure

What's compressed:
- The rest of the docstring (3 lines)
- The middle of the function body (5 lines: `continue`, `processed = …`,
  `results.append(…)`, blank line, etc.)

The signature and structure are enough for the LLM to understand what
the function does and how to call it. If it needs the implementation
detail, it retrieves the CCR original.

---

## ContextManager — long conversation

### Input (62-message transcript, abbreviated)

```jsonl
{"role": "system", "content": "You are a coding agent. Be terse."}
{"role": "user", "content": "Question 0 ... (1000 chars)"}
{"role": "assistant", "content": "Let me check that.", "tool_calls": [{"id": "call_0", "type": "function", "function": {"name": "read", "arguments": "{\"path\":\"file.py\"}"}}]}
{"role": "tool", "tool_call_id": "call_0", "content": "file content 0 ... (2000 chars)"}
{"role": "user", "content": "Question 1 ..."}
{"role": "assistant", "content": "Let me check that.", "tool_calls": [{"id": "call_1", ...}]}
{"role": "tool", "tool_call_id": "call_1", "content": "file content 1 ..."}
... 18 more user/assistant/tool cycles ...
{"role": "user", "content": "Final question ... (1000 chars)"}
```

Tokens before: ~50,000

### Command

```bash
python scripts/context_manager.py transcript.jsonl \
    --max-tokens 5000 --keep-last-turns 3 --stats
```

### Output (24 messages)

```jsonl
{"role": "system", "content": "[headroom-ccr:e7f3a9c1b2d4]\nYou are a coding agent. Be terse."}
{"role": "user", "content": "[dropped: earlier user turn — see CCR cache for original]"}
{"role": "assistant", "content": "[dropped: assistant turn summarized — see CCR cache for original]"}
... (oldest tool pairs dropped entirely) ...
{"role": "user", "content": "Question 17 ..."}
{"role": "assistant", "content": "Let me check that.", "tool_calls": [{"id": "call_17", ...}]}
{"role": "tool", "tool_call_id": "call_17", "content": "file content 17 ..."}
{"role": "user", "content": "Question 18 ..."}
{"role": "assistant", "content": "Let me check that.", "tool_calls": [{"id": "call_18", ...}]}
{"role": "tool", "tool_call_id": "call_18", "content": "file content 18 ..."}
{"role": "user", "content": "Question 19 ..."}
{"role": "assistant", "content": "Let me check that.", "tool_calls": [{"id": "call_19", ...}]}
{"role": "tool", "tool_call_id": "call_19", "content": "file content 19 ..."}
{"role": "user", "content": "Final question ..."}
```

Tokens after: ~4,800

**Savings: 90%**

What's preserved:
- The system prompt (with CCR key annotation)
- The last 3 user turns + their assistant/tool triples
- The final user turn

What's dropped:
- The oldest 17 tool_call/tool_result pairs (dropped as complete units,
  never split)
- The oldest 17 user messages (replaced with markers; originals in CCR
  cache)

If a later turn needs the dropped content (e.g., the user asks "what
did file 5 contain?"), the agent retrieves it:

```bash
cat .headroom-cache/e7f3a9c1b2d4.txt
# Parse the JSONL to find the tool result with tool_call_id="call_5"
```

---

## Summary

| Transform          | Typical input size | Typical output size | Typical savings |
|--------------------|-------------------:|--------------------:|----------------:|
| SmartCrusher       | 25,000 tokens      | 250 tokens          | 99%             |
| LogCompressor      | 3,500 tokens       | 250 tokens          | 93%             |
| SearchCompressor   | 5,000 tokens       | 300 tokens          | 94%             |
| CodeCompressor     | 150 tokens         | 75 tokens           | 50%             |
| ContextManager     | 50,000 tokens      | 4,800 tokens        | 90%             |

Actual savings depend on the input. The most aggressive transforms
(SmartCrusher, LogCompressor, SearchCompressor) work best on inputs with
high redundancy (repeated JSON items, repeated PASSED lines, repeated
grep hits). CodeCompressor is the most conservative — it preserves
signatures and structure, only compressing function bodies.
