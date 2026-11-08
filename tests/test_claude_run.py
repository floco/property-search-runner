import json
import subprocess

import pytest

from propertysearch.agent import AgentError, UsageLimitError, run_claude




class FakePopen:
    instances = []

    def __init__(self, cmd, fake_rc=0, fake_out="", fake_err="", fake_exc=None, **kw):
        self.cmd, self.kw, self.returncode, self.pid = cmd, kw, fake_rc, 99
        self._out, self._err, self._exc = fake_out, fake_err, fake_exc
        self.inputs = []
        FakePopen.instances.append(self)

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if self._exc and len(self.inputs) == 1:
            raise self._exc
        return self._out, self._err

    def kill(self):
        pass


def fake(monkeypatch, rc=0, stdout="", stderr="", exc=None):
    calls = []

    def popen(cmd, **kw):
        proc = FakePopen(cmd, rc, stdout, stderr, exc, **kw)
        calls.append((cmd, proc))
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def stream(result_obj, searches=(), fetches=()):
    lines = [{"type": "system", "subtype": "init"}]
    for q in searches:
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": q}}]}})
    for u in fetches:
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "input": {"url": u, "prompt": "x"}}]}})
    if result_obj is not None:
        lines.append(dict(result_obj, type="result"))
    return "\n".join(json.dumps(l) for l in lines) + "\n"


def test_run_claude_collects_activity(monkeypatch):
    out = stream({"result": "[]", "is_error": False},
                 searches=["marketing jobs Brussels", "policy jobs Paris"],
                 fetches=["https://www.eurobrussels.com/job/1", "https://eurobrussels.com/job/2",
                          "https://jobs.welcometothejungle.com/x"])
    fake(monkeypatch, stdout=out)
    run = run_claude("hello", claude_bin="claude")
    assert run.result == "[]"
    assert run.searches == ["marketing jobs Brussels", "policy jobs Paris"]
    assert run.pages == ["https://www.eurobrussels.com/job/1", "https://eurobrussels.com/job/2",
                         "https://jobs.welcometothejungle.com/x"]


def test_run_claude_uses_stream_json(monkeypatch):
    calls = fake(monkeypatch, stdout=stream({"result": "[]", "is_error": False}))
    run_claude("hello", claude_bin="claude")
    cmd, _ = calls[0]
    assert cmd[cmd.index("--output-format") + 1] == "stream-json" and "--verbose" in cmd


def test_run_claude_returns_result(monkeypatch):
    calls = fake(monkeypatch, stdout=stream({"result": "[]", "is_error": False}))
    assert run_claude("hello", claude_bin="claude").result == "[]"
    cmd, proc = calls[0]
    assert "-p" in cmd and "--allowedTools" in cmd and "WebSearch" in cmd and "WebFetch" in cmd
    assert not any("Bash" in c for c in cmd)
    assert proc.inputs[0] == "hello"


def test_run_claude_usage_limit(monkeypatch):
    fake(monkeypatch, rc=1, stdout=stream({"result": "Claude usage limit reached", "is_error": True}))
    with pytest.raises(UsageLimitError):
        run_claude("hello", claude_bin="claude")


def test_run_claude_other_error(monkeypatch):
    fake(monkeypatch, rc=1, stdout="", stderr="not logged in")
    with pytest.raises(AgentError) as e:
        run_claude("hello", claude_bin="claude")
    assert not isinstance(e.value, UsageLimitError)
    assert "not logged in" in str(e.value)


def test_run_claude_timeout(monkeypatch):
    fake(monkeypatch, exc=subprocess.TimeoutExpired("claude", 5))
    with pytest.raises(AgentError, match="timed out"):
        run_claude("hello", timeout_s=5, claude_bin="claude")


def test_run_claude_no_web_search_raises(monkeypatch):
    out = {"result": "[]", "is_error": False, "usage": {"server_tool_use": {"web_search_requests": 0}}}
    fake(monkeypatch, stdout=stream(out))
    with pytest.raises(AgentError, match="no web searches"):
        run_claude("hello", claude_bin="claude")


def test_run_claude_with_web_searches_ok(monkeypatch):
    out = {"result": "[]", "is_error": False, "usage": {"server_tool_use": {"web_search_requests": 7}}}
    fake(monkeypatch, stdout=stream(out))
    assert run_claude("hello", claude_bin="claude").result == "[]"


def test_run_claude_counts_searches_in_model_usage(monkeypatch):
    out = {"result": "[]", "is_error": False,
           "usage": {"server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}},
           "modelUsage": {"main-model": {"webSearchRequests": 0}, "helper-model": {"webSearchRequests": 3}}}
    fake(monkeypatch, stdout=stream(out))
    assert run_claude("hello", claude_bin="claude").result == "[]"


def test_run_claude_zero_searches_everywhere_raises(monkeypatch):
    out = {"result": "[]", "is_error": False,
           "usage": {"server_tool_use": {"web_search_requests": 0}},
           "modelUsage": {"main-model": {"webSearchRequests": 0}, "helper-model": {"webSearchRequests": 0}}}
    fake(monkeypatch, stdout=stream(out))
    with pytest.raises(AgentError, match="no web searches"):
        run_claude("hello", claude_bin="claude")


def test_run_claude_isolated_from_user_settings(monkeypatch):
    calls = fake(monkeypatch, stdout=stream({"result": "[]", "is_error": False}))
    run_claude("hello", claude_bin="claude")
    cmd, proc = calls[0]
    assert cmd[cmd.index("--setting-sources") + 1] == "project"
    assert proc.kw.get("start_new_session") is True


@pytest.mark.parametrize("msg", ["You've hit your limit · resets 10am", "Claude AI usage limit reached|1700000000",
                                 "You're out of extra usage · resets 3pm"])
def test_run_claude_usage_limit_wordings(monkeypatch, msg):
    fake(monkeypatch, rc=1, stdout=stream({"result": msg, "is_error": True}))
    with pytest.raises(UsageLimitError):
        run_claude("hello", claude_bin="claude")


def test_run_claude_limit_text_without_error_flag(monkeypatch):
    fake(monkeypatch, stdout=stream({"result": "You've hit your limit · resets 10am", "is_error": False}))
    with pytest.raises(UsageLimitError):
        run_claude("hello", claude_bin="claude")


def test_run_claude_timeout_kills_process_group(monkeypatch):
    killed = []
    monkeypatch.setattr("os.killpg", lambda pgid, sig: killed.append(pgid))
    monkeypatch.setattr("os.getpgid", lambda pid: 4242)
    calls = fake(monkeypatch, exc=subprocess.TimeoutExpired("claude", 5))
    with pytest.raises(AgentError, match="timed out"):
        run_claude("hello", timeout_s=5, claude_bin="claude")
    assert killed == [4242]


def test_run_claude_stream_without_result_line_is_error(monkeypatch):
    fake(monkeypatch, rc=1, stdout=stream(None, searches=["q"]), stderr="crashed")
    with pytest.raises(AgentError, match="crashed"):
        run_claude("hello", claude_bin="claude")


def test_run_claude_collects_usage(monkeypatch):
    rl = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
        "five_hour": {"utilization": 0.34}, "seven_day": {"utilization": 0.08}}}}
    rl2 = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
        "five_hour": {"utilization": 0.41}, "seven_day": {"utilization": 0.09}}}}
    final = {"result": "[]", "is_error": False, "modelUsage": {
        "claude-opus-5-5": {"inputTokens": 6, "outputTokens": 734, "cacheReadInputTokens": 11910,
                            "cacheCreationInputTokens": 4315, "webSearchRequests": 0},
        "claude-haiku-5-5": {"inputTokens": 12430, "outputTokens": 728, "cacheReadInputTokens": 0,
                             "cacheCreationInputTokens": 0, "webSearchRequests": 2}}}
    out = json.dumps(rl) + "\n" + stream(final, searches=["q"]).replace(
        '{"type": "system"', json.dumps(rl2) + '\n{"type": "system"', 1)
    fake(monkeypatch, stdout=out)
    run = run_claude("hello", claude_bin="claude")
    assert run.usage.weekly_pct == 9 and run.usage.five_hour_pct == 41
    assert run.usage.tokens_by_model == {"claude-opus-5-5": 16965, "claude-haiku-5-5": 13158}
    assert run.usage.total_tokens == 30123


def test_run_claude_usage_missing_is_none(monkeypatch):
    fake(monkeypatch, stdout=stream({"result": "[]", "is_error": False}, searches=["q"]))
    run = run_claude("hello", claude_bin="claude")
    assert run.usage.weekly_pct is None and run.usage.total_tokens == 0


def test_run_claude_runs_in_project_dir_so_hooks_load(monkeypatch):
    from pathlib import Path
    calls = fake(monkeypatch, stdout=stream({"result": "[]", "is_error": False}, searches=["q"]))
    run_claude("hello", claude_bin="claude")
    assert calls[0][1].kw["cwd"] == str(Path(__file__).resolve().parent.parent)
