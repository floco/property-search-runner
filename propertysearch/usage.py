"""Map Claude Code's run usage to myhome's provider-neutral SearchUsage shape."""
from __future__ import annotations

from .agent import RunUsage

PROVIDER = "claude-code"


def to_search_usage(u: RunUsage) -> dict:
    return {
        "provider": PROVIDER,
        "tokensByModel": dict(u.tokens_by_model),
        "totalTokens": u.total_tokens,
        "quotas": [{"label": "Weekly", "usedPct": u.weekly_pct}, {"label": "5-hour", "usedPct": u.five_hour_pct}],
    }
