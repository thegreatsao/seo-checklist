#!/usr/bin/env python3
"""
Fetch Core Web Vitals and performance data from Google PageSpeed Insights API.

Uses the free PSI API v5. An API key is optional but recommended — without one
Google rate-limits the endpoint aggressively. To avoid pasting the key on the
CLI, the script reads it (in priority order) from:

    1. ``--api-key <value>`` flag
    2. ``PAGESPEED_API_KEY`` environment variable
    3. ``GOOGLE_API_KEY`` environment variable
    4. A ``.env`` file in the current directory, the skill root, or
       ``$HOME/.agentic-seo/.env`` (see ``env_loader.py``)

Usage:
    python pagespeed.py https://example.com
    python pagespeed.py https://example.com --strategy mobile
    python pagespeed.py https://example.com --json
    PAGESPEED_API_KEY=AIza... python pagespeed.py https://example.com
"""

import argparse
import json
import sys
import time
from typing import Any

from env_loader import get_env

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import safe_get
except ImportError:
    from scripts.lib.safe_http import safe_get


PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
VALID_STRATEGIES = ("mobile", "desktop")

# basis: inherited — 100ms of predicted saving, present at import. Below it a Lighthouse
#  opportunity is dropped from the report, so it does decide what the audit says; the
#  number is a noise floor for an estimate Lighthouse itself calls approximate.
MIN_OPPORTUNITY_SAVINGS_MS = 100
# basis: presentation — Lighthouse's own published score bands (90 and above green, 50
#  and above amber) and a millisecond value rendered as seconds once it reaches a
#  thousand. Both only choose what the console prints.
SCORE_GOOD = 90
SCORE_AVERAGE = 50        # basis: presentation — the amber band of the pair above
SECONDS_DISPLAY_MS = 1000  # basis: presentation — where ms is printed as seconds

# Current CWV thresholds (as of 2026)
# basis: standard — the same published Core Web Vitals bands as cwv_metrics.THRESHOLDS.
#  Two copies because one reads a local trace and one reads CrUX; a test asserts they
#  agree
CWV_THRESHOLDS = {
    "LCP": {"good": 2500, "poor": 4000, "unit": "ms", "label": "Largest Contentful Paint"},
    "INP": {"good": 200, "poor": 500, "unit": "ms", "label": "Interaction to Next Paint"},
    "CLS": {"good": 0.1, "poor": 0.25, "unit": "", "label": "Cumulative Layout Shift"},
    "FCP": {"good": 1800, "poor": 3000, "unit": "ms", "label": "First Contentful Paint"},
    "TTFB": {"good": 800, "poor": 1800, "unit": "ms", "label": "Time to First Byte"},
}

# Mapping from PSI API field names to our labels
PSI_METRIC_MAP = {
    "LARGEST_CONTENTFUL_PAINT_MS": "LCP",
    "INTERACTION_TO_NEXT_PAINT": "INP",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS",
    "FIRST_CONTENTFUL_PAINT_MS": "FCP",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "TTFB",
}


def _empty_result(url: str, strategy: str) -> dict:
    return {
        "url": url,
        "strategy": strategy,
        "performance_score": None,
        "metrics": {},
        "opportunities": [],
        "diagnostics": [],
        "field_data_available": False,
        "error": None,
    }


# The two sources this script merges describe the same three bands in different
# words: CrUX says FAST/AVERAGE/SLOW, Lighthouse says good/needs-improvement/poor.
# Both landed in the same `rating` field, so a rule comparing it to "fast" could
# only ever be satisfied when CrUX had data — and CrUX has none for a low-traffic
# URL, which is most of what this tool gets pointed at. A perfect Lighthouse LCP
# came out `good`, the rule wanted `fast`, and two critical items reported FAIL on
# a fast page. One vocabulary now; `field_data_available` says where it came from.
CRUX_RATING = {"fast": "good", "average": "needs-improvement", "slow": "poor"}

# Which metrics decide the field-data verdict: the three Core Web Vitals and
# nothing else. FCP and TTFB are diagnostics, not thresholds Google grades on.
CORE_WEB_VITALS = ("LCP", "INP", "CLS")


# The three bands CrUX and Lighthouse both grade in, after CRUX_RATING has normalised
# them. Anything outside this set is a band nobody here enumerated.
KNOWN_RATINGS = ("good", "needs-improvement", "poor")


def field_cwv_verdict(metrics: dict) -> dict | None:
    """Whether real users passed Core Web Vitals — or None when nobody can say.

    Returns None when the field data covers none of the three, so the item reading
    this reports NO_DATA. "CrUX has no sample for this URL" is not "the site is
    slow": it usually means the site is small, and SP-108 used to fail it for that.

    **A rating this code does not recognise is not a failure.** `rating != "good"` used
    to make one: if the API adds a band, or `CRUX_RATING` misses a spelling, the metric
    was silently graded as failing. It became load-bearing in 0.25.0, when SP-111 to
    SP-113 stopped reading Lighthouse's blended score and started reading this verdict —
    SP-113 had its own `value_map` and answered `NO_DATA` on an unrecognised band, and
    routing it through here would have turned that honesty into a `critical` FAIL on a
    page nobody had measured. An unrecognised band is dropped from the grading and named
    in `unknown`, so an item reads `NO_DATA` when that is all there was.

    Pass is over the metrics that *were* graded, and `measured` says which. CrUX
    publishes no INP for a URL with few interactions, and refusing to answer at all
    there would throw away a verdict about LCP and CLS that Google itself reports.

    The two halves are deliberately not symmetric. **A failure among the graded metrics
    is safe to report** — one bad metric fails the assessment whatever the unrecognised
    one turns out to be. **A pass is not**, so an unrecognised band with nothing failing
    yields `verdict: "unknown"`, which no `value_map` maps and every item reading it
    reports as `NO_DATA`. Saying "Core Web Vitals passed" while one of the three is a
    word this code does not know would be the fabrication the whole field-data rule was
    written to stop.
    """
    present = {k: metrics[k] for k in CORE_WEB_VITALS if k in metrics}
    unknown = sorted(k for k, m in present.items()
                     if m.get("rating") not in KNOWN_RATINGS)
    graded = {k: m for k, m in present.items() if k not in unknown}
    if not graded and not unknown:
        return None
    failing = sorted(k for k, m in graded.items() if m.get("rating") != "good")
    if failing:
        verdict = "fail"
    elif unknown or not graded:
        verdict = "unknown"
    else:
        verdict = "pass"
    out = {"verdict": verdict, "measured": sorted(graded), "failing": failing}
    if unknown:
        out["unknown"] = unknown
    return out


def parse_pagespeed_response(data: dict[str, Any], url: str, strategy: str = "mobile") -> dict:
    """Normalize a PageSpeed Insights API response into the script output contract."""
    result = _empty_result(url, strategy)

    # Extract performance score
    lighthouse = data.get("lighthouseResult", {})
    categories = lighthouse.get("categories", {})
    perf = categories.get("performance", {})
    result["performance_score"] = round((perf.get("score", 0) or 0) * 100)

    # Extract CrUX field data (real user metrics)
    loading = data.get("loadingExperience", {})
    crux_metrics = loading.get("metrics", {})

    if crux_metrics:
        result["field_data_available"] = True
        for api_name, label in PSI_METRIC_MAP.items():
            metric_data = crux_metrics.get(api_name)
            if metric_data:
                percentile = metric_data.get("percentile")
                category = metric_data.get("category", "").lower()

                thresholds = CWV_THRESHOLDS.get(label, {})
                result["metrics"][label] = {
                    "value": percentile,
                    "unit": thresholds.get("unit", ""),
                    "label": thresholds.get("label", label),
                    # CrUX's own word is kept beside the normalised one: the
                    # rating is what rules read, the source word is what lets a
                    # reader check this mapping against the API response.
                    "rating": CRUX_RATING.get(category, category),
                    "crux_category": category,
                    "source": "field",
                }

    # Fall back to Lighthouse lab data if no field data
    if not result["field_data_available"]:
        audits = lighthouse.get("audits", {})
        lab_map = {
            "largest-contentful-paint": "LCP",
            "interaction-to-next-paint": "INP",
            "cumulative-layout-shift": "CLS",
            "first-contentful-paint": "FCP",
            "server-response-time": "TTFB",
        }
        for audit_id, label in lab_map.items():
            audit = audits.get(audit_id, {})
            if audit and audit.get("numericValue") is not None:
                value = audit["numericValue"]
                thresholds = CWV_THRESHOLDS.get(label, {})

                # Determine rating
                good = thresholds.get("good", float("inf"))
                poor = thresholds.get("poor", float("inf"))
                if value <= good:
                    rating = "good"
                elif value <= poor:
                    rating = "needs-improvement"
                else:
                    rating = "poor"

                # CLS is reported as a score, not ms
                if label == "CLS":
                    value = round(value, 3)
                else:
                    value = round(value)

                result["metrics"][label] = {
                    "value": value,
                    "unit": thresholds.get("unit", ""),
                    "label": thresholds.get("label", label),
                    "rating": rating,
                    # Where this number came from, beside the number, because two items
                    # decide from `rating` without their titles saying anything about
                    # field data — SP-107 reads FCP and SE-119 reads CLS. A lab rating
                    # answers "what did one synthetic load do", a field rating answers
                    # "what do real visitors get", and a client acts differently on each.
                    # The field branch above records `crux_category` for the same reason;
                    # this side recorded nothing, so the distinction was invisible to
                    # every surface. `openspec/specs/inputs/` INP-5.
                    "source": "lab",
                }

    # Extract opportunities
    audits = lighthouse.get("audits", {})
    for audit_id, audit in audits.items():
        if audit.get("details", {}).get("type") == "opportunity":
            savings = audit.get("details", {}).get("overallSavingsMs")
            if savings and savings > MIN_OPPORTUNITY_SAVINGS_MS:
                result["opportunities"].append({
                    "title": audit.get("title", audit_id),
                    "savings_ms": round(savings),
                    "description": audit.get("description", "")[:200],
                })

    # Sort opportunities by savings
    result["opportunities"].sort(key=lambda x: x["savings_ms"], reverse=True)

    # The field-data verdict, present only when there is field data to base it on.
    # SP-108 reads it, and an absent key is NO_DATA — which is the truthful answer
    # for a URL CrUX has never had enough traffic to sample.
    if result["field_data_available"]:
        verdict = field_cwv_verdict(result["metrics"])
        if verdict:
            result["field_cwv"] = verdict

    # Extract key diagnostics
    diagnostic_ids = [
        "dom-size", "total-byte-weight", "render-blocking-resources",
        "uses-responsive-images", "uses-webp-images", "font-display",
    ]
    for diag_id in diagnostic_ids:
        diag = audits.get(diag_id, {})
        if diag and diag.get("score") is not None and diag["score"] < 1:
            result["diagnostics"].append({
                "title": diag.get("title", diag_id),
                "score": round(diag["score"] * 100),
                "display": diag.get("displayValue", ""),
            })

    return result


def get_pagespeed(url: str, strategy: str = "mobile", api_key: str = None) -> dict:
    """
    Fetch PageSpeed Insights data for a URL.

    Args:
        url: URL to analyze
        strategy: 'mobile' or 'desktop'
        api_key: Optional Google API key for higher rate limits

    Returns:
        Dictionary with CWV metrics, performance score, and opportunities
    """
    if strategy not in VALID_STRATEGIES:
        result = _empty_result(url, strategy)
        result["error"] = f"Unsupported strategy: {strategy}"
        return result
    result = _empty_result(url, strategy)

    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
    }
    if api_key:
        params["key"] = api_key

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = safe_get(PSI_API, params=params, timeout=60)

            if resp.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3  # Simple backoff: 3s, 6s
                    print(f"  [pagespeed] Rate limited by API. Retrying in {wait_time}s...", file=sys.stderr)
                    time.sleep(wait_time)
                    continue
                else:
                    result["error"] = "Rate limited by Google API. Wait a few minutes or add an API key."
                    return result

            if resp.status_code != 200:
                result["error"] = f"API error: HTTP {resp.status_code}"
                return result

            data = resp.json()
            return parse_pagespeed_response(data, url=url, strategy=strategy)

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                print("  [pagespeed] Timeout. Retrying...", file=sys.stderr)
                time.sleep(2)
                continue
            result["error"] = "API request timed out (60s) — try again later"
            return result
        except requests.exceptions.RequestException as e:
            result["error"] = f"Request failed: {e}"
            return result
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            result["error"] = f"Failed to parse API response: {e}"
            return result

    return result


def get_pagespeed_for_strategies(url: str, strategies: list[str], api_key: str = None) -> dict:
    """Fetch PageSpeed data for multiple strategies and preserve per-strategy errors."""
    results = {strategy: get_pagespeed(url, strategy=strategy, api_key=api_key) for strategy in strategies}
    errors = {strategy: data.get("error") for strategy, data in results.items() if data.get("error")}
    return {
        "url": url,
        "strategies": results,
        "error": "; ".join(f"{strategy}: {error}" for strategy, error in errors.items()) if errors else None,
    }


def print_result(result: dict):
    """Print one normalized PageSpeed result in the existing human-readable format."""
    if result["error"]:
        print(f"Error: {result['error']}")
        return

    print(f"PageSpeed Insights — {result['url']}")
    print(f"Strategy: {result['strategy'].upper()}")
    print("=" * 50)

    score = result["performance_score"]
    if score >= SCORE_GOOD:
        icon = "🟢"
    elif score >= SCORE_AVERAGE:
        icon = "🟡"
    else:
        icon = "🔴"
    print(f"\nPerformance Score: {icon} {score}/100")

    data_source = "Field Data (CrUX)" if result["field_data_available"] else "Lab Data (Lighthouse)"
    print(f"Data Source: {data_source}")

    if result["metrics"]:
        print("\nCore Web Vitals:")
        for name, metric in result["metrics"].items():
            rating = metric["rating"]
            if "good" in rating.lower() or "fast" in rating.lower():
                icon = "✅"
            elif "poor" in rating.lower() or "slow" in rating.lower():
                icon = "🔴"
            else:
                icon = "⚠️"

            unit = metric["unit"]
            value = metric["value"]
            if unit == "ms" and value >= SECONDS_DISPLAY_MS:
                display = f"{value/1000:.1f}s"
            elif unit == "ms":
                display = f"{value}ms"
            else:
                display = str(value)

            # Show threshold comparison
            thresholds = CWV_THRESHOLDS.get(name, {})
            good = thresholds.get("good", "?")
            threshold_unit = thresholds.get("unit", "")
            threshold_str = f"(target: <{good}{threshold_unit})" if good != "?" else ""

            print(f"  {icon} {metric['label']}: {display} {threshold_str}")

    if result["opportunities"]:
        print("\nTop Opportunities:")
        for opp in result["opportunities"][:5]:
            savings = opp["savings_ms"]
            if savings >= SECONDS_DISPLAY_MS:
                display = f"{savings/1000:.1f}s"
            else:
                display = f"{savings}ms"
            print(f"  💡 {opp['title']} (save ~{display})")

    if result["diagnostics"]:
        print("\nDiagnostics:")
        for diag in result["diagnostics"]:
            print(f"  ⚠️ {diag['title']}: {diag['display']}")


def main():
    parser = argparse.ArgumentParser(description="Get Core Web Vitals from PageSpeed Insights")
    parser.add_argument("url", help="URL to analyze")
    parser.add_argument("--strategy", "-s", default="mobile",
                        choices=["mobile", "desktop", "both"], help="Analysis strategy")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--api-key", help="Google API key for higher rate limits")

    args = parser.parse_args()
    api_key = args.api_key or get_env("PAGESPEED_API_KEY", "GOOGLE_API_KEY")

    if args.strategy == "both":
        result = get_pagespeed_for_strategies(args.url, list(VALID_STRATEGIES), api_key=api_key)
        if args.json:
            print(json.dumps(result, indent=2))
            return
        for idx, strategy in enumerate(VALID_STRATEGIES):
            if idx:
                print("\n")
            print_result(result["strategies"][strategy])
        if result["error"]:
            sys.exit(1)
        return

    result = get_pagespeed(args.url, strategy=args.strategy, api_key=api_key)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)
    print_result(result)


if __name__ == "__main__":
    main()
