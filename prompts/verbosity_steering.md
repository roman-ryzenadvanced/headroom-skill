# Verbosity steering — L0 through L4

These are the system-prompt fragments that implement Headroom's output-token
shaper. Append the selected level to the **tail** of the system prompt
(after any `cache_control` breakpoint, so the cached prefix stays warm).

The default level is **L2**. The five levels are cumulative: L2 = L1 + its
own rules; L3 = L2 + its own rules; etc.

> **Why the tail, not the head.** Prompt caching is a prefix match. Any byte
> change ahead of a `cache_control` breakpoint invalidates everything after
> it. Prepending steering text would bust the provider prefix cache and cost
> more than it saves. Appending after the last system block leaves the cached
> prefix byte-identical; only the small, byte-stable steering block is
> reprocessed.

---

## L0 — off

(No text appended. Write naturally.)

---

## L1 — no ceremony

```
[Output style — L1]
Skip preambles ("Great, let me help with that…") and postambles ("Let me
know if you need anything else!"). Start with the answer. End when the
answer is complete. Do not narrate what you are about to do; just do it.
```

---

## L2 — no ceremony + no echo  (DEFAULT)

```
[Output style — L2]
1. Skip preambles and postambles. Start with the answer.
2. Do not restate code, diffs, or tool output that is already on screen.
   Reference it by `path:line` instead of reprinting.
3. Do not narrate tool results the user can already see ("I read the file
   and found…"). Go straight to the conclusion the tool result supports.
4. When proposing a change, show the smallest edit that conveys the change.
   Do not re-print the entire file.
```

This is the safe default. In upstream Headroom's benchmarks, L2 produced
no accuracy loss on GSM8K, TruthfulQA, SQuAD v2, or BFCL while saving
~28% of output tokens.

---

## L3 — conclusions only

```
[Output style — L3]
1. (All of L2.)
2. Conclusions only. Skip the reasoning unless the user asks "why?".
3. Prefer the smallest edit that fixes the problem. Do not refactor
   unrelated code in the same change.
4. When asked to investigate, give the root cause and the fix. Do not list
   every hypothesis you considered and rejected.
```

Use L3 when the user asks for brevity, when the turn is a mechanical
continuation (see `effort_routing.md`), or when the user is clearly an
expert who doesn't need the reasoning.

---

## L4 — caveman

```
[Output style — L4]
Minimum tokens. Fragments OK. No full sentences unless safety requires.
Just the answer. No code if a one-line shell command will do. No
explanation unless asked.
```

Use L4 only when the user explicitly asks for maximum terseness, or when
the conversation is clearly a quick back-and-forth (e.g. iterating on a
single value). L4 sacrifices clarity for tokens and should not be the
default.

---

## How to pick the level

| Situation                                       | Level |
|-------------------------------------------------|-------|
| Default                                         | L2    |
| User asks "be brief" / "short" / "terser"       | L3    |
| User asks "minimum tokens" / "just the answer"  | L4    |
| User asks "explain in detail" / "walk me through"| L0 or L1 |
| Mechanical continuation after a successful tool | L3    |
| Error continuation (tool returned `is_error`)   | L2 (keep full effort) |
| New user question                               | L2    |
| Demonstrating a concept to a learner            | L1    |
| Code review with explanations                   | L1    |

## Per-user learning (advanced)

Upstream Headroom has a `headroom learn --verbosity` command that mines
past sessions to pick the right level per user. The signals it looks for:

- **Interrupts** — the user interrupts the model mid-reply (push-back
  signal; suggests the model is being too verbose).
- **Fast-skips** — the user replies so quickly they couldn't have read the
  whole previous answer (strongest signal; suggests the answer was too
  long).
- **Read-throughs** — the user pauses long enough to have read the answer
  before replying (suggests the verbosity was appropriate).

If you're an agent with access to user timing data, you can apply the same
heuristics. If you're not, default to L2 and let the user adjust.

## Implementation notes for agent authors

- The steering text should be **byte-stable per level**. Don't include
  timestamps, request IDs, or other dynamic content in the steering block.
- Mark the steering block with a sentinel (e.g. `[Output style — L2]`) so
  repeated requests replace the block in place rather than stacking.
- Append the steering text **after** the last `cache_control` breakpoint
  in the system prompt, so the cached prefix is untouched.
- If the client supports `output_config.effort` (Anthropic, some OpenAI
  models), lower effort on mechanical continuations. See
  `effort_routing.md`.
- Never disable `thinking` outright on models that have it — that errors.
  Only lower the effort / budget.
