"""
_common.py — shared helpers for the headroom-skill scripts.

Pure Python 3 stdlib. No external dependencies.

Provides:
- estimate_tokens(text) -> int       Rough token estimate (chars / 4).
- bm25_scores(query, docs) -> list   BM25 similarity scores.
- entropy(s) -> float                Shannon entropy of a string.
- is_high_entropy(s, threshold=0.85) -> bool
- is_error_line(line) -> bool        Heuristic error detector.
- is_error_item(obj) -> bool         Heuristic error detector for JSON items.
- sha256_short(text) -> str          First 12 hex chars of sha256(text).
- ccr_store(text, cache_dir) -> str  Write original to .headroom-cache/<sha>.txt.

These helpers are independent re-implementations of helpers used by the
upstream Headroom project (https://github.com/chopratejas/headroom). They are
simpler and less accurate but capture the same intent.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from typing import Iterable, List, Sequence


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# BM25 scoring (minimal, stdlib only)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """Simple whitespace/punctuation tokenizer, lowercased."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def bm25_scores(
    query: str,
    docs: Sequence[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> List[float]:
    """Return BM25 scores of each doc against the query.

    Pure stdlib. Documents are tokenized with a simple regex tokenizer.
    """
    q_terms = tokenize(query)
    if not q_terms or not docs:
        return [0.0] * len(docs)

    doc_tokens = [tokenize(d) for d in docs]
    doc_lens = [len(t) for t in doc_tokens]
    avgdl = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
    if avgdl == 0:
        avgdl = 1.0

    # Document frequency per term
    df = Counter()
    for toks in doc_tokens:
        for term in set(toks):
            df[term] += 1
    N = len(docs)

    scores: List[float] = []
    for toks, dl in zip(doc_tokens, doc_lens):
        tf = Counter(toks)
        s = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (N - df[term] + 0.5) / (df[term] + 0.5))
            numerator = tf[term] * (k1 + 1)
            denominator = tf[term] + k1 * (1 - b + b * dl / avgdl)
            s += idf * numerator / denominator
        scores.append(s)
    return scores


# ---------------------------------------------------------------------------
# Entropy
# ---------------------------------------------------------------------------

def entropy(s: str) -> float:
    """Shannon entropy (bits/char) of a string."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def is_high_entropy(s: str, threshold: float = 0.85) -> bool:
    """True if the string looks like an opaque identifier (UUID, hash, etc.).

    Normalized entropy: entropy(s) / log2(len(alphabet)). For ASCII strings
    we use 6.0 (log2 of ~64 printable chars) as the denominator.
    """
    if not s or len(s) < 8:
        return False
    return entropy(s) / 6.0 >= threshold


# ---------------------------------------------------------------------------
# Error detection
# ---------------------------------------------------------------------------

_ERROR_KEYWORDS = (
    "error",
    "failed",
    "failure",
    "exception",
    "traceback",
    "fatal",
    "panic",
    "segfault",
    "abort",
    "crash",
    "denied",
    "refused",
    "timeout",
    "undefined",
    "nullreference",
    "outofrange",
    "overflow",
    "deadlock",
)

_ERROR_RE = re.compile(
    r"\b(" + "|".join(_ERROR_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_error_line(line: str) -> bool:
    """Heuristic: does this log line look like an error?"""
    if not line:
        return False
    if _ERROR_RE.search(line):
        return True
    # Status codes / exit codes
    if re.search(r"\b[45]\d\d\b", line):  # 4xx/5xx HTTP
        return True
    if re.search(r"\[ERR\b|\bERR\]|✗|×", line):
        return True
    return False


def is_error_item(obj) -> bool:
    """Heuristic: does this JSON item look like it represents an error?

    Looks for keys like 'error', 'status', 'level', 'is_error', 'success'
    with values that suggest failure.
    """
    if not isinstance(obj, dict):
        return False
    for k, v in obj.items():
        kl = k.lower()
        if kl in ("is_error", "isError") and v:
            return True
        if kl == "level" and isinstance(v, str) and v.lower() in (
            "error", "fatal", "critical", "alert", "emergency",
        ):
            return True
        if kl == "status":
            if isinstance(v, str) and re.match(r"^[45]\d\d", v):
                return True
            if isinstance(v, int) and 400 <= v < 600:
                return True
        if kl == "success" and v is False:
            return True
        if kl == "ok" and v is False:
            return True
        if kl == "error" and v:
            return True
        if kl == "errors" and isinstance(v, (list, dict)) and v:
            return True
        if isinstance(v, str) and is_error_line(v):
            return True
    return False


# ---------------------------------------------------------------------------
# SHA / CCR cache
# ---------------------------------------------------------------------------

def sha256_short(text: str, length: int = 12) -> str:
    """First `length` hex chars of sha256(text)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def ccr_store(text: str, cache_dir: str = ".headroom-cache") -> str:
    """Write the original text to <cache_dir>/<sha>.txt and return the key.

    The key is the first 12 hex chars of sha256(text). Callers should cite
    this key in their narration so later turns can retrieve the original:
        CCR key: a3f9c1b2d4e6
    """
    os.makedirs(cache_dir, exist_ok=True)
    key = sha256_short(text)
    path = os.path.join(cache_dir, f"{key}.txt")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return key


def ccr_retrieve(key: str, cache_dir: str = ".headroom-cache") -> str | None:
    """Retrieve an original from the CCR cache. Returns None if missing."""
    if not re.fullmatch(r"[0-9a-f]{4,64}", key):
        return None
    path = os.path.join(cache_dir, f"{key}.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def truncate(s: str, n: int, ellipsis: str = "…") -> str:
    """Truncate to n chars, with ellipsis if cut."""
    if len(s) <= n:
        return s
    return s[: max(0, n - len(ellipsis))] + ellipsis


def mean_std(values: Iterable[float]) -> tuple[float, float]:
    """Return (mean, std) of a sequence. Empty -> (0, 0)."""
    xs = list(values)
    if not xs:
        return 0.0, 0.0
    mu = sum(xs) / len(xs)
    if len(xs) < 2:
        return mu, 0.0
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return mu, math.sqrt(var)
