from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")

TEST_PATH_TOKENS = {"test", "tests", "spec", "specs"}

STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "code",
    "current",
    "edit",
    "file",
    "fix",
    "for",
    "from",
    "function",
    "here",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "line",
    "local",
    "make",
    "module",
    "not",
    "of",
    "on",
    "or",
    "path",
    "please",
    "refactor",
    "remove",
    "same",
    "should",
    "similar",
    "so",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "use",
    "value",
    "warning",
    "src",
    "app",
    "blocks",
    "statement",
}

MIN_RETRIEVAL_SCORE = 4.0
STRONG_MATCH_SCORE = 10.0

DISPOSITION_LABELS = {
    "resolved": "resolved in code",
    "accepted": "kept as accepted debt",
    "persistent": "left open or deferred",
}

MAINTENANCE_LABELS = {
    "cleanup": "small refactors",
    "behavior": "behavior-sensitive changes",
    "supporting": "nearby follow-up changes",
}
