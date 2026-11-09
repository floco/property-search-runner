import json
from pathlib import Path

import pytest

from propertysearch.agent import AgentError
from propertysearch.prompt import build_prompt, parse_listings

TEMPLATE = "C:{criteria}\nS:{seen_list}\nT:{today}\nM:{max_results}\nA:{max_age_days}"
CLAIM = {"prompt": "land {x} near {seen_list}", "today": "2026-11-08", "maxResultsPerRun": 5,
         "maxListingAgeDays": 7, "seen": [{"url": "https://a.si/1", "title": "Plot 1"}]}


def test_build_prompt_substitutes_and_protects_braces():
    out = build_prompt(TEMPLATE, CLAIM)
    assert out == "C:land {x} near {seen_list}\nS:Plot 1 | https://a.si/1\nT:2026-11-08\nM:5\nA:7"


def test_build_prompt_language_names_the_claim_language():
    assert build_prompt("L:{language}", {**CLAIM, "language": "fr"}) == "L:French"
    assert build_prompt("L:{language}", {**CLAIM, "language": "en"}) == "L:English"


def test_build_prompt_language_defaults_to_english():
    # Older myhome versions don't send a language; unknown codes fall back too.
    assert build_prompt("L:{language}", CLAIM) == "L:English"
    assert build_prompt("L:{language}", {**CLAIM, "language": "xx"}) == "L:English"


def test_build_prompt_empty_seen():
    assert "S:(none yet)" in build_prompt(TEMPLATE, {**CLAIM, "seen": []})


def test_real_prompt_template_fills_completely():
    template = (Path(__file__).resolve().parent.parent / "agent_prompt.md").read_text()
    out = build_prompt(template, {**CLAIM, "prompt": "CRITERIA"})
    assert "CRITERIA" in out and "2026-11-08" in out
    assert not any(ph in out for ph in ("{criteria}", "{seen_list}", "{today}", "{max_results}", "{max_age_days}", "{language}"))
    assert '"listings"' in out and '"sitesQueried"' in out


ITEM = {"title": "Plot 800 m²", "listingUrl": "https://a.si/2", "reason": "fits", "price": 150000, "type": "land"}


def test_parse_listings_takes_last_json_and_drops_incomplete():
    text = ('Thinking... {"listings": [], "sitesQueried": []}\nFinal:\n```json\n'
            + json.dumps({"listings": [ITEM, {"title": "no url"}, "junk", {**ITEM, "listingUrl": "ftp://x"}],
                          "sitesQueried": ["https://a.si", 5]}) + "\n```")
    listings, sites = parse_listings(text)
    assert listings == [ITEM]
    assert sites == ["https://a.si"]


def test_parse_listings_empty_ok():
    assert parse_listings('{"listings": [], "sitesQueried": ["https://b.si"]}') == ([], ["https://b.si"])


def test_parse_listings_garbage_raises():
    with pytest.raises(AgentError):
        parse_listings("Sorry, I could not search today.")


def test_parse_listings_all_wrong_shape_raises():
    with pytest.raises(AgentError):
        parse_listings(json.dumps({"listings": [{"name": "x"}], "sitesQueried": []}))
