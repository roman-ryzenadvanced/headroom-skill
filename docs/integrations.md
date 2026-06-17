# Integrations — per-agent setup

This file shows how to load the headroom-skill rules into each major
coding agent. The pattern is the same everywhere: **put the rules where
the agent reads them, optionally copy the scripts to a known location**.

The rules file to use is `AGENTS.md` (universal). For Claude Code, use
`CLAUDE.md` instead (same content, different filename convention).

## Table of contents

- [Claude Code (Anthropic)](#claude-code-anthropic)
- [Cursor](#cursor)
- [OpenAI Codex / Codex CLI](#openai-codex--codex-cli)
- [Aider](#aider)
- [OpenClaw / Claw](#openclaw--claw)
- [Hermes](#hermes)
- [Goose (Block)](#goose-block)
- [Continue](#continue)
- [OpenHands](#openhands)
- [vibe](#vibe)
- [GitHub Copilot CLI](#github-copilot-cli)
- [Generic / any agent](#generic--any-agent)

---

## Claude Code (Anthropic)

Claude Code reads `CLAUDE.md` from the project root and from `~/.claude/`
at session start. Project-level takes precedence.

**Option A — project-local (recommended for team workflows):**

```bash
cd /path/to/your/project
cp /path/to/headroom-skill-portable/CLAUDE.md ./CLAUDE.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

**Option B — user-global (applies to all projects):**

```bash
mkdir -p ~/.claude
cat /path/to/headroom-skill-portable/CLAUDE.md >> ~/.claude/CLAUDE.md
# Optionally copy scripts to a stable location
mkdir -p ~/.local/share/headroom-skill
cp -r /path/to/headroom-skill-portable/scripts ~/.local/share/headroom-skill/
```

Then add a one-liner to your `~/.claude/CLAUDE.md` pointing to the
scripts:

```markdown
Headroom scripts live at `~/.local/share/headroom-skill/scripts/`. Run
them as `python ~/.local/share/headroom-skill/scripts/smart_crusher.py …`.
```

**Option C — as a Claude Code Skill (skill-system install):**

If you're using the Claude Code skill system, drop the
`headroom-skill-portable/` directory into `~/.claude/skills/headroom/`
and Claude Code will load `SKILL.md` automatically when relevant.

---

## Cursor

Cursor reads `.cursor/rules/*.mdc` files. Each `.mdc` file is a rule
with frontmatter.

```bash
mkdir -p .cursor/rules
cp /path/to/headroom-skill-portable/AGENTS.md .cursor/rules/headroom.mdc
```

Add the frontmatter to the top of `.cursor/rules/headroom.mdc`:

```yaml
---
description: Token-reduction rules (SmartCrusher, LogCompressor, etc.). Apply when tool output is large or context is filling up.
globs: ["*"]
alwaysApply: true
---
```

Copy the scripts:

```bash
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

---

## OpenAI Codex / Codex CLI

Codex CLI reads `AGENTS.md` from the project root and `~/.codex/AGENTS.md`
globally.

```bash
cd /path/to/your/project
cp /path/to/headroom-skill-portable/AGENTS.md ./AGENTS.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

For global install:

```bash
mkdir -p ~/.codex
cat /path/to/headroom-skill-portable/AGENTS.md >> ~/.codex/AGENTS.md
```

---

## Aider

Aider doesn't read `AGENTS.md` natively, but you can pass it as a "read
file" via `--read` or `.aider.conf.yml`.

```bash
cp /path/to/headroom-skill-portable/AGENTS.md ./CONVENTIONS.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
```

In `.aider.conf.yml`:

```yaml
read:
  - CONVENTIONS.md
```

Or on the command line:

```bash
aider --read CONVENTIONS.md ...
```

---

## OpenClaw / Claw

OpenClaw supports plugins and a context-engine hook. The Headroom
upstream project ships a native `plugins/openclaw/` plugin that wires
Headroom-the-binary in as a ContextEngine.

For the **portable skill** (no binary):

```bash
mkdir -p .claw/context
cp /path/to/headroom-skill-portable/AGENTS.md .claw/context/headroom.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
```

If your Claw build reads `AGENTS.md` from the project root (most do, for
interoperability), just drop it there:

```bash
cp /path/to/headroom-skill-portable/AGENTS.md ./AGENTS.md
```

For a deeper integration — wiring the helper scripts as Claw tools —
follow your Claw build's plugin docs. The four scripts are stdlib-only
Python 3; they accept stdin and write to stdout, so they're trivial to
wrap as Claw tool calls.

---

## Hermes

Hermes typically loads a rules file specified in its agent config. The
exact path varies by Hermes version and config, but the common
convention is `HERMES_RULES.md` or `AGENTS.md` at the project root.

```bash
cp /path/to/headroom-skill-portable/AGENTS.md ./AGENTS.md
cp /path/to/headroom-skill-portable/AGENTS.md ./HERMES_RULES.md  # if your Hermes build looks for this
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

If your Hermes build supports a system-prompt fragment include, add the
contents of `prompts/verbosity_steering.md` to the system prompt tail.

---

## Goose (Block)

Goose reads `.goosehints` files. Drop the rules there:

```bash
cp /path/to/headroom-skill-portable/AGENTS.md .goosehints
cp -r /path/to/headroom-skill-portable/scripts ./scripts
```

For a per-project rules file, use `.goosehints` in the project root. For
session-wide, use `~/.config/goose/.goosehints`.

---

## Continue

Continue reads `.continue/rules/*.md` (in newer versions) or
`config.yaml` (older). For the rules-based approach:

```bash
mkdir -p .continue/rules
cp /path/to/headroom-skill-portable/AGENTS.md .continue/rules/headroom.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
```

---

## OpenHands

OpenHands reads `AGENTS.md` from the workspace root.

```bash
cp /path/to/headroom-skill-portable/AGENTS.md ./AGENTS.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

---

## vibe

vibe reads `AGENTS.md` from the project root.

```bash
cp /path/to/headroom-skill-portable/AGENTS.md ./AGENTS.md
cp -r /path/to/headroom-skill-portable/scripts ./scripts
echo ".headroom-cache/" >> .gitignore
```

---

## GitHub Copilot CLI

Copilot CLI doesn't read project rules natively. The portable skill
works best here by **running the scripts manually** before pasting tool
output, or by setting the `HEADROOM_OUTPUT_SHAPER=1` equivalent — which
for Copilot CLI means crafting a custom system prompt.

If you've installed the upstream Headroom binary, the native integration
is:

```bash
headroom copilot-auth login
headroom wrap copilot --subscription -- --model gpt-4o
```

For the portable skill (no binary), pre-compress tool output manually:

```bash
# Instead of pasting a 1000-line grep result into Copilot CLI:
rg "auth" src/ | python /path/to/scripts/search_compressor.py --query "auth token" --max-items 20 > compressed.txt
# Then paste compressed.txt into Copilot CLI
```

---

## Generic / any agent

For any agent that reads a rules file:

1. Find the rules file. Common conventions: `AGENTS.md`, `CLAUDE.md`,
   `.cursor/rules/`, `.aider.conf.yml --read`, `.goosehints`,
   `.continue/rules/`, `HERMES_RULES.md`, `CONVENTIONS.md`.
2. Append or symlink the contents of `AGENTS.md` into that file.
3. Copy `scripts/` to a stable location (project root, `~/.local/share/`,
   etc.).
4. Add `.headroom-cache/` to `.gitignore`.
5. (Optional) Add `prompts/verbosity_steering.md` contents to the
   agent's system prompt tail, for output-token reduction.

If your agent supports MCP, you can wrap the four scripts as MCP tools.
The scripts are stdlib-only Python 3, accept stdin, write to stdout, and
exit 0 on success — they're trivial to wrap.
