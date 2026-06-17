#!/usr/bin/env python3
"""
smart_crusher.py — portable re-implementation of Headroom's SmartCrusher.

Compresses a JSON array (or array-of-dicts inside a JSON object) by selecting
the most informative items:

  1. All items flagged as errors (is_error, status >= 400, level=error, ...).
  2. First N items (default 3) — pagination / setup context.
  3. Last N items (default 2) — recency.
  4. Anomalies — numeric values >2σ from the mean.
  5. Top-K items by BM25 similarity to the user's query.
  6. Change points — items where a field value transitions.
  7. Sample of the remainder, up to a cap.

Originals are written to .headroom-cache/<sha>.txt (CCR convention).

Usage:
    python smart_crusher.py results.json \\
        --query "user signup error" \\
        --keep-first 3 --keep-last 2 \\
        --max-items 50

Reads from stdin if no file is given. Writes compressed JSON to stdout.

Credits: independent re-implementation of the SmartCrusher transform from
https://github.com/chopratejas/headroom (Apache 2.0).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, List, Sequence

# Allow `python scripts/smart_crusher.py` from the repo root.
sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
try:
    from _common import (  # type: ignore
        bm25_scores,
        ccr_store,
        estimate_tokens,
        is_error_item,
        is_high_entropy,
        mean_std,
    )
except ImportError:
    # Fallback for when run as a standalone file.
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import (  # type: ignore
        bm25_scores,
        ccr_store,
        estimate_tokens,
        is_error_item,
        is_high_entropy,
        mean_std,
    )


def _flatten_to_items(doc: Any) -> tuple[Any, list[Any], str]:
    """Find the largest array inside `doc` and return (parent, items, key).

    Returns (None, [], '') if no array is found.
    """
    if isinstance(doc, list):
        return doc, doc, "<root>"
    if isinstance(doc, dict):
        # Find the longest list value
        best_key = None
        best_len = 0
        for k, v in doc.items():
            if isinstance(v, list) and len(v) > best_len:
                best_key = k
                best_len = len(v)
        if best_key is not None:
            return doc, doc[best_key], best_key
    return None, [], ""


def _numeric_values(item: Any) -> list[float]:
    """Extract all numeric values from an item (dict or scalar)."""
    out: list[float] = []
    if isinstance(item, dict):
        for v in item.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
    elif isinstance(item, (int, float)) and not isinstance(item, bool):
        out.append(float(item))
    return out


def _is_anomaly(item: Any, mu: float, sigma: float, threshold: float = 2.0) -> bool:
    """True if any numeric value in `item` is >threshold standard deviations
    from the mean."""
    if sigma == 0:
        return False
    for v in _numeric_values(item):
        z = abs(v - mu) / sigma
        if z > threshold:
            return True
    return False


def _change_points(items: Sequence[Any]) -> set[int]:
    """Indices of items where a string/enum field transitions from the
    previous item's value."""
    if not items or not isinstance(items[0], dict):
        return set()
    indices: set[int] = set()
    # Track a few key fields if present
    keys_to_watch = ("status", "level", "state", "phase", "stage", "event")
    prev: dict[str, Any] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for k in keys_to_watch:
            if k in item:
                cur = item[k]
                if k in prev and prev[k] != cur:
                    indices.add(i)
                prev[k] = cur
    return indices


def crush(
    items: Sequence[Any],
    query: str = "",
    keep_first: int = 3,
    keep_last: int = 2,
    max_items: int = 50,
    relevance_top_k: int = 5,
    anomaly_sigma: float = 2.0,
) -> tuple[list[Any], dict]:
    """Select the most informative items from a JSON array.

    Returns (selected_items, stats_dict).
    """
    if not items:
        return [], {"original_count": 0, "selected_count": 0, "kept": {}}

    n = len(items)
    selected_indices: set[int] = set()
    kept: dict[str, list[int]] = {}

    # 1. Errors (always)
    err_idx = [i for i, it in enumerate(items) if is_error_item(it)]
    selected_indices.update(err_idx)
    kept["errors"] = err_idx

    # 2. First N
    first_idx = list(range(min(keep_first, n)))
    selected_indices.update(first_idx)
    kept["first"] = first_idx

    # 3. Last N
    last_idx = list(range(max(0, n - keep_last), n))
    selected_indices.update(last_idx)
    kept["last"] = last_idx

    # 4. Anomalies (numeric only)
    all_nums: list[float] = []
    for it in items:
        all_nums.extend(_numeric_values(it))
    if all_nums:
        mu, sigma = mean_std(all_nums)
        if sigma > 0:
            anom_idx = [
                i
                for i, it in enumerate(items)
                if _is_anomaly(it, mu, sigma, anomaly_sigma)
            ]
            selected_indices.update(anom_idx)
            kept["anomalies"] = anom_idx

    # 5. BM25 relevance
    if query:
        doc_texts = [json.dumps(it, sort_keys=True, default=str) for it in items]
        scores = bm25_scores(query, doc_texts)
        ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
        rel_idx = [i for i in ranked if scores[i] > 0][:relevance_top_k]
        selected_indices.update(rel_idx)
        kept["relevant"] = rel_idx

    # 6. Change points
    cp_idx = _change_points(items)
    selected_indices.update(cp_idx)
    kept["change_points"] = sorted(cp_idx)

    # 7. Cap: if we're over max_items, drop the lowest-priority (sample).
    sorted_sel = sorted(selected_indices)
    if len(sorted_sel) > max_items:
        # Keep all errors, first N, last N, top relevance, then sample rest
        priority: set[int] = set()
        priority.update(kept.get("errors", []))
        priority.update(kept.get("first", []))
        priority.update(kept.get("last", []))
        priority.update(kept.get("relevant", [])[:relevance_top_k])
        # Sample the rest to fill up to max_items
        rest = [i for i in sorted_sel if i not in priority]
        # Even sampling
        keep_from_rest = max(0, max_items - len(priority))
        if rest and keep_from_rest > 0:
            step = max(1, len(rest) // keep_from_rest)
            sampled = rest[::step][:keep_from_rest]
            priority.update(sampled)
        sorted_sel = sorted(priority)
        kept["sampled"] = [i for i in sampled] if "sampled" in dir() else []

    # Deduplicate identical items
    seen_hashes: set[str] = set()
    deduped: list[Any] = []
    for i in sorted_sel:
        h = json.dumps(items[i], sort_keys=True, default=str)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        deduped.append(items[i])

    stats = {
        "original_count": n,
        "selected_count": len(deduped),
        "kept": {k: len(v) for k, v in kept.items()},
    }
    return deduped, stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="SmartCrusher: compress a JSON array by selecting the most informative items.",
    )
    ap.add_argument("file", nargs="?", help="Input JSON file (default: stdin)")
    ap.add_argument("--query", default="", help="User's current question (for BM25 relevance)")
    ap.add_argument("--keep-first", type=int, default=3)
    ap.add_argument("--keep-last", type=int, default=2)
    ap.add_argument("--max-items", type=int, default=50)
    ap.add_argument("--relevance-top-k", type=int, default=5)
    ap.add_argument("--anomaly-sigma", type=float, default=2.0)
    ap.add_argument(
        "--ccr-cache-dir",
        default=".headroom-cache",
        help="Directory to write original (CCR cache). Empty disables.",
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help="Print compression stats to stderr.",
    )
    args = ap.parse_args()

    raw = sys.stdin.read() if not args.file else open(args.file, "r", encoding="utf-8").read()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"smart_crusher: input is not valid JSON ({e}); passing through.\n")
        sys.stdout.write(raw)
        return 0

    parent, items, array_key = _flatten_to_items(doc)
    if not items:
        # No array found; pass through unchanged
        sys.stdout.write(json.dumps(doc, indent=2, default=str))
        return 0

    selected, stats = crush(
        items,
        query=args.query,
        keep_first=args.keep_first,
        keep_last=args.keep_last,
        max_items=args.max_items,
        relevance_top_k=args.relevance_top_k,
        anomaly_sigma=args.anomaly_sigma,
    )

    # Reassemble: if root was a list, replace; if it was a dict, replace the
    # array value at `array_key` and add a `_headroom` summary block.
    tokens_before = estimate_tokens(raw)
    if isinstance(parent, list):
        out_doc: Any = selected
    else:
        out_doc = dict(parent)
        out_doc[array_key] = selected
        out_doc["_headroom"] = {
            "compressed": True,
            "original_count": stats["original_count"],
            "selected_count": stats["selected_count"],
            "kept": stats["kept"],
            "ccr_key": ccr_store(raw, args.ccr_cache_dir) if args.ccr_cache_dir else None,
            "query": args.query or None,
        }
    out_str = json.dumps(out_doc, indent=2, default=str)
    tokens_after = estimate_tokens(out_str)

    sys.stdout.write(out_str)
    if args.stats:
        sys.stderr.write(
            f"smart_crusher: {stats['original_count']} -> {stats['selected_count']} items, "
            f"~{tokens_before} -> ~{tokens_after} tokens "
            f"({(1 - tokens_after / max(1, tokens_before)) * 100:.0f}% saved)\n"
            f"  kept: {stats['kept']}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
