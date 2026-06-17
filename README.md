# headroom-skill

> A portable, framework-agnostic **skill** that teaches any coding agent (Claude Code, Codex, Cursor, Aider, Hermes, OpenClaw / Claw, Goose, Continue, OpenHands, vibe, Copilot CLI, …) how to slash token usage the same way [Headroom](https://github.com/chopratejas/headroom) does — without installing the Headroom binary.

<p align="center">
  <strong>60–95% fewer tokens · no proxy required · drop-in agent rules · helper scripts · reversible</strong>
</p>

---

## What this is

[Headroom](https://github.com/chopratejas/headroom) is a fantastic local proxy + library that compresses everything an AI agent reads before it reaches the LLM. It ships as a Python/Rust binary, runs as a proxy, and wraps existing CLI agents.

**This repo is the *technique set* behind Headroom, distilled into a portable skill that any agent can apply *in-context*, with no installation.** Drop the markdown rules into your agent's context, optionally call the bundled Python helpers, and your agent starts compressing JSON tool output, build logs, search results, source code, and conversation history exactly the way Headroom does.

The skill captures the six Headroom transforms that account for the majority of token savings:

| Headroom transform         | What it does                                              | Portable-skill equivalent                  |
|----------------------------|-----------------------------------------------------------|--------------------------------------------|
| **SmartCrusher**           | Statistical selection from JSON arrays                    | `scripts/smart_crusher.py` + rules         |
| **CodeCompressor**         | AST-aware code compression (signatures kept, bodies cut)  | `scripts/code_compressor.py` + rules       |
| **LogCompressor**          | Keep errors / stack traces / summary; drop passing tests  | `scripts/log_compressor.py` + rules        |
| **SearchCompressor**       | BM25-style relevance selection over grep/ripgrep output   | `scripts/search_compressor.py` + rules     |
| **CacheAligner**           | Move dynamic content to the tail so KV caches hit         | Rules in `prompts/cache_alignment.md`      |
| **RollingWindow / IntelligentContext** | Drop oldest tool outputs first, keep system + recent turns | `scripts/context_manager.py` + rules       |
| **Output Token Shaper**    | Trim what the model *writes back* (verbosity L0–L4, effort routing) | `prompts/verbosity_steering.md`            |
| **CCR (reversible)**       | Cache originals, retrieve on demand                       | Convention: write originals to `.headroom-cache/` |

## Why a skill instead of the binary?

Headroom-the-binary is the right call when you can install things and run a proxy. A skill is the right call when:

- You're inside a sandboxed agent (Hermes, Claw, devcontainer) that can't run a long-lived proxy.
- You want the agent itself to apply compression *in-context* — e.g. compress a 50 KB tool result before pasting it into the next message.
- You're on a restricted network where the binary's ML assets (Kompress-v2-base from HuggingFace, ONNX Runtime from cdn.pyke.io) aren't reachable.
- You want zero new dependencies — every helper script in this repo is Python 3 stdlib only.

## Get started (30 seconds)

```bash
git clone https://github.com/roman-ryzenadvanced/headroom-skill.git
cd headroom-skill
```

Pick the integration mode that matches your agent:

### 1. As agent rules (works everywhere)

Append or symlink the right rules file into your agent's context:

| Agent                          | File to use                       | Where it goes                                  |
|--------------------------------|-----------------------------------|------------------------------------------------|
| Claude Code / Anthropic Claude | `CLAUDE.md`                       | project root, `~/.claude/CLAUDE.md`, or skill  |
| OpenAI Codex / GPT Codex CLI   | `AGENTS.md`                       | project root or `~/.codex/AGENTS.md`           |
| Cursor                         | `AGENTS.md`                       | `.cursor/rules/headroom.mdc` (referenced)      |
| Aider                          | `AGENTS.md` (loaded as conventions) | `.aider.conf.yml` `--read` flag                |
| OpenClaw / Claw                | `AGENTS.md`                       | `.claw/context/` or plugin context             |
| Hermes                         | `AGENTS.md`                       | `HERMES_RULES.md` or agent system prompt       |
| Goose, Continue, OpenHands, vibe, Copilot CLI | `AGENTS.md`         | each tool's rules / conventions file           |

### 2. As helper scripts

Copy `scripts/` into your project (or call them in-place). They're stdlib-only Python 3 — no `pip install` needed.

```bash
# Compress a 1000-row JSON tool result to ~50 most informative rows
python scripts/smart_crusher.py results.json --query "user signup error" --keep-first 3 --keep-last 2

# Compress a 10k-line pytest log to errors + summary + first/last few lines
python scripts/log_compressor.py pytest.log

# Compress a grep/ripgrep result by BM25 relevance to the query
python scripts/search_compressor.py grep.out --query "auth token refresh"

# Compress a source file: keep imports + signatures + decorators, drop bodies
python scripts/code_compressor.py module.py --language python --max-body-lines 3

# Apply a rolling window over a JSONL conversation transcript
python scripts/context_manager.py transcript.jsonl --max-tokens 100000 --keep-last-turns 5
```

### 3. As system-prompt fragments

Drop the contents of `prompts/verbosity_steering.md` into your agent's system prompt to get the same **output-token reduction** that Headroom's `HEADROOM_OUTPUT_SHAPER=1` proxy flag gives you. Level 2 is the safe default; level 4 is "caveman mode" for maximum savings.

## What you get

Realistic savings on common agent workloads (numbers from the upstream Headroom benchmarks; the portable skill targets the same ratios):

| Workload                      | Before   | After    | Savings |
|-------------------------------|---------:|---------:|--------:|
| Code search (100 results)     | 17,765   | 1,408    | ~92%    |
| SRE incident debugging log    | 65,694   | 5,118    | ~92%    |
| GitHub issue triage JSON      | 54,174   | 14,761   | ~73%    |
| Large source file (read)      | varies   | varies   | ~50–70% |
| Model output (verbosity L2)   | baseline | −25–30%  | ~28%    |

## Repository layout

```
headroom-skill/                       (cloned from github.com/roman-ryzenadvanced/headroom-skill)
├── README.md                     this file
├── LICENSE                       Apache 2.0 (matches upstream)
├── NOTICE                        attribution notice
├── SKILL.md                      portable skill manifest (frontmatter + body)
├── AGENTS.md                     universal agent rules — works with any agent
├── CLAUDE.md                     Claude Code / Cursor specific copy
├── docs/
│   ├── techniques.md             deep dive into each compression technique
│   ├── integrations.md           per-agent setup instructions
│   └── reversible-ccr.md         how the on-disk CCR cache convention works
├── scripts/
│   ├── smart_crusher.py          JSON array compressor (statistical selection)
│   ├── log_compressor.py         build / test log compressor
│   ├── search_compressor.py      grep / ripgrep result compressor
│   ├── code_compressor.py        source-code compressor (regex-based AST-lite)
│   ├── context_manager.py        rolling-window + importance scoring
│   └── _common.py                shared helpers (token estimate, entropy, BM25)
├── prompts/
│   ├── verbosity_steering.md     L0–L4 output-token shaping system-prompt fragments
│   ├── effort_routing.md         turn-classification rules (mechanical vs new ask)
│   └── cache_alignment.md        prefix-stability rules for KV-cache friendliness
└── examples/
    ├── before_after_json.md      SmartCrusher before/after
    ├── before_after_log.md       LogCompressor before/after
    ├── before_after_code.md      CodeCompressor before/after
    └── before_after_search.md    SearchCompressor before/after
```

## How agents use this

The skill teaches the agent two complementary behaviours:

1. **In-context compression.** When the agent is about to paste a 5,000-line tool result into its next message, it should first compress that result by applying the matching transform — either by running the helper script, or by hand if no script is available. The rules in `AGENTS.md` tell the agent *which* transform to pick based on content type.
2. **Output token shaping.** When the agent generates its reply, it should follow the verbosity rules in `prompts/verbosity_steering.md`. Level 2 is the safe default and roughly matches what Headroom's proxy does with `HEADROOM_OUTPUT_SHAPER=1` and `HEADROOM_VERBOSITY_LEVEL=2`.

Together, these give you the same token savings Headroom reports, without running a proxy.

## Credits & attribution

This skill is a **portable re-implementation of the techniques** in [chopratejas/headroom](https://github.com/chopratejas/headroom). All credit for the original algorithms, design, and benchmarks belongs to the Headroom authors.

- **Headroom** — by [Tejas Chopra](https://github.com/chopratejas) and contributors. Licensed Apache 2.0.
  Original repo: <https://github.com/chopratejas/headroom>
  Docs: <https://headroom-docs.vercel.app/docs>
- **Kompress-v2-base** — the ML text-compression model behind Headroom's `[ml]` extra, by the same authors. <https://huggingface.co/chopratejas/kompress-v2-base>
- **RTK** — referenced by Headroom for shell-output rewriting. <https://github.com/rtk-ai/rtk>
- **lean-ctx** — referenced by Headroom as an alternative CLI context tool. <https://github.com/yvgude/lean-ctx>

The Headroom transforms were studied from the upstream `wiki/`, `docs/`, and `crates/headroom-core/src/transforms/` sources. The portable scripts in this repo are **independent re-implementations in pure Python (stdlib only)** — they do not link to or import Headroom code. They are simpler and weaker than the upstream Rust + ML implementations, but capture the same selection heuristics and produce similar savings ratios on the workloads Headroom benchmarks.

If you have the option to install the real Headroom binary, **you should** — it's faster, more accurate, and ML-backed. This skill exists for the cases where you can't.

## License

Apache 2.0 — see [`LICENSE`](LICENSE). Same license as upstream Headroom.

## Contributing

PRs welcome. The bar for new helpers: pure Python stdlib, no new dependencies, behaviour matches the corresponding upstream Headroom transform as documented in `docs/techniques.md`.

## When to use this vs the real Headroom

| Use this skill when…                                | Use the real Headroom when…                              |
|-----------------------------------------------------|----------------------------------------------------------|
| You can't run a long-lived proxy                    | You can `pip install headroom-ai[all]`                   |
| You're in a sandboxed agent without install rights  | You want ML-backed text compression (Kompress-v2)        |
| You want the agent itself to compress in-context    | You want a transparent proxy that wraps any CLI agent    |
| You want zero new dependencies                      | You want AST-accurate code compression (tree-sitter)     |
| You just want the *technique* embedded in prompts   | You want the dashboard, memory, and cross-agent features |

The two are not exclusive — many users run Headroom-the-binary as a proxy **and** keep this skill loaded for in-context compression of things the proxy can't see (e.g. an agent's own internal scratchpad).
