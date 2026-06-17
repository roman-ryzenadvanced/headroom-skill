#!/usr/bin/env python3
"""
log_compressor.py — portable re-implementation of Headroom's LogCompressor.

Compresses build/test logs by keeping:

  1. Every line that looks like an error (ERROR, FAILED, Exception, Traceback, etc.)
  2. The full stack trace that follows an error line.
  3. Section headers / structural markers (=====, -----, *****, -----).
  4. Summary lines (counts of passed/failed/skipped).
  5. First N lines and last N lines for setup/recency context.
  6. Warnings (configurable).

Other lines are dropped. Originals are written to .headroom-cache/<sha>.txt.

Usage:
    python log_compressor.py pytest.log
    python log_compressor.py build.log --keep-first 5 --keep-last 10 --keep-warnings

Reads from stdin if no file is given. Writes compressed log to stdout.

Credits: independent re-implementation of the LogCompressor transform from
https://github.com/chopratejas/headroom (Apache 2.0).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ccr_store, estimate_tokens, is_error_line  # type: ignore


# Section markers like: ===== test session starts =====
_SECTION_RE = re.compile(r"^[=\-*/#~]{3,}.*[=\-*/#~]{3,}$|^[=\-*/#~]{3,}\s*$")

# Summary lines: "1 failed, 499 passed", "5 errors", "Ran 100 tests in 12.3s"
_SUMMARY_RE = re.compile(
    r"\b(\d+\s*(failed|passed|skipped|errors?|warnings?|tests?|items?)\b"
    r"|^Ran\s+\d+\s+tests?"
    r"|^\s*\[summary\]"
    r"|^Tests?:\s*\d+"
    r"|^Result:\s)",
    re.IGNORECASE,
)

# Warning lines
_WARN_RE = re.compile(r"\b(warn(ing)?|deprecat(ed|ion))\b", re.IGNORECASE)

# Stack trace continuation: indented, file path, line, in <func>
_TRACE_RE = re.compile(
    r"^\s+(File\s+\".*\",\s+line\s+\d+|in\s+\w+|\^+|~+|\|.*\|)"
)


def compress_log(
    text: str,
    keep_first: int = 3,
    keep_last: int = 5,
    keep_warnings: bool = False,
    trace_context: int = 15,
) -> tuple[str, dict]:
    """Return (compressed_text, stats)."""
    lines = text.splitlines()
    n = len(lines)
    if n == 0:
        return "", {"original_lines": 0, "kept_lines": 0}

    keep_idx: set[int] = set()
    kept: dict[str, list[int]] = {}

    # 1. Errors + full following traceback
    err_lines: list[int] = []
    for i, line in enumerate(lines):
        if is_error_line(line):
            err_lines.append(i)
            keep_idx.add(i)
            # Keep following traceback lines (indented File "..." / in <func>)
            for j in range(i + 1, min(n, i + 1 + trace_context)):
                if _TRACE_RE.match(lines[j]) or lines[j].startswith(" " * 4):
                    keep_idx.add(j)
                elif not lines[j].strip():
                    # Allow blank lines inside tracebacks
                    continue
                else:
                    break
    kept["errors"] = err_lines

    # 2. Section headers
    sec_lines = [i for i, line in enumerate(lines) if _SECTION_RE.match(line.strip())]
    keep_idx.update(sec_lines)
    kept["sections"] = sec_lines

    # 3. Summary lines
    sum_lines = [i for i, line in enumerate(lines) if _SUMMARY_RE.search(line)]
    keep_idx.update(sum_lines)
    kept["summaries"] = sum_lines

    # 4. Warnings
    if keep_warnings:
        warn_lines = [i for i, line in enumerate(lines) if _WARN_RE.search(line)]
        keep_idx.update(warn_lines)
        kept["warnings"] = warn_lines

    # 5. First N and last N
    first_idx = list(range(min(keep_first, n)))
    last_idx = list(range(max(0, n - keep_last), n))
    keep_idx.update(first_idx)
    keep_idx.update(last_idx)
    kept["first"] = first_idx
    kept["last"] = last_idx

    # Build output, inserting [elided N lines] markers
    sorted_idx = sorted(keep_idx)
    out_lines: list[str] = []
    prev = -1
    for i in sorted_idx:
        if i > prev + 1:
            gap = i - prev - 1
            out_lines.append(f"... [elided {gap} lines] ...")
        out_lines.append(lines[i])
        prev = i
    if prev < n - 1:
        out_lines.append(f"... [elided {n - 1 - prev} lines] ...")

    stats = {
        "original_lines": n,
        "kept_lines": len(sorted_idx),
        "kept_breakdown": {k: len(v) for k, v in kept.items()},
    }
    return "\n".join(out_lines), stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="LogCompressor: keep errors, stack traces, summaries, drop the rest.",
    )
    ap.add_argument("file", nargs="?", help="Input log file (default: stdin)")
    ap.add_argument("--keep-first", type=int, default=3)
    ap.add_argument("--keep-last", type=int, default=5)
    ap.add_argument("--keep-warnings", action="store_true",
                    help="Also keep WARNING / DeprecationWarning lines.")
    ap.add_argument("--trace-context", type=int, default=15,
                    help="Max lines of traceback to keep after an error.")
    ap.add_argument("--ccr-cache-dir", default=".headroom-cache",
                    help="Directory to write original. Empty disables.")
    ap.add_argument("--stats", action="store_true",
                    help="Print compression stats to stderr.")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    out, stats = compress_log(
        raw,
        keep_first=args.keep_first,
        keep_last=args.keep_last,
        keep_warnings=args.keep_warnings,
        trace_context=args.trace_context,
    )

    if args.ccr_cache_dir:
        key = ccr_store(raw, args.ccr_cache_dir)
        out = f"[headroom-log ccr:{key}]\n{out}"

    sys.stdout.write(out)
    if not out.endswith("\n"):
        sys.stdout.write("\n")

    if args.stats:
        tb = estimate_tokens(raw)
        ta = estimate_tokens(out)
        sys.stderr.write(
            f"log_compressor: {stats['original_lines']} -> {stats['kept_lines']} lines, "
            f"~{tb} -> ~{ta} tokens "
            f"({(1 - ta / max(1, tb)) * 100:.0f}% saved)\n"
            f"  kept: {stats['kept_breakdown']}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
