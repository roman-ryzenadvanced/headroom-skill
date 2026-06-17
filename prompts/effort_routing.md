# Effort routing — turn classification rules

Companion to `verbosity_steering.md`. Classifies each turn before the model
generates, so we can route mechanical continuations to lower effort and
keep full effort for new asks and error recovery.

In upstream Headroom, this runs in the proxy and clamps
`output_config.effort` (Anthropic) or `thinking.budget_tokens` (legacy
models) on mechanical turns. In the portable skill, the agent itself
applies the classification before deciding how much reasoning to do.

## The classification

Look at the **last message** in the conversation (the one the model is
about to respond to). Classify based on its content:

| Last message contains…                                       | Classification            | Verbosity | Effort  |
|--------------------------------------------------------------|---------------------------|-----------|---------|
| A new question or instruction (text, image, document block)  | `NEW_USER_ASK`            | L2        | full    |
| Only `tool_result`, all `is_error: false`                    | `MECHANICAL_CONTINUATION` | L3        | low     |
| Any `tool_result` with `is_error: true`                      | `ERROR_CONTINUATION`      | L2        | full    |
| Anything else                                                | `UNKNOWN`                 | L2        | full    |

## Why this works

In an agentic loop, most API calls are mechanical continuations: the model
just read a file (no errors), or ran a test (it passed), or did a search
(got results). The model is just resuming. Harnesses like Claude Code pin
`output_config.effort` at `xhigh` for *every* turn, including these — and
effort drives thinking depth, which bills as output tokens.

Lowering effort on mechanical turns cuts output tokens by ~30% on those
turns, with no measurable accuracy loss on standard benchmarks.

## Concrete rules

### `NEW_USER_ASK`
The user asked a new question or gave a new instruction. The model needs
full reasoning. Verbosity L2, effort full.

Detection: the last message has `role: user` AND contains any text/image/
document block.

### `MECHANICAL_CONTINUATION`
The previous turn was a tool call, the tool succeeded, and there's no new
user input. The model is resuming. Lower effort to `low`, drop verbosity
to L3.

Detection: the last message has `role: tool` (or contains a `tool_result`
block) AND no `is_error: true` AND there's no new user message after it.

### `ERROR_CONTINUATION`
The previous turn was a tool call, the tool failed (`is_error: true`). The
model needs to reason about the failure. Keep effort at full, verbosity L2.

Detection: the last message has `role: tool` (or contains a `tool_result`
block) AND at least one block has `is_error: true`.

### `UNKNOWN`
Anything else (e.g. an assistant message with no following user/tool
message — shouldn't happen in normal flow). Default to L2 + full effort.

## What "lower effort" means per provider

### Anthropic (Claude)
- Lower `output_config.effort` from `xhigh`/`high` to `low` on mechanical
  turns.
- Never inject `output_config.effort` where the client didn't send it —
  models without effort support 400 on it. Lowering an already-present
  value is always valid; its presence proves the model accepts the param.
- On legacy models with `thinking: {type: "enabled", budget_tokens: N}`,
  clamp `N` to the API floor (1024) on mechanical turns.
- **Never toggle `thinking.type`.** Disabling thinking while history
  carries thinking blocks 400s on some models.

### OpenAI (GPT-4o, o1, etc.)
- Lower `reasoning.effort` from `high` to `low` on mechanical turns (o1/o3
  models).
- For GPT-4o and below, no equivalent param — rely on verbosity steering
  alone.

### Gemini
- Lower `thinkingConfig.thinkingBudget` on mechanical turns (Gemini 2.5+).
- Keep `0` as the floor (the model can still answer).

### Open-source / local
- Most local runtimes don't expose effort. Rely on verbosity steering
  alone.

## Safety rules (each prevents a concrete failure)

1. **Never inject `effort` where the client didn't send it.** Models
   without effort support return 400 on it. Lowering an already-present
   value is always valid — its presence proves the target model accepts
   the param.
2. **Never toggle `thinking.type`.** Disabling thinking while history
   carries thinking blocks 400s on some models, and the toggle busts the
   messages cache tier.
3. **Byte-stable, idempotent steering.** Repeated requests keep an
   identical prefix; cache stays warm.
4. **Respect `x-headroom-bypass`.** Sub-agent calls that opt out of
   compression also opt out of shaping. (In the portable skill: respect
   the user's "don't compress this" instructions.)

## Implementation example (Python, for agent authors)

```python
def classify_turn(messages: list[dict]) -> str:
    if not messages:
        return "UNKNOWN"
    last = messages[-1]
    # Tool result with no new user ask after it
    if last.get("role") == "tool" or _has_tool_result_block(last):
        if _any_tool_result_is_error(last):
            return "ERROR_CONTINUATION"
        return "MECHANICAL_CONTINUATION"
    if last.get("role") == "user" and _has_text_or_image(last):
        return "NEW_USER_ASK"
    return "UNKNOWN"

def pick_verbosity_and_effort(classification: str) -> tuple[int, str]:
    return {
        "NEW_USER_ASK":            (2, "full"),
        "MECHANICAL_CONTINUATION": (3, "low"),
        "ERROR_CONTINUATION":      (2, "full"),
        "UNKNOWN":                 (2, "full"),
    }.get(classification, (2, "full"))
```

## When to bypass

- The user explicitly asks for a detailed explanation → L1 + full effort,
  regardless of classification.
- The user explicitly asks for "just the answer" → L4 + low effort,
  regardless of classification.
- The user is debugging an error and asks "why?" → L1 + full effort, even
  on a mechanical continuation.
- The task is high-stakes (security review, prod deploy) → L2 + full
  effort, never mechanical.
