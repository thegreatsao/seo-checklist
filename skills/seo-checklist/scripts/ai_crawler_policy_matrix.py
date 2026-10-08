#!/usr/bin/env python3
"""Compare robots.txt and llms.txt signals for AI crawlers."""

from __future__ import annotations

import argparse
import json
from typing import NamedTuple

from lib import robots_rules
from seo_common import (carries_content, fetch_robots, fetch_url, normalize_url,
                        origin, robots_allowed)


# OpenAI splits its fetching across four tokens and blocking one does not block the
# others: `GPTBot` trains, `OAI-SearchBot` and `ChatGPT-User` answer, and `OAI-AdsBot`
# fetches the landing page of a ChatGPT ad. The last one is here because the failure it
# causes is not an SEO one — a site that disallows it has its ads **rejected at review**,
# which no other check in this registry would surface.
#
# Checked against Google's documentation on 10 August 2026: no token in this table
# controls AI Overviews or AI Mode. `Google-Extended` is the token most likely to be
# mistaken for such a control, but it governs model training and grounding in Gemini
# Apps and Vertex AI. Google's Search answer features follow `Googlebot` access plus
# the ordinary `nosnippet`, `data-nosnippet`, `max-snippet` and `noindex` directives.
#
# Anthropic, checked the same day at
# https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler:
# `ClaudeBot` collects possible training data, `Claude-User` retrieves a page at a
# user's direction, and `Claude-SearchBot` crawls to improve search answers. Anthropic
# says all three honour robots.txt.
#
# Perplexity, checked the same day at
# https://docs.perplexity.ai/docs/resources/perplexity-crawlers: `PerplexityBot`
# indexes pages for search results, while `Perplexity-User` fetches them for a user's
# question and generally ignores robots.txt. A declared restriction for the latter is
# therefore reported as not enforced rather than as a restriction the fetcher obeys.
#
# Apple, checked the same day at https://support.apple.com/en-us/119829: `Applebot`
# crawls for Spotlight, Siri and Safari, and Apple says its data can also provide
# current context for AI-generated answers. It belongs in answer feeding for that
# reason. `nosnippet` controls that answer use; `Applebot-Extended` controls training
# use and does not crawl by itself. Both tokens honour their applicable robots rules.
MODEL_TRAINING_SCOPE = "model_training"
ANSWER_FEEDING_SCOPE = "answer_feeding"
AD_REVIEW_SCOPE = "ad_landing_page_review"
NOT_ENFORCED_POLICY = "not_enforced"


class CrawlerPolicy(NamedTuple):
    scope: str
    honours_robots_txt: bool


AI_CRAWLERS = {
    "GPTBot": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "OAI-SearchBot": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "ChatGPT-User": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "OAI-AdsBot": CrawlerPolicy(AD_REVIEW_SCOPE, True),
    "ClaudeBot": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "Claude-User": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "Claude-SearchBot": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "PerplexityBot": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "Perplexity-User": CrawlerPolicy(ANSWER_FEEDING_SCOPE, False),
    "Google-Extended": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "Applebot": CrawlerPolicy(ANSWER_FEEDING_SCOPE, True),
    "Applebot-Extended": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "CCBot": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "Bytespider": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
    "Amazonbot": CrawlerPolicy(MODEL_TRAINING_SCOPE, True),
}


def matrix(site: str, paths: list[str] | None = None, timeout: int = 15) -> dict:
    base = origin(site)
    paths = paths or ["/", "/llms.txt", "/sitemap.xml"]
    robots = fetch_robots(base, timeout=timeout)
    llms = fetch_url(base + "/llms.txt", timeout=timeout, max_bytes=500_000)
    parsed = robots.get("parsed")
    rows = []
    for crawler, crawler_policy in AI_CRAWLERS.items():
        decisions = {}
        allowed_all = True
        for path in paths:
            url = normalize_url(path, base)
            allowed, rule = robots_allowed(robots.get("parsed"), url, crawler)
            decisions[path] = {"allowed": allowed, "rule": rule}
            allowed_all = allowed_all and allowed
        rows.append({
            "crawler": crawler,
            "scope": crawler_policy.scope,
            "honours_robots_txt": crawler_policy.honours_robots_txt,
            # RFC 9309 group selection: a token governed only by `*` has been
            # decided for, but the policy has not named that token.
            "named": (parsed is not None
                      and robots_rules.group_for(parsed, crawler)["matched"]
                      == robots_rules.product_token(crawler)),
            "policy": ("allowed" if allowed_all else "restricted")
                      if crawler_policy.honours_robots_txt else NOT_ENFORCED_POLICY,
            "paths": decisions,
            "llms_txt_available": carries_content(llms.get("status")),
            "alignment": "documented" if carries_content(llms.get("status")) and allowed_all else "robots_only" if not allowed_all else "allowed_without_llms_txt",
        })
    named_scopes = {
        scope: sorted(row["crawler"] for row in rows
                      if row["scope"] == scope and row["named"]
                      and row["honours_robots_txt"])
        for scope in (MODEL_TRAINING_SCOPE, ANSWER_FEEDING_SCOPE, AD_REVIEW_SCOPE)
    }
    if named_scopes[MODEL_TRAINING_SCOPE] and named_scopes[ANSWER_FEEDING_SCOPE]:
        policy_grade = "explicit"
    elif any(named_scopes.values()):
        policy_grade = "partial"
    else:
        policy_grade = "silent"

    # `fetch_error` so the runner can tell "this site allows GPTBot" from "nobody
    # answered". Without it a refused connection produced a full policy matrix built
    # entirely out of absent robots.txt rules, and GEO-003 graded it.
    return {"site": base, "robots_url": robots["url"],
            "robots_status": robots["fetch"].get("status"),
            "llms_txt_url": base + "/llms.txt", "llms_txt_status": llms.get("status"),
            "fetch_error": robots["fetch"].get("error") or llms.get("error"),
            "named_scopes": named_scopes, "policy_grade": policy_grade,
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI crawler policy matrix")
    parser.add_argument("site")
    parser.add_argument("--path", action="append", help="Path to test; repeatable")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = matrix(args.site, args.path, args.timeout)
    print(json.dumps(result, indent=2) if args.json else "\n".join(
        f"{r['crawler']}\t{r['scope']}\t{r['policy']}\t"
        f"robots.txt={'honoured' if r['honours_robots_txt'] else 'not_honoured'}\t"
        f"{r['alignment']}"
        for r in result["rows"]))


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
