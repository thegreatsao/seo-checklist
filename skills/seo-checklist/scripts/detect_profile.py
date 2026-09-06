#!/usr/bin/env python3
"""
Guess what kind of site this is, so the checklist can be narrowed to it.

This is a **suggestion, not a decision**. Every signal is reported with the
evidence that produced it, and the caller is expected to confirm. Picking a
narrower profile on a guess would drop checks and raise the score without anyone
choosing that — which is exactly the failure the registry exists to prevent.

Signals are structural (schema.org types, platform fingerprints, cart and
pricing markup) rather than textual, because wording is the first thing that
lies: a plumber's site says "shop" in the nav and an online store says "about
our family business" on the homepage.

Usage:
    python detect_profile.py https://example.com --json
    python detect_profile.py --html ./site/index.html --url https://example.com --json
"""

import argparse
import json
import os
import re
import sys


# Not every caller is the runner. This script prints `ensure_ascii=False` JSON, and a
# bare `python <script> …` on Windows encodes stdout with the ANSI codepage — so a
# Greek query or a Polish name raises UnicodeEncodeError and the script produces
# nothing at all. The runner now hands its children a UTF-8 environment; this is the
# same guarantee for somebody running the script by hand.
def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # already wrapped, or not a TextIO
            pass


_utf8_stdout()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from seo_common import html_parser
except ImportError:
    from scripts.seo_common import html_parser

# schema.org @type -> (profile, weight, why). Structured data is the strongest
# signal available because the site author declared it on purpose.
# basis: inherited — present at import. Weights for guessing a site's type from its
#  schema, and the guess is only ever a suggestion the operator confirms — which is the
#  reason this one can stay unexamined without deciding anything
SCHEMA_SIGNALS = {
    "product": ("ecommerce", 4, "Product schema"),
    "offer": ("ecommerce", 3, "Offer schema"),
    "aggregateoffer": ("ecommerce", 3, "AggregateOffer schema"),
    "itemlist": ("ecommerce", 1, "ItemList schema"),
    "localbusiness": ("local", 4, "LocalBusiness schema"),
    "restaurant": ("local", 4, "Restaurant schema"),
    "lodgingbusiness": ("local", 4, "LodgingBusiness schema"),
    "hotel": ("local", 4, "Hotel schema"),
    "store": ("local", 2, "Store schema"),
    "place": ("local", 2, "Place schema"),
    "blogposting": ("blog", 4, "BlogPosting schema"),
    "blog": ("blog", 4, "Blog schema"),
    "newsarticle": ("media", 4, "NewsArticle schema"),
    "newsmediaorganization": ("media", 4, "NewsMediaOrganization schema"),
    "liveblogposting": ("media", 3, "LiveBlogPosting schema"),
    "softwareapplication": ("saas", 4, "SoftwareApplication schema"),
    "webapplication": ("saas", 4, "WebApplication schema"),
    "saasapplication": ("saas", 4, "SaaSApplication schema"),
}

# Platform fingerprints in markup and asset paths.
# basis: inherited — present at import, and the same argument as `SCHEMA_SIGNALS` above,
#  now with the measurement under it. What a profile decides was counted for 0.80.1:
#  `local` excludes 4 of the 217 items, `saas`, `blog` and `media` exclude 7 each, and
#  `default` and `ecommerce` exclude none — an excluded item reports N/A. What stops that
#  from being a silent narrowing is `choose_profile`, and the order of its branches is the
#  whole of it: `--profile auto` returns the detector's answer in any environment, with or
#  without a terminal, because typing the flag is the decision. Every other run without an
#  explicit profile asks a person, and where there is nobody to ask it falls back to
#  `default` — the whole registry — and says so on stderr. So these weights narrow scope
#  only behind a flag somebody typed, and never by themselves.
PLATFORM_SIGNALS = [
    (r"cdn\.shopify\.com|shopify-", "ecommerce", 4, "Shopify"),
    (r"woocommerce|wp-content/plugins/woocommerce", "ecommerce", 4, "WooCommerce"),
    # `mage/` without the leading slash also matches `image/`, which fingerprinted
    # Magento on two sites that have never seen it.
    (r"/skin/frontend/|/js/mage/|magento", "ecommerce", 4, "Magento"),
    (r"prestashop", "ecommerce", 4, "PrestaShop"),
    (r"bigcommerce", "ecommerce", 4, "BigCommerce"),
    (r"opencart", "ecommerce", 3, "OpenCart"),
    (r"ghost\.io|content/themes/casper", "blog", 3, "Ghost"),
    (r"wp-content/themes", "blog", 1, "WordPress theme"),
]

# Same-page link paths. Weak on their own; they matter in aggregate.
# basis: inherited — present at import; the scope argument written over `PLATFORM_SIGNALS`
#  covers this table too. Its weights run 1 to 3, the same span as `MARKUP_SIGNALS` and one
#  short of `PLATFORM_SIGNALS`, which is where a fingerprint names the platform outright.
PATH_SIGNALS = [
    (r"/cart\b|/basket\b|/checkout\b|add-to-cart", "ecommerce", 3, "cart or checkout link"),
    (r"/product[s]?/|/shop\b|/collections?/", "ecommerce", 2, "product or shop paths"),
    (r"/blog\b|/posts?/|/article[s]?/", "blog", 2, "blog paths"),
    (r"/news\b|/opinion\b|/politics\b|/sport\b", "media", 2, "news sections"),
    (r"/pricing\b|/plans\b", "saas", 3, "pricing or plans page"),
    (r"/signup\b|/sign-up\b|/register\b|/free-trial\b|/get-started\b", "saas", 2,
     "signup or trial link"),
    (r"/login\b|/signin\b|/sign-in\b|/app\b|/dashboard\b", "saas", 1, "app login link"),
    (r"/contacts?\b|/kontakt|/kontaktai", "local", 1, "contact page"),
]

# basis: inherited — present at import; the third table under the same scope argument as
#  `PLATFORM_SIGNALS`. Read together with it: `detect()` sums both against one page.
MARKUP_SIGNALS = [
    (r'itemprop=["\']price["\']|class=["\'][^"\']*\bprice\b', "ecommerce", 2, "price markup"),
    (r"google\.com/maps/embed|maps\.google\.|yandex\.[a-z]+/map", "local", 3, "embedded map"),
    (r'itemprop=["\']openingHours|opening[-_]?hours', "local", 3, "opening hours"),
    (r"tel:\+?\d", "local", 1, "click-to-call number"),
    (r'itemprop=["\']streetAddress|<address\b', "local", 2, "postal address"),
    (r'rel=["\']author|itemprop=["\']author', "blog", 1, "author byline"),
    (r"<time\b[^>]*datetime=", "blog", 1, "article timestamps"),
]

PROFILES = ("ecommerce", "local", "saas", "blog", "media")
# Below this the evidence is too thin to suggest narrowing anything.
# basis: inherited — present at import. With CLEAR_MARGIN it decides whether profile
#  detection suggests anything at all; tuned against the two fixtures here and nothing
#  else, which is the weakest evidence any threshold in this tree has
MIN_SCORE = 4
# basis: inherited — present at import; see MIN_SCORE above
CLEAR_MARGIN = 3


def _schema_types(soup) -> list[str]:
    """Every @type in every JSON-LD block, flattened. A block is legally a single
    node, an array, or a @graph container, and @type itself may be a list."""
    out = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t.lower())
        elif isinstance(t, list):
            # extend, not `+=`: augmented assignment inside a closure rebinds the
            # name as local and breaks every other branch that only reads it.
            out.extend(str(x).lower() for x in t)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                walk(node[key])

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or "{}"))
        except (ValueError, TypeError):
            continue
    # Microdata, still common on older storefronts.
    for tag in soup.find_all(attrs={"itemtype": True}):
        out.append(str(tag["itemtype"]).rsplit("/", 1)[-1].lower())
    return out


def detect(html: str, url: str = "") -> dict:
    result = {
        "url": url,
        "profile": "default",
        "confidence": "none",
        "scores": {p: 0 for p in PROFILES},
        "signals": {p: [] for p in PROFILES},
        "runner_up": None,
        "error": None,
    }
    if not html:
        result["error"] = "no HTML to inspect"
        return result

    soup = BeautifulSoup(html, html_parser())
    lower = html.lower()

    def hit(profile, weight, why):
        if why not in result["signals"][profile]:
            result["scores"][profile] += weight
            result["signals"][profile].append(why)

    for t in _schema_types(soup):
        if t in SCHEMA_SIGNALS:
            profile, weight, why = SCHEMA_SIGNALS[t]
            hit(profile, weight, why)

    for pattern, profile, weight, why in PLATFORM_SIGNALS + MARKUP_SIGNALS:
        if re.search(pattern, lower):
            hit(profile, weight, why)

    hrefs = " ".join(a.get("href", "") for a in soup.find_all("a", href=True)).lower()
    for pattern, profile, weight, why in PATH_SIGNALS:
        if re.search(pattern, hrefs):
            hit(profile, weight, why)

    ranked = sorted(result["scores"].items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    second, second_score = ranked[1]

    if best_score < MIN_SCORE:
        # Not enough to justify narrowing anything. `default` runs everything,
        # which is the safe answer when the evidence is thin.
        result.update(profile="default", confidence="none")
    elif best_score - second_score >= CLEAR_MARGIN:
        result.update(profile=best, confidence="high")
    else:
        result.update(profile=best, confidence="low",
                      runner_up={"profile": second, "score": second_score})
    return result


def main():
    ap = argparse.ArgumentParser(description="Suggest a checklist site profile")
    ap.add_argument("url", nargs="?", default="", help="page to inspect")
    ap.add_argument("--html", default="", help="local HTML file instead of fetching")
    ap.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    a = ap.parse_args()

    html = ""
    if a.html:
        with open(a.html, encoding="utf-8", errors="replace") as f:
            html = f.read()
    elif a.url:
        try:
            from lib.safe_http import safe_get
        except ImportError:
            from scripts.lib.safe_http import safe_get
        try:
            html = safe_get(a.url, timeout=15).text
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"error": str(exc)[:200], "profile": "default"})
                  if a.json else f"fetch failed: {exc}")
            return
    else:
        ap.error("give a URL or --html")

    result = detect(html, a.url)
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(f"Suggested profile: {result['profile']} ({result['confidence']} confidence)")
    for p, score in sorted(result["scores"].items(), key=lambda kv: -kv[1]):
        if score:
            print(f"  {p:<10} {score:>3}  {', '.join(result['signals'][p])}")


if __name__ == "__main__":
    main()
