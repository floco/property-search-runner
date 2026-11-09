"""Build the property-search prompt from a myhome claim, and parse Claude's answer."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .agent import AgentError

REQUIRED_FIELDS = ("title", "listingUrl", "reason")
LANGUAGES = {"en": "English", "fr": "French"}


def build_prompt(template: str, claim: dict) -> str:
    seen = claim.get("seen") or []
    seen_list = "\n".join(f"{s.get('title', '')} | {s.get('url', '')}" for s in seen) or "(none yet)"
    out = (template.replace("{today}", str(claim["today"]))
                   .replace("{max_results}", str(claim["maxResultsPerRun"]))
                   .replace("{max_age_days}", str(claim["maxListingAgeDays"]))
                   .replace("{language}", LANGUAGES.get(claim.get("language") or "en", "English")))
    # Substitute the user-provided blocks last, via markers, so braces inside
    # them are never treated as placeholders.
    out = out.replace("{seen_list}", "\x00S\x00").replace("{criteria}", "\x00C\x00")
    return out.replace("\x00S\x00", seen_list).replace("\x00C\x00", str(claim["prompt"]))


def _json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    found = []
    for m in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "listings" in value:
            found.append(value)
    return found


def _valid(item) -> bool:
    if not isinstance(item, dict) or not all(str(item.get(f) or "").strip() for f in REQUIRED_FIELDS):
        return False
    parts = urlsplit(str(item["listingUrl"]).strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def parse_listings(text: str) -> tuple[list[dict], list[str]]:
    """Return (listings, sitesQueried) from the LAST {"listings": [...]} object in the answer."""
    objects = _json_objects(text or "")
    if not objects:
        raise AgentError(f"Claude did not return a listings JSON object: {(text or '')[:300]!r}")
    final = objects[-1]
    raw = final.get("listings") if isinstance(final.get("listings"), list) else []
    listings = [item for item in raw if _valid(item)]
    if raw and not listings:
        raise AgentError(f"Claude returned {len(raw)} listings but none had title/listingUrl/reason: "
                         f"{json.dumps(raw[0])[:300]}")
    sites = [s for s in (final.get("sitesQueried") or []) if isinstance(s, str) and s.strip()]
    return listings, sites
