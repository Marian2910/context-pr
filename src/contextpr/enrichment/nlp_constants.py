from __future__ import annotations

import re

MIN_HISTORY_SAMPLE_SIZE = 5
MIN_HISTORY_SHARE = 0.5
MIN_STRONG_HISTORY_MATCHES = 2
HOTSPOT_FILE_MATCHES = 2
HOTSPOT_MODULE_MATCHES = 3
HOTSPOT_MODULE_SHARE = 0.5

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")

STOP_TOKENS = {
    "a",
    "all",
    "and",
    "as",
    "be",
    "code",
    "edit",
    "function",
    "if",
    "in",
    "is",
    "it",
    "not",
    "of",
    "or",
    "remove",
    "so",
    "statement",
    "that",
    "the",
    "their",
    "this",
    "to",
    "use",
}

AMBIGUITY_MARKERS = {
    "branch",
    "condition",
    "lambda",
    "logic",
    "semantic",
    "behavior",
    "state",
    "outcome",
    "capture",
}

SELF_EXPLANATORY_RULES = {
    "python:S1172",
    "python:S1481",
    "python:S1192",
    "python:S1186",
}

BEHAVIOR_RULES = {
    "python:S1515",
}
