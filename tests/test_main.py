import httpx
import pytest

from propertysearch import main as m
from propertysearch.agent import AgentError, ClaudeRun, RunUsage, UsageLimitError
from propertysearch.api import MyHome, MyHomeError
from propertysearch.usage import to_search_usage


def test_to_search_usage_maps_windows():
    u = RunUsage(tokens_by_model={"claude-a": 1000, "claude-b": 500}, weekly_pct=34, five_hour_pct=None)
    assert to_search_usage(u) == {
        "provider": "claude-code", "tokensByModel": {"claude-a": 1000, "claude-b": 500}, "totalTokens": 1500,
        "quotas": [{"label": "Weekly", "usedPct": 34}, {"label": "5-hour", "usedPct": None}],
    }


class FakeHome:
    def __init__(self, claims):
        self.claims = list(claims)
        self.completed, self.failed = [], []

    def claim(self):
        return self.claims.pop(0) if self.claims else None

    def complete(self, run_id, payload):
        self.completed.append((run_id, payload))
        return {"received": len(payload["listings"]), "new": len(payload["listings"]), "duplicates": 0}

    def fail(self, run_id, reason, message, usage=None):
        self.failed.append((run_id, reason, message))


def claim(run_id="r1"):
    return {"runId": run_id, "homeId": "h", "searchId": "s", "name": "Plots", "prompt": "land",
            "maxResultsPerRun": 5, "maxListingAgeDays": 7, "today": "2026-11-08", "seen": []}


GOOD = ('{"listings": [{"title": "Plot", "listingUrl": "https://a.si/1", "reason": "fits"}],'
        ' "sitesQueried": ["https://www.a.si/search"]}')


def fake_claude(result=GOOD, exc=None):
    def run(prompt, timeout_s, claude_bin):
        if exc:
            raise exc
        return ClaudeRun(result=result, searches=["q1"], pages=["https://b.si/x", "https://a.si/1"],
                         usage=RunUsage(tokens_by_model={"m": 10}, weekly_pct=5, five_hour_pct=1))
    return run


def test_main_loop_completes_then_stops_on_204():
    home = FakeHome([claim("r1"), claim("r2")])
    n = m.run_all(home, fake_claude(), template="{criteria}", timeout_s=10, claude_bin="c")
    assert n == 2 and [c[0] for c in home.completed] == ["r1", "r2"]
    payload = home.completed[0][1]
    assert payload["listings"][0]["listingUrl"] == "https://a.si/1"
    assert payload["searchQueries"] == ["q1"]
    assert set(payload["sitesQueried"]) == {"https://www.a.si/search", "b.si", "a.si"}
    assert payload["usage"]["quotas"][0] == {"label": "Weekly", "usedPct": 5}


def test_main_usage_limit_reports_and_stops():
    home = FakeHome([claim("r1"), claim("r2")])
    m.run_all(home, fake_claude(exc=UsageLimitError("limit")), template="{criteria}", timeout_s=10, claude_bin="c")
    assert home.failed == [("r1", "usage_limit", "limit")]
    assert len(home.claims) == 1  # stopped, r2 left for later


def test_main_error_reports_and_continues():
    home = FakeHome([claim("r1"), claim("r2")])
    m.run_all(home, fake_claude(result="no json here"), template="{criteria}", timeout_s=10, claude_bin="c")
    assert [f[:2] for f in home.failed] == [("r1", "error"), ("r2", "error")]


def test_main_agent_error_reports(monkeypatch):
    home = FakeHome([claim("r1")])
    m.run_all(home, fake_claude(exc=AgentError("Claude timed out")), template="{criteria}", timeout_s=10, claude_bin="c")
    assert home.failed == [("r1", "error", "Claude timed out")]


def _client(handler):
    return MyHome("http://myhome:8000/", "tok", transport=httpx.MockTransport(handler))


def test_api_claim_204_is_none_and_sends_bearer():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        return httpx.Response(204)
    assert _client(handler).claim() is None
    assert seen == {"auth": "Bearer tok", "url": "http://myhome:8000/api/property-search/runner/claim"}


def test_api_claim_returns_json():
    assert _client(lambda req: httpx.Response(200, json=claim())).claim()["runId"] == "r1"


def test_api_error_raises():
    with pytest.raises(MyHomeError, match="403"):
        _client(lambda req: httpx.Response(403, json={"detail": "Insufficient permissions"})).claim()


def test_api_fail_posts_reason():
    bodies = []

    def handler(req):
        import json
        bodies.append((req.url.path, json.loads(req.content)))
        return httpx.Response(204)
    _client(handler).fail("r1", "usage_limit", "limit", None)
    assert bodies == [("/api/property-search/runner/runs/r1/fail", {"reason": "usage_limit", "message": "limit", "usage": None})]
