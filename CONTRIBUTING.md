# Contributing to headroom-skill

Thanks for your interest in improving this portable skill.

## The bar for new helpers

The portable skill deliberately stays **Python 3 stdlib only**. New
helper scripts must:

- Run on Python 3.8+ with no `pip install` required.
- Not import any third-party packages (no `requests`, no `numpy`, no
  `tree-sitter`, no `transformers`).
- Match the behaviour of the corresponding upstream Headroom transform
  as documented in `docs/techniques.md`.
- Follow the CCR convention: write originals to `.headroom-cache/<sha>.txt`
  and cite the key in the output.
- Pass the smoke tests in `../scripts/test_skill.py` (or add new tests
  there).

## The bar for rule changes

Changes to `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, or the files in
`prompts/` should:

- Explain the *why* — what failure mode does this rule prevent?
- Be general, not overfit to a specific example.
- Avoid heavy-handed `MUST` / `NEVER` where a reasoned explanation
  works better. LLMs are smart; explain the reasoning.

## The bar for new integrations

A new agent integration in `docs/integrations.md` should:

- Be tested with at least one real version of the agent.
- Include both project-local and global install paths where the agent
  supports both.
- Note any agent-specific quirks (e.g. "Cursor `.mdc` files need
  frontmatter").

## Development workflow

```bash
git clone https://github.com/<your-username>/headroom-skill.git
cd headroom-skill

# Run the smoke tests
python /path/to/scripts/test_skill.py

# Try the scripts on a real tool output
rg "foo" src/ | python scripts/search_compressor.py --query "foo" --stats
```

## Adding a new transform

1. Read the corresponding upstream Headroom transform's source:
   `https://github.com/chopratejas/headroom/tree/main/crates/headroom-core/src/transforms`
2. Write `scripts/<name>_compressor.py` — stdlib only, follows the
   `_common.py` helpers.
3. Add a section to `docs/techniques.md` documenting the algorithm.
4. Add a row to the routing table in `AGENTS.md` and `SKILL.md`.
5. Add a smoke test to `scripts/test_skill.py`.
6. Add a before/after example to `examples/before_after.md`.

## License

By contributing, you agree your contributions are licensed under the
Apache 2.0 license, same as the rest of this repo and same as upstream
Headroom.

## Attribution

If you're adding a transform that exists in upstream Headroom, **credit
the original**. The convention is a comment at the top of the script:

```python
"""
<script>.py — portable re-implementation of Headroom's <TransformName>.

Credits: independent re-implementation of the <TransformName> transform from
https://github.com/chopratejas/headroom (Apache 2.0).
"""
```
