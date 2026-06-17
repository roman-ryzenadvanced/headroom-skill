#!/usr/bin/env python3
"""
code_compressor.py — portable re-implementation of Headroom's CodeCompressor.

Compresses source code by keeping:
  - All import / using / include statements.
  - All class / function / method signatures (name, args, return type).
  - All decorators.
  - The first line of each docstring.
  - The first N lines of each function body (default 3).
  - try/except, try/catch, raise, throw lines.
  - Type annotations and structural keywords (def, class, return, if, for, while).
  - Closing braces / dedent markers.

Replaces the rest of each function body with `# ... (N lines compressed)`.
Originals are written to .headroom-cache/<sha>.txt.

This is a regex-based, AST-lite compressor. It's less accurate than Headroom's
tree-sitter-based CodeAwareCompressor (which uses real AST parsing for Python,
JS, TS, Go, Rust, Java, C, C++) but captures the same intent and has zero
external dependencies.

Usage:
    python code_compressor.py module.py
    python code_compressor.py module.py --language python --max-body-lines 3 --docstring-mode first_line

Reads from stdin if no file is given. Writes compressed source to stdout.

Supported languages (regex-level): python, javascript, typescript, go, rust,
java, c, cpp. The heuristics are language-aware but conservative — when in
doubt, keep the line.

Credits: independent re-implementation of the CodeCompressor transform from
https://github.com/chopratejas/headroom (Apache 2.0).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ccr_store, estimate_tokens  # type: ignore


# ---------------------------------------------------------------------------
# Per-language patterns
# ---------------------------------------------------------------------------

# Patterns that say "always keep this line, regardless of context"
_ALWAYS_KEEP = [
    r"^\s*(import\s|from\s+\S+\s+import\s|using\s|use\s|include\s|#include\s|require\s|extern\s+crate)",
    r"^\s*(package\s+\w|mod\s+\w)",
    r"^\s*@(?:\w+|decorator)",  # decorators
    r"^\s*@",  # python decorators (broad)
    r"^\s*(public|private|protected|static|final|async|export|default|abstract|virtual|override|inline|constexpr)\b.*\b(class|struct|interface|enum|fn|func|def|function|method)\b",
    r"^\s*(class|struct|interface|enum|trait|impl|object|record|union)\s+\w",
    r"^\s*(def|func|fn|function|fun|method|sub)\s+\w",
    r"^\s*(try|except|catch|finally|raise|throw|throws|panic|unwrap\(\)|expect\()\b",
    r"^\s*return\b",
    r"^\s*(if|elif|else|for|while|switch|case|when|match|do|loop)\b",
    r"^\s*}\s*$",  # closing brace
    r"^\s*def\s|^\s*class\s",  # python (already covered but explicit)
]

# Function body start detection (per language)
_BODY_OPENERS = {
    "python": re.compile(r"^\s*(def|class)\s+\w.*:\s*$"),
    "javascript": re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\*?\s+\w+|\w+\s*\(.*\)\s*\{)\s*$"),
    "typescript": re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\*?\s+\w+|\w+\s*\(.*\)\s*(?::\s*\S+)?\s*\{)\s*$"),
    "go": re.compile(r"^\s*func\s+(?:\([^)]*\)\s+)?\w+\s*\(.*\)\s*(?:\(.*\))?\s*\{\s*$"),
    "rust": re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+.*\{\s*$"),
    "java": re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)+\w+\s+\w+\s*\(.*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{\s*$"),
    "c": re.compile(r"^\s*(?:static\s+|inline\s+|extern\s+)*\w[\w\s\*]*\s+\w+\s*\(.*\)\s*\{\s*$"),
    "cpp": re.compile(r"^\s*(?:static\s+|inline\s+|extern\s+|constexpr\s+|template\s*<[^>]*>\s*)*\w[\w\s\*:<>&]*\s+\w+\s*\(.*\)\s*\{\s*$"),
}


# Docstring patterns
_PY_DOCSTRING = re.compile(r"^\s*(\"\"\"|''')")
_JS_DOCSTRING = re.compile(r"^\s*/\*\*?")
_COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*)")


def _is_signature(line: str, language: str) -> bool:
    pat = _BODY_OPENERS.get(language)
    return bool(pat and pat.match(line))


def _is_always_keep(line: str) -> bool:
    return any(re.match(p, line) for p in _ALWAYS_KEEP)


def _is_docstring_delim(line: str) -> bool:
    return bool(_PY_DOCSTRING.match(line) or _JS_DOCSTRING.match(line))


def _is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return not s or _COMMENT_LINE.match(line)


def compress_code(
    text: str,
    language: str = "python",
    max_body_lines: int = 3,
    docstring_mode: str = "first_line",  # full | first_line | remove
    preserve_imports: bool = True,
    preserve_signatures: bool = True,
    preserve_error_handlers: bool = True,
    preserve_decorators: bool = True,
) -> tuple[str, dict]:
    """Compress source code. Returns (compressed_text, stats)."""
    lines = text.splitlines(keepends=False)
    n = len(lines)
    if n == 0:
        return "", {"original_lines": 0, "kept_lines": 0, "bodies_compressed": 0}

    out: list[str] = []
    in_body = False
    body_depth = 0
    body_start_line = -1
    body_kept_lines = 0
    in_docstring = False
    docstring_delim = None
    bodies_compressed = 0
    kept_lines = 0

    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Docstring handling
        if in_docstring:
            if docstring_mode == "full":
                out.append(line)
                kept_lines += 1
            elif docstring_mode == "first_line":
                # Already appended the first line; skip
                pass
            # remove: skip
            if docstring_delim and docstring_delim in line:
                # Closing delim — but only count if it's not the same as opening on one line
                if line.count(docstring_delim) >= 2:
                    # One-liner, already handled
                    in_docstring = False
                    docstring_delim = None
                else:
                    # Closing delim on its own line
                    if docstring_mode == "full":
                        pass  # already appended
                    in_docstring = False
                    docstring_delim = None
            i += 1
            continue

        # Open docstring?
        m = _PY_DOCSTRING.match(line) or _JS_DOCSTRING.match(line)
        if m:
            delim = m.group(1) if m.lastindex else m.group(0)
            if docstring_mode == "full":
                out.append(line)
                kept_lines += 1
                if line.count(delim) >= 2:
                    pass  # one-liner, done
                else:
                    in_docstring = True
                    docstring_delim = delim
            elif docstring_mode == "first_line":
                # Append just the first line
                if line.count(delim) >= 2:
                    out.append(line)
                else:
                    out.append(line + " ...\"\"\"")  # close it
                kept_lines += 1
            # remove: skip
            i += 1
            continue

        # Signature line opens a body
        if preserve_signatures and _is_signature(line, language):
            out.append(line)
            kept_lines += 1
            # Next non-blank, non-comment lines until we hit the body are kept
            # (e.g., decorators, type annotations on the next line).
            i += 1
            # Keep up to max_body_lines of body, then compress
            body_kept = 0
            body_total = 0
            body_buf: list[str] = []
            while i < n:
                bl = lines[i]
                if _is_blank_or_comment(bl) and not body_buf:
                    out.append(bl)
                    kept_lines += 1
                    i += 1
                    continue
                # End of body: next signature or dedent to col 0 (python)
                if (preserve_signatures and _is_signature(bl, language)) or (
                    language == "python" and bl and not bl[0].isspace() and not _is_blank_or_comment(bl)
                ):
                    break
                # Closing brace
                if bl.strip() == "}":
                    break
                body_total += 1
                # Always keep error handlers and returns
                if preserve_error_handlers and re.match(
                    r"^\s*(try|except|catch|finally|raise|throw|throws)\b", bl
                ):
                    out.append(bl)
                    kept_lines += 1
                    i += 1
                    continue
                if body_kept < max_body_lines:
                    out.append(bl)
                    body_kept += 1
                    kept_lines += 1
                body_buf.append(bl)
                i += 1
            # If we compressed anything, add a marker
            if body_total > body_kept:
                indent = "    "  # best-effort
                out.append(f"{indent}# ... ({body_total - body_kept} lines compressed) ...")
                bodies_compressed += 1
            continue

        # Imports / decorators / always-keep
        if (preserve_imports and _is_always_keep(line)) or (
            preserve_decorators and line.lstrip().startswith("@")
        ):
            out.append(line)
            kept_lines += 1
            i += 1
            continue

        # Error handlers
        if preserve_error_handlers and re.match(
            r"^\s*(try|except|catch|finally|raise|throw|throws)\b", line
        ):
            out.append(line)
            kept_lines += 1
            i += 1
            continue

        # Default: keep top-level lines (col 0) and drop nothing aggressively
        # at module scope — only compress inside bodies, which we handled above.
        out.append(line)
        kept_lines += 1
        i += 1

    stats = {
        "original_lines": n,
        "kept_lines": kept_lines,
        "bodies_compressed": bodies_compressed,
    }
    return "\n".join(out), stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CodeCompressor: keep signatures + imports + decorators, compress bodies.",
    )
    ap.add_argument("file", nargs="?", help="Source file (default: stdin)")
    ap.add_argument("--language", default="python",
                    choices=["python", "javascript", "typescript", "go", "rust", "java", "c", "cpp"])
    ap.add_argument("--max-body-lines", type=int, default=3,
                    help="Lines of each function body to keep before compressing.")
    ap.add_argument("--docstring-mode", default="first_line",
                    choices=["full", "first_line", "remove"])
    ap.add_argument("--no-imports", action="store_true", help="Don't preserve imports.")
    ap.add_argument("--no-signatures", action="store_true", help="Don't preserve signatures.")
    ap.add_argument("--no-error-handlers", action="store_true")
    ap.add_argument("--no-decorators", action="store_true")
    ap.add_argument("--ccr-cache-dir", default=".headroom-cache")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    out, stats = compress_code(
        raw,
        language=args.language,
        max_body_lines=args.max_body_lines,
        docstring_mode=args.docstring_mode,
        preserve_imports=not args.no_imports,
        preserve_signatures=not args.no_signatures,
        preserve_error_handlers=not args.no_error_handlers,
        preserve_decorators=not args.no_decorators,
    )

    if args.ccr_cache_dir:
        key = ccr_store(raw, args.ccr_cache_dir)
        out = f"# [headroom-code ccr:{key} language={args.language}]\n{out}"

    sys.stdout.write(out)
    if not out.endswith("\n"):
        sys.stdout.write("\n")

    if args.stats:
        tb = estimate_tokens(raw)
        ta = estimate_tokens(out)
        sys.stderr.write(
            f"code_compressor: {stats['original_lines']} -> {stats['kept_lines']} lines, "
            f"{stats['bodies_compressed']} bodies compressed, "
            f"~{tb} -> ~{ta} tokens "
            f"({(1 - ta / max(1, tb)) * 100:.0f}% saved)\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
