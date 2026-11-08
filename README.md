# property-search-runner

Executes the **AI property searches** defined in [My Home](https://github.com/floco/myhome)
(Properties → Suggestions → Searches) with headless **Claude Code**, using the Claude
**Pro/Max subscription** logged in on this machine (no API key).

My Home owns everything else: the search definitions and their schedule, de-duplication
(a property is never suggested twice), the suggestions inbox, retention cleanup and the Brevo
email digest. This runner is the only provider-specific piece; it talks to My Home through a
small provider-neutral API:

| Call | What it does |
|------|--------------|
| `POST /api/property-search/runner/claim` | Returns the next **due** search (or 204 when nothing is due) |
| `POST /api/property-search/runner/runs/{id}/complete` | Sends the listings found, the sites queried and the usage |
| `POST /api/property-search/runner/runs/{id}/fail` | Reports `usage_limit` (retried later by My Home) or `error` |

## Setup

1. Claude Code installed and logged in with your Pro/Max account (`claude` → `/login`).
   `claude -p "hi"` must work for the user cron runs as.
2. In My Home:
   - expose the add-on's port **8000/tcp** (add-on → Configuration → Network),
   - create an API token with role **normal** (Settings → Security & Access → API tokens).
3. Here:

       cp config/settings.env.example config/settings.env
       chmod 600 config/settings.env      # then fill MYHOME_URL and MYHOME_TOKEN
       python3 -m pip install -r requirements.txt   # only httpx (+ pytest for tests)
       python3 -m propertysearch.main --check

4. Cron (root crontab):

       */15 * * * * /projects/property-search-runner/run.sh

   The runner only asks; My Home decides which searches are due from their daily / weekly /
   monthly schedule (and "Run now"), so a search runs at most 15 minutes after its slot.

## Commands

    ./run.sh                                     # drain all due searches now
    python3 -m propertysearch.main --check       # test the token and URL
    python3 -m propertysearch.main --dry-run "plots >= 800 m² near Novo Mesto under 200k EUR"
    python3 -m pytest -q                         # tests

## Where to look

- `logs/YYYY-MM-DD.log`: each run, with counts, tokens and plan usage (kept 60 days)
- My Home → Properties → Suggestions: last run status per search

## Notes

- Usage shown in emails and logs comes from Claude Code's own `rate_limit_event`
  (weekly and 5-hour plan utilisation) and per-model token counts.
- When the plan's usage limit is hit, the runner reports it and stops; My Home makes the
  search due again on a later tick (up to 3 attempts per scheduled slot).
- `propertysearch/agent.py` (the Claude Code invocation and stream parsing) is shared with
  [floco/jobsearch](https://github.com/floco/jobsearch).

## Security

Listing pages are untrusted input (they could contain instructions aimed at the AI).
Claude only gets the `WebSearch` and `WebFetch` tools: no shell, no files, and it never sees
the My Home token, which stays in the runner process. A project hook
(`.claude/settings.json` → `hooks/block_private_fetch.py`) refuses `WebFetch` to loopback,
private, link-local, `.local` and unresolvable hosts, and to ambiguous URLs (userinfo,
backslashes, encoded or numeric-shorthand hosts).

Residual risk: the hook checks DNS *before* the fetch, so a domain that changes its DNS
answer between check and fetch (DNS rebinding) could still reach a LAN address. For full
protection, add an egress firewall rule for this machine blocking RFC 1918, loopback and
link-local destinations for the `claude` process (or run it in a dedicated network namespace).
