"""Entry point: drain every due property search from myhome, one at a time.

    python3 -m propertysearch.main            # claim → run Claude → report, until nothing is due
    python3 -m propertysearch.main --check    # verify MYHOME_URL / MYHOME_TOKEN
    python3 -m propertysearch.main --dry-run "plots near Novo Mesto under 200k EUR"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .agent import AgentError, UsageLimitError, run_claude
from .api import MyHome, MyHomeError
from .config import ROOT, ConfigError, load_config
from .prompt import build_prompt, parse_listings
from .usage import to_search_usage

TEMPLATE_PATH = ROOT / "agent_prompt.md"


def log(msg: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def _sites(parsed_sites: list[str], pages: list[str]) -> list[str]:
    hosts = []
    for url in pages:
        host = urlsplit(url).netloc.lower()
        if host and host not in hosts:
            hosts.append(host)
    out = list(dict.fromkeys(parsed_sites))
    return out + [h for h in hosts if h not in out]


def run_one(home, claim: dict, claude: Callable, template: str, timeout_s: int, claude_bin: str) -> None:
    """Run one claimed search. Raises UsageLimitError (after reporting) so the caller can stop."""
    run_id = claim["runId"]
    log(f"run {run_id}: search '{claim['name']}'")
    try:
        result = claude(build_prompt(template, claim), timeout_s=timeout_s, claude_bin=claude_bin)
    except UsageLimitError as e:
        log(f"run {run_id}: usage limit — {e}")
        home.fail(run_id, "usage_limit", str(e))
        raise
    except AgentError as e:
        log(f"run {run_id}: error — {e}")
        home.fail(run_id, "error", str(e))
        return
    usage = to_search_usage(result.usage)
    try:
        listings, sites = parse_listings(result.result)
    except AgentError as e:
        log(f"run {run_id}: unparseable answer — {e}")
        home.fail(run_id, "error", str(e), usage)
        return
    counts = home.complete(run_id, {
        "listings": listings, "sitesQueried": _sites(sites, result.pages),
        "searchQueries": result.searches, "usage": usage,
    })
    log(f"run {run_id}: {counts} · tokens {usage['totalTokens']} · quotas {usage['quotas']}")


def run_all(home, claude: Callable = run_claude, *, template: str, timeout_s: int, claude_bin: str) -> int:
    """Claim and run searches until none is due or the plan's usage limit is hit. Returns runs done."""
    done = 0
    while True:
        claim = home.claim()
        if claim is None:
            return done
        try:
            run_one(home, claim, claude, template, timeout_s, claude_bin)
        except UsageLimitError:
            return done + 1
        done += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="propertysearch")
    parser.add_argument("--check", action="store_true", help="verify the connection to myhome")
    parser.add_argument("--dry-run", metavar="PROMPT", help="run one search locally and print the JSON")
    args = parser.parse_args(argv)
    template = TEMPLATE_PATH.read_text()

    if args.dry_run:
        claim = {"prompt": args.dry_run, "today": date.today().isoformat(), "maxResultsPerRun": 5,
                 "maxListingAgeDays": 14, "seen": []}
        result = run_claude(build_prompt(template, claim))
        listings, sites = parse_listings(result.result)
        print(json.dumps({"listings": listings, "sitesQueried": _sites(sites, result.pages),
                          "usage": to_search_usage(result.usage)}, indent=2, ensure_ascii=False))
        return 0

    try:
        cfg = load_config()
    except ConfigError as e:
        log(str(e))
        return 2
    home = MyHome(cfg.myhome_url, cfg.myhome_token)
    try:
        if args.check:
            me = home.me()
            print(f"OK: connected to {cfg.myhome_url} as {me.get('username')} (role {me.get('role')})")
            return 0
        n = run_all(home, template=template, timeout_s=cfg.timeout_s, claude_bin=cfg.claude_bin)
    except MyHomeError as e:
        log(f"myhome error: {e}")
        return 1
    if n:
        log(f"done: {n} run(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
