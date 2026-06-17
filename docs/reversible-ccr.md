# Reversible compression — CCR cache convention

CCR (Compress-Cache-Retrieve) is Headroom's answer to "compression is
lossy — how do I get the original back if I need it?". The portable
skill uses a simple on-disk convention that mirrors CCR's behaviour.

## The convention

Before compressing any content, the helper scripts:

1. Compute `sha256(original_content)`, truncated to the first 12 hex
   chars. Call this the **CCR key**.
2. Write the original to `.headroom-cache/<key>.txt`.
3. Compress the content.
4. Prepend a header to the compressed output citing the key:

   ```
   [headroom-log ccr:bb5b11469a04]
   ```

   or for JSON:

   ```json
   {"_headroom": {"ccr_key": "bb5b11469a04", "compressed": true, ...}, ...}
   ```

When a later turn needs the original (the user asks "what was the full
log?" or the agent finds it needs more context), retrieve it:

```bash
cat .headroom-cache/bb5b11469a04.txt
```

## Why a file on disk?

- **Local only.** The original never goes to the LLM unless retrieved.
- **Content-addressed.** Identical inputs produce identical keys, so
  running the same compression twice doesn't double-store.
- **Survives across turns.** The cache persists for the duration of the
  session (or until manually cleaned).
- **No new dependencies.** Just `os.makedirs` and `open()`.

## Cache directory

Default: `.headroom-cache/` in the current working directory.

Override with `--ccr-cache-dir <path>` on any script, or set the
environment variable `HEADROOM_CCR_CACHE_DIR`.

Add to `.gitignore`:

```
.headroom-cache/
```

## Cleanup

The cache can grow large over a long session. Clean it periodically:

```bash
# Delete entries older than 7 days
find .headroom-cache -mtime +7 -delete

# Delete everything (e.g. at session end)
rm -rf .headroom-cache/
```

## Retrieval

To retrieve an original by key:

```bash
cat .headroom-cache/<key>.txt
```

The helper `ccr_retrieve(key)` in `scripts/_common.py` does this
programmatically (with basic key-format validation).

## CCR key format

The key is the first 12 hex chars of `sha256(original_content)`. This
gives a 48-bit address space — collision probability is negligible for
typical session sizes (millions of entries).

If you need stronger guarantees, change the `length` parameter in
`sha256_short()` (in `scripts/_common.py`) to 16, 20, or the full 64.

## What gets cached

| Transform         | What's cached                |
|-------------------|------------------------------|
| SmartCrusher      | The original JSON document   |
| LogCompressor     | The original log text        |
| SearchCompressor  | The original search output   |
| CodeCompressor    | The original source file     |
| ContextManager    | The original transcript      |

The cache key is computed **before** any compression, so it's the
unmodified original.

## What does NOT get cached

- The agent's own narration (the "Compressed 1,432 → 187 tokens…"
  line). That's generated text, not original content.
- The compressed output. That's already in the conversation; caching it
  would be redundant.
- The user's messages or the assistant's replies. Those are sacred and
  never compressed, so they don't need a CCR cache.

## Comparison to upstream Headroom CCR

Upstream Headroom stores CCR originals in a SQLite-backed store with
TTLs, eviction policies, and cross-agent retrieval. The portable skill
uses a flat-file directory because:

- No `pip install` (SQLite is stdlib but the schema isn't worth it for
  a session-scoped cache).
- Easy to inspect (`ls .headroom-cache/`).
- Easy to clean (`rm -rf .headroom-cache/`).
- Easy to grep (`grep -l "FATAL" .headroom-cache/*.txt`).

If you need TTLs, eviction, or cross-agent retrieval, install upstream
Headroom and use its real CCR.

## Privacy and security

- The cache is local. It is never sent to the LLM unless retrieved.
- The cache may contain sensitive data (logs with PII, source code
  with secrets). Treat the `.headroom-cache/` directory as you would
  any other local cache of sensitive data:
  - Add it to `.gitignore`.
  - Don't sync it to cloud storage.
  - Clean it at the end of sensitive sessions.
  - On shared machines, set `HEADROOM_CCR_CACHE_DIR` to a private
    path inside `~/.cache/` or similar.
