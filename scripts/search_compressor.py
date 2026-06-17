#!/usr/bin/env python3
"""
search_compressor.py — portable re-implementation of Headroom's SearchCompressor.

Compresses grep / ripgrep / ag output (lines of the form `file:line:content`)
by selecting the most relevant matches to the user's query:

  1. Every match that contains an error keyword.
  2. First N matches (first hit in each file, for diversity).
  3. Last N matches (most recent).
  4. Top-K matches by BM25 similarity to the query.
  5. One match per unique file path (file diversity), keeping the highest-scored.
  6. Sample of the remainder, up to a cap.

Originals are written to .headroom-cache/<sha>.txt.

Usage:
    python search_compressor.py grep.out --query "auth token refresh"
    rg "foo" src/ | python search_compressor.py --query "foo" --keep-first 5

Reads from stdin if no file is given. Writes compressed output to stdout.

Credits: independent re-implementation of the SearchCompressor transform from
https://github.com/chopratejas/headroom (Apache 2.0).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import bm25_scores, ccr_store, estimate_tokens, is_error_line  # type: ignore


# Match `path:line:content` or `path:line:col:content` (ripgrep --column)
_LINE_RE = re.compile(r"^(?P<path>[^:]+?):(?P<line>\d+)(?::\d+)?:\s?(?P<content>.*)$")


def parse_match(line: str) -> dict | None:
    m = _LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None
    return {
        "raw": line.rstrip("\n"),
        "path": m.group("path"),
        "line": int(m.group("line")),
        "content": m.group("content"),
    }


def compress_search(
    text: str,
    query: str,
    keep_first: int = 3,
    keep_last: int = 2,
    relevance_top_k: int = 10,
    max_items: int = 50,
    per_file_diversity: int = 3,
) -> tuple[str, dict]:
    """Compress search output. Returns (compressed_text, stats)."""
    lines = text.splitlines()
    matches = [parse_match(l) for l in lines]
    matches = [m for m in matches if m is not None]
    n = len(matches)
    if n == 0:
        return text, {"original_count": 0, "selected_count": 0, "kept": {}}

    selected: set[int] = set()
    kept: dict[str, list[int]] = {}

    # 1. Error matches
    err_idx = [i for i, m in enumerate(matches) if is_error_line(m["content"])]
    selected.update(err_idx)
    kept["errors"] = err_idx

    # 2. First N
    first_idx = list(range(min(keep_first, n)))
    selected.update(first_idx)
    kept["first"] = first_idx

    # 3. Last N
    last_idx = list(range(max(0, n - keep_last), n))
    selected.update(last_idx)
    kept["last"] = last_idx

    # 4. BM25 relevance over content
    scores = bm25_scores(query, [m["content"] for m in matches])
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    rel_idx = [i for i in ranked if scores[i] > 0][:relevance_top_k]
    selected.update(rel_idx)
    kept["relevant"] = rel_idx

    # 5. Per-file diversity: top per_file_diversity matches per file by score
    file_groups: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(matches):
        file_groups[m["path"]].append(i)
    div_idx: list[int] = []
    for path, idxs in file_groups.items():
        idxs.sort(key=lambda i: scores[i], reverse=True)
        div_idx.extend(idxs[:per_file_diversity])
    selected.update(div_idx)
    kept["file_diversity"] = div_idx

    # 6. Cap
    sorted_sel = sorted(selected)
    if len(sorted_sel) > max_items:
        # Priority: errors, first/last, top relevance
        priority: set[int] = set()
        priority.update(kept["errors"])
        priority.update(kept["first"])
        priority.update(kept["last"])
        priority.update(kept["relevant"][:relevance_top_k])
        # Sample the rest
        rest = [i for i in sorted_sel if i not in priority]
        keep_from_rest = max(0, max_items - len(priority))
        if rest and keep_from_rest > 0:
            step = max(1, len(rest) // keep_from_rest)
            sampled = rest[::step][:keep_from_rest]
            priority.update(sampled)
        sorted_sel = sorted(priority)

    # Deduplicate by raw line
    seen: set[str] = set()
    out_lines: list[str] = []
    for i in sorted_sel:
        if matches[i]["raw"] in seen:
            continue
        seen.add(matches[i]["raw"])
        out_lines.append(matches[i]["raw"])

    # Build output with elision markers
    out_idx = sorted_sel
    final: list[str] = []
    prev = -1
    for i in out_idx:
        if i > prev + 1:
            final.append(f"... [elided {i - prev - 1} matches] ...")
        final.append(matches[i]["raw"])
        prev = i
    if prev < n - 1:
        final.append(f"... [elided {n - 1 - prev} matches] ...")

    stats = {
        "original_count": n,
        "selected_count": len(out_lines),
        "kept": {k: len(v) for k, v in kept.items()},
        "files_represented": len({matches[i]["path"] for i in out_idx}),
    }
    return "\n".join(final), stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="SearchCompressor: compress grep/ripgrep output by relevance.",
    )
    ap.add_argument("file", nargs="?", help="Input search results file (default: stdin)")
    ap.add_argument("--query", required=True,
                    help="User's current question (for BM25 relevance).")
    ap.add_argument("--keep-first", type=int, default=3)
    ap.add_argument("--keep-last", type=int, default=2)
    ap.add_argument("--relevance-top-k", type=int, default=10)
    ap.add_argument("--max-items", type=int, default=50)
    ap.add_argument("--per-file-diversity", type=int, default=3,
                    help="Max matches to keep per file.")
    ap.add_argument("--ccr-cache-dir", default=".headroom-cache")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    out, stats = compress_search(
        raw,
        query=args.query,
        keep_first=args.keep_first,
        keep_last=args.keep_last,
        relevance_top_k=args.relevance_top_k,
        max_items=args.max_items,
        per_file_diversity=args.per_file_diversity,
    )

    if args.ccr_cache_dir:
        key = ccr_store(raw, args.ccr_cache_dir)
        out = f"[headroom-search ccr:{key} query={args.query!r}]\n{out}"

    sys.stdout.write(out)
    if not out.endswith("\n"):
        sys.stdout.write("\n")

    if args.stats:
        tb = estimate_tokens(raw)
        ta = estimate_tokens(out)
        sys.stderr.write(
            f"search_compressor: {stats['original_count']} -> {stats['selected_count']} matches "
            f"across {stats['files_represented']} files, "
            f"~{tb} -> ~{ta} tokens "
            f"({(1 - ta / max(1, tb)) * 100:.0f}% saved)\n"
            f"  kept: {stats['kept']}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
