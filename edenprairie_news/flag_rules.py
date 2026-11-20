"""Pluggable "does this post need mod attention" detectors.

Each rule takes a post dict (the shape returned by
reddit_client._summarize_submission / stored in storage.subreddit_posts)
and returns a short flag string, or None if it doesn't apply. Add a new
rule by writing a function with that signature and appending it to RULES --
compute_flags() and its caller don't need to change.

Deliberately starts small: two obvious rules to prove the pattern. This is
the place to grow more nuanced moderation heuristics later (e.g. reported
comment threads, likely duplicates, keyword watchlists) without touching
subreddit_sync.py or the web UI.
"""

from collections.abc import Callable

Rule = Callable[[dict], str | None]


def rule_no_flair(post: dict) -> str | None:
    return "no_flair" if not post.get("flair") else None


def rule_reported(post: dict) -> str | None:
    return "reported" if post.get("num_reports", 0) > 0 else None


RULES: list[Rule] = [rule_no_flair, rule_reported]


def compute_flags(post: dict) -> list[str]:
    return [flag for rule in RULES if (flag := rule(post)) is not None]
