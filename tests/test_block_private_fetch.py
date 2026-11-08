import json
import subprocess
import sys
from pathlib import Path

import pytest

from hooks.block_private_fetch import is_blocked

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "block_private_fetch.py"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api", "http://localhost/", "http://192.168.1.10/", "http://10.0.0.1",
    "http://172.16.5.4/x", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://0.0.0.0/",
    "http://homeassistant.local:8123/", "file:///etc/passwd", "not a url",
])
def test_private_or_bad_targets_blocked(url):
    assert is_blocked(url, resolve=lambda host: ["127.0.0.1"] if host == "localhost" else [])


@pytest.mark.parametrize("url", [
    "http://evil.example\\@127.0.0.1/", "http://user@public.example/", "http://pub.example%2F@127.0.0.1/",
    "http://pub.example /x", "http://pub.example\t/x", "http://pub.example\\.127.0.0.1/",
    "http://127.1/", "http://2130706433/", "http://0x7f000001/",
])
def test_ambiguous_authorities_blocked(url):
    assert is_blocked(url, resolve=lambda host: ["93.184.216.34"])


def test_public_host_allowed():
    assert not is_blocked("https://www.nepremicnine.net/oglasi", resolve=lambda host: ["93.184.216.34"])


def test_host_resolving_to_private_blocked():
    assert is_blocked("https://evil.example/", resolve=lambda host: ["93.184.216.34", "192.168.0.5"])


def test_unresolvable_host_blocked():
    assert is_blocked("https://nx.example/", resolve=lambda host: [])


def _run(payload):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)


def test_hook_exit_2_blocks_with_reason():
    r = _run({"tool_name": "WebFetch", "tool_input": {"url": "http://127.0.0.1:8000/api/auth/me"}})
    assert r.returncode == 2 and "private" in r.stderr.lower()


def test_hook_ignores_other_tools():
    assert _run({"tool_name": "WebSearch", "tool_input": {"query": "x"}}).returncode == 0


def test_project_settings_register_hook():
    settings = json.loads((HOOK.parent.parent / ".claude" / "settings.json").read_text())
    hooks = settings["hooks"]["PreToolUse"]
    assert any(h["matcher"] == "WebFetch" and "block_private_fetch.py" in h["hooks"][0]["command"] for h in hooks)
