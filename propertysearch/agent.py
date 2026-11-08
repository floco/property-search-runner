"""Run headless Claude Code (Pro/Max subscription login) and collect what it did.

Ported unchanged from floco/jobsearch: stream parsing, usage, limit detection, timeouts."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import urlsplit


CLAUDE_BIN = "/root/.local/bin/claude"
PROJECT_DIR = Path(__file__).resolve().parent.parent
LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "hit your limit", "out of extra usage",
                 "out of usage")


class AgentError(Exception):
    pass


class UsageLimitError(AgentError):
    pass


@dataclass
class RunUsage:
    """Tokens used by this run (all models, cache included) and plan usage as reported by Claude Code."""
    tokens_by_model: dict[str, int] = field(default_factory=dict)
    weekly_pct: int | None = None
    five_hour_pct: int | None = None

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens_by_model.values())

    def to_dict(self) -> dict:
        return {"tokens_by_model": self.tokens_by_model, "total_tokens": self.total_tokens,
                "weekly_pct": self.weekly_pct, "five_hour_pct": self.five_hour_pct}


@dataclass
class ClaudeRun:
    """Claude's final answer plus what it actually did: the searches it ran and the pages it opened."""
    result: str
    searches: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)


_TOKEN_FIELDS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")


def _pct(window: dict | None) -> int | None:
    value = (window or {}).get("utilization")
    return round(float(value) * 100) if isinstance(value, (int, float)) else None


def _usage(final: dict | None, rate_limit: dict | None) -> RunUsage:
    tokens = {}
    for model, stats in ((final or {}).get("modelUsage") or {}).items():
        if isinstance(stats, dict):
            tokens[model] = sum(int(stats.get(f) or 0) for f in _TOKEN_FIELDS)
    windows = (rate_limit or {}).get("unifiedWindows") or {}
    return RunUsage(tokens_by_model=tokens, weekly_pct=_pct(windows.get("seven_day")),
                    five_hour_pct=_pct(windows.get("five_hour")))


def _read_stream(stdout: str) -> tuple[dict | None, list[str], list[str], dict | None]:
    final, searches, pages, rate_limit = None, [], [], None
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            final = event
        elif event.get("type") == "rate_limit_event":
            rate_limit = event.get("rate_limit_info") or rate_limit  # keep the latest snapshot
        elif event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                args = block.get("input") or {}
                if block.get("name") == "WebSearch" and args.get("query"):
                    searches.append(str(args["query"]))
                elif block.get("name") == "WebFetch" and args.get("url"):
                    pages.append(str(args["url"]))
    return final, searches, pages, rate_limit


def run_claude(prompt: str, timeout_s: int = 1500, claude_bin: str = CLAUDE_BIN) -> ClaudeRun:
    cmd = [claude_bin, "-p", "--output-format", "stream-json", "--verbose",
           "--setting-sources", "project",
           "--tools", "WebSearch", "WebFetch",
           "--allowedTools", "WebSearch", "WebFetch",
           "--strict-mcp-config", "--no-session-persistence"]
    # Own process group, so a timeout kills Claude and anything it spawned (no orphan holding the pipes open).
    # cwd = repo root so "--setting-sources project" loads .claude/settings.json, whose PreToolUse
    # hook blocks WebFetch to private/local addresses (listing pages are untrusted input).
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True, cwd=str(PROJECT_DIR))
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        raise AgentError(f"Claude timed out after {timeout_s} s")
    data, searches, pages, rate_limit = _read_stream(stdout)
    is_error = proc.returncode != 0 or data is None or bool(data.get("is_error"))
    if not is_error:
        result = str(data.get("result", ""))
        if "[" not in result and any(m in result.lower() for m in LIMIT_MARKERS):
            raise UsageLimitError(f"Claude usage limit: {result[:300]}")
        if not searches and _web_searches(data) == 0:
            raise AgentError("Claude made no web searches (search tool unavailable?): "
                             f"{result[:300]}")
        return ClaudeRun(result=result, searches=searches, pages=pages, usage=_usage(data, rate_limit))
    tail = (stdout or "").strip().splitlines()[-1:] if data is None else []
    detail = " ".join(filter(None, [
        str(data.get("result", "")) if data else " ".join(tail),
        stderr])).strip()[:1000]
    if any(m in detail.lower() for m in LIMIT_MARKERS):
        raise UsageLimitError(f"Claude usage limit: {detail}")
    raise AgentError(f"Claude failed (exit {proc.returncode}): {detail or 'no output'}")


def _web_searches(data: dict) -> int | None:
    """Total web searches across all models (Claude Code runs searches via a helper model).
    None when the output carries no counters at all, so an unknown format never blocks a run."""
    counts = []
    stu = (data.get("usage") or {}).get("server_tool_use") or {}
    if "web_search_requests" in stu:
        counts.append(stu["web_search_requests"] or 0)
    for model in (data.get("modelUsage") or {}).values():
        if isinstance(model, dict) and "webSearchRequests" in model:
            counts.append(model["webSearchRequests"] or 0)
    return sum(counts) if counts else None
