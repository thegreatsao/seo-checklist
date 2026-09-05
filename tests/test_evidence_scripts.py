"""Every remaining evidence script, run against a served page, through its own path.

`test_evidence.py` covers the seven scripts that decide the nineteen `critical`
items. This file covers the other 43 — 83 registry items — and the rule is the same
one: **each test asserts the field the registry actually reads**, named in the test,
so a script that quietly changes its output contract fails here instead of in a
client's report.

Why this was worth the trouble twice over: writing the first 34 found eighteen
assertions that had never fired, and writing the eight for `image_weight_audit.py`
found two items that failed sites for serving images the recommended way. One defect
per two or three tests, two releases running. That rate is the argument — not a
coverage percentage.

**The scripts are not stubbed and not imported.** Each runs as a subprocess with
`--json`, exactly as `checklist_runner.run_script` runs it, against a real origin on
loopback. A stub tests the seam you thought of; these scripts reach for HTTP through
four different seams, and their own redirect handling, content-type checks, robots
logic and pacing are all things a stub replaces with an assumption.

Two origins, because `robots.txt`, `llms.txt` and the sitemap belong to an *origin*
rather than a directory — one document root cannot be both present and absent, so a
single origin could only ever test those in one direction.

Every run happens once, in `setUpModule`, in parallel, and is cached: 40 scripts is
~80 process launches, and doing them per test method would make this file slower than
the rest of the suite put together.
"""
import ast
import http.client
import http.server
import inspect
import json
import os
import re
import socket
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest import mock
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
REGISTRY = os.path.join(SKILL, "resources", "config", "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from harness import served  # noqa: E402

from checklist_runner import (  # noqa: E402
    FAIL, NEEDS_INPUT, NO_DATA, PASS, WARN, build_plan, evaluate,
    grade, input_truncated, passes_by_absence,
)

with open(REGISTRY, encoding="utf-8") as f:
    ITEMS = {i["id"]: i for i in json.load(f)["items"]}


def verdict(item_id: str, output: dict) -> str:
    """The item's real rule over a script's real output, graded as the runner grades.

    The rule is read from the registry rather than restated here. A test that
    hard-codes `{"path": "score", "gte": 70}` keeps passing after the registry stops
    asking for it, which is exactly how a check goes quiet.
    """
    check = ITEMS[item_id]["check"]
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


def graded_verdict(item_id: str, output: dict) -> str:
    """The verdict after runner-level rules such as capped-input withholding."""
    item = ITEMS[item_id]
    key = (item["check"]["script"], ())
    return grade([item], {key: [item_id]}, {key: output}, {}, False)[0]["status"]


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------

# Rewritten to whichever port the origin bound, the same way the fixture trees are,
# so canonicals, sitemap entries, hreflang targets and `Location` headers point at
# themselves. Getting this wrong is not subtle in its effects and is very subtle to
# read: the first version of this file replaced a string the bodies did not contain,
# so every absolute URL pointed at a host that does not exist — and the *symptoms*
# were six checks reporting plausible-looking failures about self-reference, orphans,
# duplicate canonicals and redirect hops. Half an hour of reading them as script bugs.
PLACEHOLDER = "PLACEHOLDER"

GOOD_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Sourdough starter care: feeding, reviving and storing</title>
<meta name="description" content="How to feed and revive a sourdough starter, with timings for warm and cold kitchens.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="PLACEHOLDER/">
<link rel="icon" href="/favicon.ico">
<meta property="og:title" content="Sourdough starter care">
<meta property="og:description" content="Feeding and reviving a sourdough starter.">
<meta property="og:image" content="PLACEHOLDER/i/a.webp">
<meta property="og:url" content="PLACEHOLDER/">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Fixture Bakery">
<meta property="og:locale" content="en_GB">
<meta property="article:published_time" content="2026-07-01">
<meta name="twitter:site" content="@fixturebakery">
<meta name="twitter:image:alt" content="A round sourdough loaf">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Sourdough starter care">
<meta name="twitter:description" content="Feeding and reviving a starter.">
<meta name="twitter:image" content="PLACEHOLDER/i/a.webp">
<link rel="stylesheet" href="/s.min.css">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article",
"headline":"Sourdough starter care: feeding, reviving and storing","datePublished":"2026-07-01",
"dateModified":"2026-07-20","author":{"@type":"Person","name":"A Baker","url":"PLACEHOLDER/about.html"},
"publisher":{"@type":"Organization","name":"Fixture Bakery","url":"PLACEHOLDER/",
"logo":{"@type":"ImageObject","url":"PLACEHOLDER/i/logo.png","width":600,"height":60}},
"image":"PLACEHOLDER/i/a.webp","description":"How to feed and revive a sourdough starter.",
"mainEntityOfPage":{"@type":"WebPage","@id":"PLACEHOLDER/"}}</script>
</head><body>
<header><nav><a href="/">Starter care</a> <a href="/about.html">Who we are</a>
<a href="/guide.html">Baking guide</a> <a href="/privacy.html">Privacy</a></nav></header>
<main><h1>Sourdough starter care</h1>
<p>A sourdough starter is flour and water kept alive by regular feeding. Last updated
20 July 2026 by A Baker, who has kept the same culture since 2019.</p>
<h2>How often should you feed a sourdough starter?</h2>
<p>Once a day at room temperature, or once a week in the refrigerator. A starter fed
on a schedule rises predictably, and predictability is the whole point of keeping one
rather than buying yeast. Acidity slows starch retrogradation, which is why a sour
loaf stales more slowly than a sweet one.</p>
<h2>What does it mean when a starter smells of acetone?</h2>
<p>It is hungry. The smell is ethanol and acetic acid accumulating because the
available starch has been consumed. Feed it twice at twelve-hour intervals and it
recovers; discard nothing but the excess.</p>
<h2>Can you revive a starter that has been neglected for months?</h2>
<p>Usually yes. Scrape off any dry crust, keep a spoonful of the wet centre, and feed
it every twelve hours for three days. Lactobacilli survive far longer than bakers
expect, and a culture that looks dead is generally only dormant.</p>
<h3>Storing a starter between bakes</h3>
<p>Refrigerate it in a jar with a loose lid. Cold slows fermentation without stopping
it, so a weekly feed is enough. Feed it twice at room temperature before you bake, and
give the second feed at least four hours so the culture is at its peak when it goes
into the dough rather than already falling back.</p>
<table><caption>Feeding schedule</caption>
<tr><th>Kitchen</th><th>Interval</th></tr>
<tr><td>Warm (24C)</td><td>Every 12 hours</td></tr>
<tr><td>Cold (18C)</td><td>Once a day</td></tr></table>
<ul><li>Feed by weight, not by volume.</li><li>Use unchlorinated water.</li>
<li>Keep the jar loosely covered.</li></ul>
<blockquote cite="PLACEHOLDER_EXTERNAL"><p>Sourdough fermentation
is driven by lactic acid bacteria and yeasts.</p></blockquote>
<p>Sources: <a href="PLACEHOLDER_EXTERNAL">Encyclopedia on
sourdough</a>, and our own <a href="/about.html">editorial policy</a>.</p>
<figure><picture><source type="image/webp" srcset="/i/a.webp 1x, /i/a.webp 2x"
sizes="(max-width: 600px) 64px, 128px">
<img src="/i/a.png" alt="A round sourdough loaf, scored across the top"
width="64" height="64" fetchpriority="high" decoding="async"></picture>
<figcaption>A finished loaf.</figcaption></figure>
</main>
<footer><p>Fixture Bakery, 1 Fixture Street, Vilnius, Lithuania. Telephone
+370 600 00000. <a href="/privacy.html">Privacy policy</a> ·
<a href="/about.html#contact">Contact</a></p></footer>
<script src="/s.js" defer></script></body></html>""".replace(
    "PLACEHOLDER_EXTERNAL", harness.PLACEHOLDER_EXTERNAL)

# Deliberately failing, and failing in ways a *page* can: the origin-level defects
# live on the second origin because robots.txt and llms.txt cannot be both there and
# not there behind one port.
BAD_PAGE = """<!doctype html><html><head>
<title>page</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="https://elsewhere.example/other">
<script src="https://cdn.jsdelivr.net/npm/heavy/heavy.js"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-DUPLICATE"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-DUPLICATE"></script>
<link rel="stylesheet" href="/s.css">
<style>
  body { font-size : 9px ; color : #eeeeee ; background : #ffffff }
  /* a comment left in, and a great deal of pointless whitespace */
</style>
</head><body>
<h1>a</h1><h1>b</h1>
<p style="font-size:8px;color:#f0f0f0;background:#ffffff">short</p>
<img src="/i/missing.png"><img src="/i/a.png" alt="">
<a href="http://insecure.invalid/x">click here</a>
<a href="/gone">here</a> <a href="/thin-indexable.html">stub</a>
<a href="/shop?utm_source=s0&amp;SESSIONID=0&amp;color=c0&amp;size=z0&amp;sort=k0">Filter 0</a>
<a href="/shop?utm_source=s1&amp;SESSIONID=1&amp;color=c1&amp;size=z1&amp;sort=k1">Filter 1</a>
<a href="/shop?utm_source=s2&amp;SESSIONID=2&amp;color=c2&amp;size=z2&amp;sort=k2">Filter 2</a>
<a href="/shop?utm_source=s3&amp;SESSIONID=3&amp;color=c3&amp;size=z3&amp;sort=k3">Filter 3</a>
<a href="/shop?utm_source=s4&amp;SESSIONID=4&amp;color=c4&amp;size=z4&amp;sort=k4">Filter 4</a>
<a href="/shop?utm_source=s5&amp;SESSIONID=5&amp;color=c5&amp;size=z5&amp;sort=k5">Filter 5</a>
<script src="/s.js"></script></body></html>"""

# One page per shape a script needs and the two above do not have.
INTL_BROKEN = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Intl</title><link rel="canonical" href="PLACEHOLDER/intl-broken.html">
<link rel="alternate" hreflang="en-GB" href="http://PLACEHOLDER_HOST/intl-broken.html">
<link rel="alternate" hreflang="de-DE" href="PLACEHOLDER/de.html">
<link rel="alternate" hreflang="xx-YY" href="PLACEHOLDER/xx.html">
</head><body><h1>Intl</h1><p>No self-reference, no x-default, mixed protocol.</p>
</body></html>"""

INTL_GOOD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Intl</title><link rel="canonical" href="PLACEHOLDER/intl.html">
<link rel="alternate" hreflang="en" href="PLACEHOLDER/intl.html">
<link rel="alternate" hreflang="de" href="PLACEHOLDER/de.html">
<link rel="alternate" hreflang="x-default" href="PLACEHOLDER/intl.html">
</head><body><h1>Intl</h1><p>Self-referencing, x-default present, one protocol.</p>
</body></html>"""

FAQ_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Questions</title><link rel="canonical" href="PLACEHOLDER/faq.html">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage",
"mainEntity":[{"@type":"Question","name":"How often do you feed a starter?",
"acceptedAnswer":{"@type":"Answer","text":"Once a day at room temperature."}}]}</script>
</head><body><h1>Questions</h1>
<h2>How often do you feed a starter?</h2>
<p>Once a day if the jar sits at room temperature, and once a week if it lives in the
refrigerator. The interval matters more than the quantity: a starter fed on a schedule
rises predictably, and a predictable rise is the only reason to keep one rather than
opening a packet of yeast.</p>
<h2>What is a levain?</h2>
<p>A levain is a portion of starter built specifically for one bake, usually mixed the
night before. It lets you keep a small culture in the refrigerator and still produce
enough leaven for a large dough, and it means an error in the levain costs you one
loaf rather than the whole culture.</p>
<h2>Why does my loaf spread instead of rising?</h2>
<p>Almost always one of two things: gluten that was never developed enough to hold a
shape, or a dough left to prove until the structure gave out. Both look identical
coming out of the basket, and the way to tell them apart is to shorten the prove by an
hour and see whether the next loaf holds.</p>
<dl><dt>Levain</dt><dd>A portion of starter built for a single bake.</dd>
<dt>Autolyse</dt><dd>Flour and water rested before salt is added.</dd></dl>
<ol><li>Feed the starter.</li><li>Wait four hours.</li><li>Mix the dough.</li></ol>
</body></html>"""

BROKEN_SCHEMA_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Broken schema</title><link rel="canonical" href="PLACEHOLDER/schema-bad.html">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
"name":"A loaf"}</script>
<script type="application/ld+json">{"@context":"https://schema.org",
"@type":"BreadcrumbList"}</script>
<script type="application/ld+json">{not valid json at all</script>
</head><body><h1>Broken schema</h1><p>Product with no offers, breadcrumb with no
items, and one block that is not JSON.</p></body></html>"""

VIDEO_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Video</title><link rel="canonical" href="PLACEHOLDER/video.html">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"VideoObject",
"name":"Shaping a boule","description":"How to shape a round loaf.",
"thumbnailUrl":"PLACEHOLDER/i/a.webp","uploadDate":"2026-07-01","duration":"PT4M30S",
"contentUrl":"PLACEHOLDER/v/shape.mp4"}</script>
</head><body><h1>Video</h1>
<iframe src="https://www.youtube.com/embed/xyz" title="Shaping a boule"></iframe>
</body></html>"""

def page(slug: str, title: str, heading: str, body: str) -> str:
    """A page in the good site's shape, with its own content.

    Distinct bodies are load-bearing rather than tidy: serving one document at four
    paths makes them exact duplicates, and `duplicate_content.py` is right to say so —
    the first version of this file did exactly that and read four correct `Critical`
    duplicate findings as a bug in the script.
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{heading} — Fixture Bakery, Vilnius.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="PLACEHOLDER/{slug}">
<link rel="stylesheet" href="/s.min.css">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article",
"headline":"{title}","datePublished":"2026-06-02","dateModified":"2026-07-19",
"author":{{"@type":"Person","name":"A Baker","url":"PLACEHOLDER/about.html"}},
"publisher":{{"@type":"Organization","name":"Fixture Bakery","url":"PLACEHOLDER/"}},
"mainEntityOfPage":{{"@type":"WebPage","@id":"PLACEHOLDER/{slug}"}}}}</script>
</head><body>
<header><nav><a href="/">Starter care</a> <a href="/about.html">Who we are</a>
<a href="/guide.html">Baking guide</a> <a href="/privacy.html">Privacy</a></nav></header>
<main><h1>{heading}</h1>
{body}
</main>
<footer><p>Fixture Bakery, 1 Fixture Street, Vilnius, Lithuania. Telephone
+370 600 00000. <a href="/privacy.html">Privacy policy</a></p></footer>
</body></html>"""


ABOUT_PAGE = page(
    "about.html", "About Fixture Bakery and who writes these guides",
    "About the bakery",
    """<p>Fixture Bakery has been open since 2019 on Fixture Street in Vilnius. We bake
four kinds of sourdough, and everything on this site is written by the people who do
the baking rather than by an agency. This page exists so a reader can tell who is
making a claim before deciding whether to trust it.</p>
<h2>Who writes here</h2>
<p>A Baker keeps the culture, runs the ovens six mornings a week, and writes the
guides. Before the bakery there were eleven years in restaurant kitchens, four of
them in bread specifically. Nothing here is theoretical: every timing published on
this site is one we work to, and when a timing changes we change the page and note
the date at the top of it.</p>
<h2>How we test what we publish</h2>
<p>A method reaches this site after we have used it for at least two months in
production. Flour behaves differently between harvests, so a schedule that worked one
autumn may need adjusting the next, and we would rather publish a range than a false
precision. Where a claim depends on temperature we give the temperature. Where it
depends on a specific flour we name the flour.</p>
<h2>Corrections</h2>
<p>If something here is wrong, write to the address in the footer and we will correct
the page and say what changed. Two corrections have been made this year: a
hydration figure that was quoted for a different flour, and a proofing time that
assumed a warmer kitchen than most people have. Both are noted on the pages
themselves.</p>
<h2>Where to find us</h2>
<p>The shop is at 1 Fixture Street, Vilnius, open from seven in the morning until the
bread runs out, which in practice means early afternoon. The telephone number in the
footer reaches the counter rather than a call centre.</p>""")

GUIDE_PAGE = page(
    "guide.html", "A baking guide: mixing, folding, shaping and scoring",
    "Baking guide",
    """<p>This guide covers the four things that decide whether a loaf works: how the
dough is mixed, how it is folded, how it is shaped and how it is scored. It assumes
you already have an active starter — feeding one is covered on the starter care
page.</p>
<h2>Mixing</h2>
<p>Mix flour and water first and leave them for forty minutes before adding salt or
levain. The rest lets the flour hydrate fully, which makes the dough easier to handle
and shortens the kneading you will need afterwards. Weigh everything. Volume
measurement of flour varies by a fifth depending on how the cup was filled, and a
fifth is the difference between a slack dough and a stiff one.</p>
<h2>Folding</h2>
<p>Fold every forty minutes for the first two hours, then leave the dough alone.
Folding builds structure without tearing the gluten the way sustained kneading can,
and the interval matters more than the technique: dough that is folded on a schedule
develops predictably, and predictability is what lets you plan a bake around the
rest of your day.</p>
<h2>Shaping</h2>
<p>Shape in two stages with a twenty-minute rest between them. The first stage
gathers the dough into a rough round and the second tightens it. Attempting both at
once tears the surface, and a torn surface spreads in the oven however carefully it
was proofed.</p>
<h2>Scoring</h2>
<p>Score once, deeply, just before the loaf goes in. A single confident cut opens
better than several shallow ones, and a blade held at an angle produces the ear that
people associate with a good bake. None of this affects the taste.</p>""")

PRIVACY_PAGE = page(
    "privacy.html", "Privacy policy: what this site collects and why",
    "Privacy policy",
    """<p>This page explains what data this site collects, why it collects it, how long
it is kept and how to ask for it to be deleted. It was last reviewed on 19 July 2026.
If anything here is unclear, the address in the footer reaches a person.</p>
<h2>What we collect</h2>
<p>The web server keeps an access log containing the requested page, the time, the
browser's user agent and a truncated IP address. The log exists to find broken pages
and to tell a search engine crawler from a visitor. It is kept for thirty days and
then deleted automatically.</p>
<h2>Cookies</h2>
<p>This site sets no cookies of its own and loads no analytics or advertising
scripts, so there is nothing to consent to and no banner asking you to. If that
changes, this page will change first and the date above will move.</p>
<h2>Ordering bread</h2>
<p>Orders taken by telephone are written on paper at the counter and thrown away
once the order has been collected. We do not keep a customer list and we do not send
marketing of any kind, because we bake a fixed amount each morning and it sells.</p>
<h2>Your rights</h2>
<p>Under the GDPR you can ask what we hold about you, ask for it to be corrected, or
ask for it to be deleted. Given the above the answer is usually that we hold
nothing, but ask and we will check the access log for the period you name and tell
you what is in it. Requests are answered within a week.</p>
<h2>Data protection contact</h2>
<p>Write to the address in the footer, marked for the attention of the data
protection contact, who is the same person who does the baking.</p>""")

# Every anchor identical and pointing at one target, which is what BL-081 counts.
# Neither of the two main pages can carry this: varied navigation is what a good site
# has, and the bad page's links are varied for other reasons.
SPAMMY_ANCHORS = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Links</title><link rel="canonical" href="PLACEHOLDER/spammy.html"></head><body>
<h1>Links</h1>
<p>Buy <a href="/shop.html">cheap sourdough bread</a> today.</p>
<p>We sell <a href="/shop.html">cheap sourdough bread</a> daily.</p>
<p>Order <a href="/shop.html">cheap sourdough bread</a> online.</p>
<p>Try our <a href="/shop.html">cheap sourdough bread</a> now.</p>
<p>More <a href="/shop.html">cheap sourdough bread</a> here.</p>
</body></html>"""

# The hero image lazy-loaded, which delays the largest paint by a round trip. CN-054
# reads `summary.lazy_lcp_candidates`, and a page has to have exactly this shape for
# the count to be anything but zero.
LAZY_HERO = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Lazy hero</title><link rel="canonical" href="PLACEHOLDER/lazy.html"></head><body>
<h1>Lazy hero</h1>
<img src="/i/a.png" alt="A round sourdough loaf" width="800" height="400" loading="lazy">
<p>The first and largest image on the page, told to wait.</p></body></html>"""

FONT_EXTERNAL_BLOCKING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Blocking external font</title><link rel="stylesheet" href="/font-blocking.css">
</head><body><h1>Blocking external font</h1></body></html>"""

FONT_EXTERNAL_SWAP = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Swapped external font</title><link rel="stylesheet" href="/font-swap.css">
</head><body><h1>Swapped external font</h1></body></html>"""

FONT_INLINE_BLOCKING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Blocking inline font</title><style>
@font-face { font-family: InlineBlocking; src: url('/inline.woff2') format('woff2'); }
</style></head><body><h1>Blocking inline font</h1></body></html>"""

FONT_UNFETCHABLE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Unreadable font stylesheet</title><link rel="stylesheet" href="/missing-fonts.css">
</head><body><h1>Unreadable font stylesheet</h1></body></html>"""

MOBILE_WIDE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>.container { width: 1200px; }</style>
</head><body><main class="container">A layout wider than a phone.</main></body></html>"""

MOBILE_STICKY = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>nav { position: sticky; top: 0; }</style>
</head><body><nav>Navigation</nav><main>A responsive layout.</main></body></html>"""

CSS_MIN = "body{color:#222}h1{font-size:2rem}a{color:#06c}"
CSS_FAT = "\n".join(f"  .rule-{n} {{ color : #222222 ;  margin : 0 auto ; }} "
                    f"/* rule number {n}, with a comment nobody needed */"
                    for n in range(120))
FONT_BLOCKING_CSS = ("@font-face { font-family: ExternalBlocking; "
                     "src: url('/external.woff2') format('woff2'); }")
FONT_SWAP_CSS = ("@font-face { font-family: ExternalSwap; "
                 "src: url('/external.woff2') format('woff2'); font-display: swap; }")

SITEMAP_GOOD = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>PLACEHOLDER/</loc><lastmod>2026-07-20</lastmod></url>'
                '<url><loc>PLACEHOLDER/about.html</loc><lastmod>2026-07-18</lastmod></url>'
                '<url><loc>PLACEHOLDER/guide.html</loc><lastmod>2026-07-11</lastmod></url>'
                '</urlset>')

SITEMAP_BAD = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<url><loc>PLACEHOLDER/</loc></url>'
               '<url><loc>PLACEHOLDER/gone</loc></url>'
               '<url><loc>PLACEHOLDER/also-gone</loc></url>'
               '<url><loc>PLACEHOLDER/unlinked-a.html</loc></url>'
               '<url><loc>PLACEHOLDER/unlinked-b.html</loc></url>'
               '<url><loc>http://insecure.invalid/x</loc></url>'
               '</urlset>')

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 900
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\0" * 600


def valid_png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\0" + b"\0\0\0\xff" * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def valid_ico(*sizes: tuple[int, int]) -> bytes:
    """A real ICO directory plus uncompressed 32-bit DIB payloads."""
    payloads = []
    for width, height in sizes:
        pixels = b"\0\0\0\xff" * width * height
        mask = b"\0" * ((((width + 31) // 32) * 4) * height)
        dib = struct.pack("<IIIHHIIIIII", 40, width, height * 2, 1, 32, 0,
                          len(pixels), 0, 0, 0, 0) + pixels + mask
        payloads.append(dib)
    offset = 6 + 16 * len(sizes)
    entries = []
    for (width, height), payload in zip(sizes, payloads, strict=True):
        entries.append(bytes((width if width < 256 else 0,
                              height if height < 256 else 0, 0, 0))
                       + struct.pack("<HHII", 1, 32, len(payload), offset))
        offset += len(payload)
    return struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries + payloads)


def valid_gif(width: int, height: int) -> bytes:
    return (b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\0\0"
            + b"\0\0\0\xff\xff\xff" + b";")


def valid_jpeg(width: int, height: int) -> bytes:
    components = b"\x01\x11\0\x02\x11\0\x03\x11\0"
    sof = struct.pack(">BHHB", 8, height, width, 3) + components
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def webp_chunk(kind: bytes, payload: bytes) -> bytes:
    chunk = kind + struct.pack("<I", len(payload)) + payload
    if len(payload) % 2:
        chunk += b"\0"
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def valid_webp(width: int, height: int, kind: str) -> bytes:
    if kind == "VP8X":
        payload = (b"\0\0\0\0" + (width - 1).to_bytes(3, "little")
                   + (height - 1).to_bytes(3, "little"))
        return webp_chunk(b"VP8X", payload)
    if kind == "VP8L":
        w, h = width - 1, height - 1
        packed = bytes((w & 0xFF, ((w >> 8) & 0x3F) | ((h & 0x03) << 6),
                        (h >> 2) & 0xFF, (h >> 10) & 0x0F))
        return webp_chunk(b"VP8L", b"\x2f" + packed)
    payload = b"\0\0\0\x9d\x01\x2a" + struct.pack("<HH", width, height)
    return webp_chunk(b"VP8 ", payload)


FAVICON_ICO = valid_ico((48, 48))

TEXT = {"Content-Type": "text/plain; charset=utf-8"}
XML = {"Content-Type": "application/xml"}
CSS = {"Content-Type": "text/css"}
JS = {"Content-Type": "application/javascript"}


def _fixture_html(*parts):
    with open(os.path.join(ROOT, "tests", "fixtures", *parts), encoding="utf-8") as fh:
        return fh.read()

GOOD_ROUTES = {
    "/": GOOD_PAGE,
    "/seo-audit.html": ("<!doctype html><html><head><title>seo audit guide</title>"
                        "</head><body><main><h1>seo audit guide</h1>"
                        "<p>A seo audit checks technical signals and content so a "
                        "team can prioritize improvements with reliable evidence."
                        "</p></main></body></html>"),
    "/seoul.html": ("<!doctype html><html><head><title>Seoul travel notes</title>"
                    "</head><body><main><h1>Seoul travel notes</h1>"
                    "<p>Seoul rewards patient travelers with neighborhood markets, "
                    "quiet paths, careful planning, and memorable meals each day."
                    "</p></main></body></html>"),
    "/about.html": ABOUT_PAGE,
    "/guide.html": GUIDE_PAGE,
    "/privacy.html": PRIVACY_PAGE,
    "/fixture/index.html": _fixture_html("good", "index.html"),
    "/fixture/about.html": _fixture_html("good", "about.html"),
    "/fixture/privacy.html": _fixture_html("good", "privacy.html"),
    "/fixture/blog/first-post.html": _fixture_html("good", "blog", "first-post.html"),
    "/intl.html": INTL_GOOD,
    "/intl-broken.html": INTL_BROKEN,
    "/de.html": INTL_GOOD,
    "/xx.html": INTL_GOOD,
    "/faq.html": FAQ_PAGE,
    "/schema-bad.html": BROKEN_SCHEMA_PAGE,
    "/video.html": VIDEO_PAGE,
    "/thin.html": BAD_PAGE,
    "/spammy.html": SPAMMY_ANCHORS,
    "/lazy.html": LAZY_HERO,
    "/font-external-blocking.html": FONT_EXTERNAL_BLOCKING,
    "/font-external-swap.html": FONT_EXTERNAL_SWAP,
    "/font-inline-blocking.html": FONT_INLINE_BLOCKING,
    "/font-unfetchable.html": FONT_UNFETCHABLE,
    "/mobile-wide.html": MOBILE_WIDE,
    "/mobile-sticky.html": MOBILE_STICKY,
    "/shop.html": ABOUT_PAGE,
    "/robots.txt": (200, TEXT, "User-agent: *\nAllow: /\nDisallow: /private/\n"
                               "User-agent: GPTBot\nAllow: /\n"
                               "Sitemap: PLACEHOLDER/sitemap.xml\n"),
    "/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6.txt": (200, TEXT, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"),
    "/llms.txt": (200, TEXT, "# Fixture Bakery\n\n> Sourdough guides and recipes.\n\n"
                             "## Guides\n- [Starter care](PLACEHOLDER/): feeding and "
                             "reviving a starter\n- [About](PLACEHOLDER/about.html): "
                             "who writes this\n\n## Optional\n"
                             "- [Privacy](PLACEHOLDER/privacy.html): the policy\n"),
    "/sitemap.xml": (200, XML, SITEMAP_GOOD),
    "/s.min.css": (200, CSS, CSS_MIN),
    "/s.css": (200, CSS, CSS_FAT),
    "/font-blocking.css": (200, CSS, FONT_BLOCKING_CSS),
    "/font-swap.css": (200, CSS, FONT_SWAP_CSS),
    "/s.js": (200, JS, "console.log(1);"),
    "/i/a.png": (200, {"Content-Type": "image/png"}, PNG),
    "/i/a.webp": (200, {"Content-Type": "image/webp"}, WEBP),
    "/i/logo.png": (200, {"Content-Type": "image/png"}, PNG),
    "/favicon.ico": (200, {"Content-Type": "image/x-icon"}, FAVICON_ICO),
    # Redirects, which a static file server cannot express and three items need.
    "/hop1": (301, {"Location": "PLACEHOLDER/hop2"}, ""),
    "/hop2": (302, {"Location": "PLACEHOLDER/hop3"}, ""),
    "/hop3": (301, {"Location": "PLACEHOLDER/"}, ""),
    "/loop1": (301, {"Location": "PLACEHOLDER/loop2"}, ""),
    "/loop2": (301, {"Location": "PLACEHOLDER/loop1"}, ""),
    # A loop that closes past the walk's own cap of ten hops. Written out rather than
    # generated because every other route here is: a reader comparing the served tree
    # with a report should be able to count the hops without running anything.
    "/deep1": (301, {"Location": "PLACEHOLDER/deep2"}, ""),
    "/deep2": (301, {"Location": "PLACEHOLDER/deep3"}, ""),
    "/deep3": (301, {"Location": "PLACEHOLDER/deep4"}, ""),
    "/deep4": (301, {"Location": "PLACEHOLDER/deep5"}, ""),
    "/deep5": (301, {"Location": "PLACEHOLDER/deep6"}, ""),
    "/deep6": (301, {"Location": "PLACEHOLDER/deep7"}, ""),
    "/deep7": (301, {"Location": "PLACEHOLDER/deep8"}, ""),
    "/deep8": (301, {"Location": "PLACEHOLDER/deep9"}, ""),
    "/deep9": (301, {"Location": "PLACEHOLDER/deep10"}, ""),
    "/deep10": (301, {"Location": "PLACEHOLDER/deep11"}, ""),
    "/deep11": (301, {"Location": "PLACEHOLDER/deep12"}, ""),
    "/deep12": (301, {"Location": "PLACEHOLDER/deep1"}, ""),
    # And a chain that ends on the last hop the walk is allowed to take: ten redirects
    # and a page. `total_hops` is 10 here too, which is the point — a repair that
    # withheld on the count rather than on running out of hops would withhold here, on
    # a chain it followed to the end.
    "/edge1": (301, {"Location": "PLACEHOLDER/edge2"}, ""),
    "/edge2": (301, {"Location": "PLACEHOLDER/edge3"}, ""),
    "/edge3": (301, {"Location": "PLACEHOLDER/edge4"}, ""),
    "/edge4": (301, {"Location": "PLACEHOLDER/edge5"}, ""),
    "/edge5": (301, {"Location": "PLACEHOLDER/edge6"}, ""),
    "/edge6": (301, {"Location": "PLACEHOLDER/edge7"}, ""),
    "/edge7": (301, {"Location": "PLACEHOLDER/edge8"}, ""),
    "/edge8": (301, {"Location": "PLACEHOLDER/edge9"}, ""),
    "/edge9": (301, {"Location": "PLACEHOLDER/edge10"}, ""),
    "/edge10": (301, {"Location": "PLACEHOLDER/"}, ""),
}

# No robots.txt, no llms.txt, a sitemap full of problems, and the bad page at the
# root. Origin-level absence is only expressible as a second origin.
BAD_ROUTES = {
    "/": BAD_PAGE,
    "/shop": BAD_PAGE,
    "/thin-indexable.html": ("<!doctype html><html lang=en><head>"
                             "<title>Stub</title></head><body><h1>Stub</h1>"
                             "<p>Twenty words of nothing much, published "
                             "with no thought and no reason for anyone to "
                             "read it at all.</p></body></html>"),
    "/unlinked-a.html": BAD_PAGE,
    "/unlinked-b.html": BAD_PAGE,
    "/i/a.png": (200, {"Content-Type": "image/png"}, PNG),
    "/s.css": (200, CSS, CSS_FAT),
    "/s.js": (200, JS, "console.log(1);"),
    "/sitemap.xml": (200, XML, SITEMAP_BAD),
}


# ---------------------------------------------------------------------------
# Running them
# ---------------------------------------------------------------------------

GOOD = BAD = RENDER_ARTIFACTS = None
OUT: dict = {}

# (key, script, argv template). `{good}` and `{bad}` are the two origins' roots.
# One entry per (script, page) pair the assertions below need — each runs once.
RUNS = [
    ("a11y", "a11y_seo_checker.py", ["{good}"]),
    ("a11y_bad", "a11y_seo_checker.py", ["{bad}"]),
    ("aicrawl", "ai_crawler_policy_matrix.py", ["{good}"]),
    ("aicrawl_bad", "ai_crawler_policy_matrix.py", ["{bad}"]),
    ("anchor", "anchor_text_audit.py", ["{good}"]),
    ("anchor_spam", "anchor_text_audit.py", ["{good}spammy.html"]),
    ("answers", "answer_block_scanner.py", ["{good}faq.html"]),
    ("answers_bad", "answer_block_scanner.py", ["{bad}"]),
    ("article", "article_seo.py", ["{good}", "--no-autocomplete"]),
    ("article_bad", "article_seo.py", ["{bad}", "--no-autocomplete"]),
    ("article_keyword_present", "article_seo.py",
     ["{good}", "--keyword", "sourdough starter", "--no-autocomplete"]),
    ("article_keyword_absent", "article_seo.py",
     ["{good}", "--keyword", "technical SEO", "--no-autocomplete"]),
    ("article_keyword_substring", "article_seo.py",
     ["{good}seoul.html", "--keyword", "seo", "--no-autocomplete"]),
    ("article_keyword_case", "article_seo.py",
     ["{good}seo-audit.html", "--keyword", "SEO Audit", "--no-autocomplete"]),
    ("article_unfetched", "article_seo.py",
     ["http://127.0.0.1:1/unreachable", "--keyword", "sourdough starter",
      "--no-autocomplete"]),
    ("article_fixture_index", "article_seo.py",
     ["{good}fixture/index.html", "--no-autocomplete"]),
    ("article_fixture_about", "article_seo.py",
     ["{good}fixture/about.html", "--no-autocomplete"]),
    ("article_fixture_privacy", "article_seo.py",
     ["{good}fixture/privacy.html", "--no-autocomplete"]),
    ("article_fixture_post", "article_seo.py",
     ["{good}fixture/blog/first-post.html", "--no-autocomplete"]),
    ("broken", "broken_links.py", ["{good}"]),
    ("broken_bad", "broken_links.py", ["{bad}"]),
    ("cache", "cache_compression_checker.py", ["{good}"]),
    ("citation", "citation_readiness.py", ["{good}"]),
    ("citation_bad", "citation_readiness.py", ["{bad}"]),
    ("collection", "collection_page_checker.py", ["{good}"]),
    ("collection_bad", "collection_page_checker.py", ["{bad}"]),
    ("chain", "critical_request_chain.py", ["{good}"]),
    ("chain_bad", "critical_request_chain.py", ["{bad}"]),
    ("cssmin", "css_minify_check.py", ["{good}"]),
    ("cssmin_bad", "css_minify_check.py", ["{bad}"]),
    ("dupes", "duplicate_content.py", ["{good}"]),
    ("dupes_bad", "duplicate_content.py", ["{bad}"]),
    ("eeat", "eeat_signal_checker.py", ["{good}"]),
    ("eeat_bad", "eeat_signal_checker.py", ["{bad}"]),
    ("entity", "entity_checker.py", ["{good}"]),
    ("extlinks", "external_link_quality.py", ["{good}"]),
    ("extlinks_bad", "external_link_quality.py", ["{bad}"]),
    ("favicon", "favicon_check.py", ["{good}"]),
    ("favicon_bad", "favicon_check.py", ["{bad}"]),
    ("facets", "faceted_nav_audit.py", ["{good}", "--from-page"]),
    ("facets_bad", "faceted_nav_audit.py", ["{bad}", "--from-page"]),
    ("fonts", "font_audit.py", ["{good}"]),
    ("fonts_external_blocking", "font_audit.py", ["{good}font-external-blocking.html"]),
    ("fonts_external_swap", "font_audit.py", ["{good}font-external-swap.html"]),
    ("fonts_inline_blocking", "font_audit.py", ["{good}font-inline-blocking.html"]),
    ("fonts_unfetchable", "font_audit.py", ["{good}font-unfetchable.html"]),
    ("fresh", "freshness_checker.py", ["{good}"]),
    ("fresh_bad", "freshness_checker.py", ["{bad}"]),
    ("ga4", "ga4_tag_checker.py", ["{good}"]),
    ("ga4_bad", "ga4_tag_checker.py", ["{bad}"]),
    ("hreflang", "hreflang_checker.py", ["{good}intl.html", "--verify-returns"]),
    ("hreflang_bad", "hreflang_checker.py", ["{good}intl-broken.html"]),
    ("hreflang_none", "hreflang_checker.py", ["{good}"]),
    ("images", "image_inventory.py", ["{good}"]),
    ("images_bad", "image_inventory.py", ["{bad}"]),
    ("images_lazy", "image_inventory.py", ["{good}lazy.html"]),
    ("intlinks", "internal_links.py", ["{good}"]),
    ("orphans", "orphan_pages_from_sitemap.py", ["{good}"]),
    ("orphans_bad", "orphan_pages_from_sitemap.py", ["{bad}"]),
    ("crawl", "site_crawl.py", ["{good}"]),
    ("crawl_bad", "site_crawl.py", ["{bad}"]),
    ("jsrender", "javascript_render_audit.py", ["{good}"]),
    ("jsrender_bad", "javascript_render_audit.py", ["{bad}"]),
    ("jsrender_match", "javascript_render_audit.py",
     ["{good}", "--rendered-json", "{rendered_match}"]),
    ("jsrender_diff", "javascript_render_audit.py",
     ["{good}", "--rendered-json", "{rendered_diff}"]),
    ("lcp", "lcp_subparts.py", ["{good}"]),
    ("profile", "link_profile.py", ["{good}"]),
    ("profile_bad", "link_profile.py", ["{bad}"]),
    ("indexnow", "indexnow_checker.py", ["{good}", "--key", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"]),
    ("indexnow_bad", "indexnow_checker.py", ["{bad}", "--key", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"]),
    ("llms", "llms_txt_checker.py", ["{good}"]),
    ("llms_bad", "llms_txt_checker.py", ["{bad}"]),
    ("mobile", "mobile_render_checker.py", ["{good}"]),
    ("mobile_wide", "mobile_render_checker.py", ["{good}mobile-wide.html"]),
    ("mobile_sticky", "mobile_render_checker.py", ["{good}mobile-sticky.html"]),
    ("mobile_bad", "mobile_render_checker.py", ["{bad}"]),
    ("redirect", "redirect_checker.py", ["{good}"]),
    ("redirect_hops", "redirect_checker.py", ["{good}hop1"]),
    ("redirect_loop", "redirect_checker.py", ["{good}loop1"]),
    ("redirect_deep_loop", "redirect_checker.py", ["{good}deep1"]),
    ("redirect_at_the_cap", "redirect_checker.py", ["{good}edge1"]),
    ("rich", "rich_results_guard.py", ["{good}"]),
    ("rich_bad", "rich_results_guard.py", ["{good}schema-bad.html"]),
    ("robots", "robots_checker.py", ["{good}"]),
    ("robots_bad", "robots_checker.py", ["{bad}"]),
    ("props", "schema_required_props.py", ["{good}faq.html"]),
    ("props_bad", "schema_required_props.py", ["{good}schema-bad.html"]),
    ("sitemap", "sitemap_checker.py", ["{good}"]),
    ("sitemap_bad", "sitemap_checker.py", ["{bad}"]),
    ("sitemap_urls", "sitemap_checker.py", ["{good}", "--fetch-urls", "--max-urls", "25"]),
    ("sitemap_urls_bad", "sitemap_checker.py", ["{bad}", "--fetch-urls", "--max-urls", "25"]),
    ("social", "social_meta.py", ["{good}"]),
    ("social_bad", "social_meta.py", ["{bad}"]),
    ("thirdparty", "third_party_script_audit.py", ["{good}"]),
    ("thirdparty_bad", "third_party_script_audit.py", ["{bad}"]),
    ("clusters", "topical_cluster_mapper.py", ["{good}"]),
    ("urls", "url_quality.py", ["{good}"]),
    ("urls_bad", "url_quality.py", ["{bad}shop?utm_source=a&SESSIONID=1&color=red&size=xl&sort=price"]),
    ("video", "video_schema_checker.py", ["{good}video.html"]),
    ("video_bad", "video_schema_checker.py", ["{good}"]),
    # `server_log_audit.py` reads files and makes no request, so these are the only
    # runs here with no origin in them. `{logs}` and `{artifacts}` are directories in
    # the checkout rather than temp copies: the logs carry fixed dates, because the
    # script refuses to report never-crawled URLs from a window under a week, and a
    # fixture generated relative to today would make that refusal fire or not
    # depending on which day the suite ran.
    ("log_good", "server_log_audit.py", ["{artifacts}good/access.log"]),
    ("log_waste", "server_log_audit.py", ["{artifacts}broken/access.log"]),
    ("log_common", "server_log_audit.py", ["{logs}common.log"]),
    ("log_json", "server_log_audit.py", ["{logs}nginx-json.log"]),
    ("log_gz", "server_log_audit.py", ["{logs}rotated.log.gz"]),
    ("log_junk", "server_log_audit.py", ["{logs}unparsable.log"]),
    ("log_absent", "server_log_audit.py", ["{logs}no-such-file.log"]),
]


def script_env() -> dict:
    """Loopback permitted, pacing off, every credential cleared.

    The credentials matter: a developer machine with a Search Console key must not
    make these tests do something a CI runner cannot, and a Safe Browsing key would
    turn an offline test into a paid API call.
    """
    env = dict(os.environ)
    env.update({"SEO_ALLOW_PRIVATE": "1", "SEO_MAX_RPS": "0", "PYTHONPATH": SCRIPTS})
    for key in ("GSC_CREDENTIALS_PATH", "GV_SA_KEY", "GOOGLE_SAFE_BROWSING_KEY",
                "PAGESPEED_API_KEY", "INDEXNOW_KEY"):
        env.pop(key, None)
    return env


def setUpModule():
    global GOOD, BAD, RENDER_ARTIFACTS
    GOOD, BAD = served(GOOD_ROUTES), served(BAD_ROUTES)
    for site in (GOOD, BAD):
        # `PLACEHOLDER_HOST` first: it is a substring of nothing, but the full
        # placeholder contains the scheme, so rewriting that one first would leave
        # `http://http://127.0.0.1:PORT/...` behind.
        site.rewrite("PLACEHOLDER_HOST", site.base.split("//", 1)[1])
        site.rewrite(PLACEHOLDER)
    GOOD.rewrite(harness.PLACEHOLDER_EXTERNAL, BAD.base)
    BAD.rewrite(harness.PLACEHOLDER_EXTERNAL, GOOD.base)
    RENDER_ARTIFACTS = tempfile.TemporaryDirectory()
    served_html = GOOD.routes["/"][2]
    rendered_match = os.path.join(RENDER_ARTIFACTS.name, "match.json")
    rendered_diff = os.path.join(RENDER_ARTIFACTS.name, "diff.json")
    with open(rendered_match, "w", encoding="utf-8") as handle:
        json.dump({"html": served_html}, handle)
    with open(rendered_diff, "w", encoding="utf-8") as handle:
        json.dump({"html": served_html.replace(
            "<title>Sourdough starter care: feeding, reviving and storing</title>",
            "<title>A rendered-only title</title>")}, handle)
    env = script_env()

    def run(spec):
        key, script, template = spec
        fixtures = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fixtures")
        argv = [a.replace("{good}", GOOD.url).replace("{bad}", BAD.url)
                .replace("{logs}", os.path.join(fixtures, "logs") + os.sep)
                .replace("{artifacts}", os.path.join(fixtures, "artifacts") + os.sep)
                .replace("{rendered_match}", rendered_match)
                .replace("{rendered_diff}", rendered_diff)
                for a in template]
        # `cwd` is deliberately not passed: it would put the child back on CPython's
        # `fork` path, which macOS kills outright once Network.framework has been
        # initialised in this process. See `harness.spawn`. Both paths below are
        # absolute, so nothing needed the working directory anyway.
        proc = harness.spawn(
            [sys.executable, os.path.join(SCRIPTS, script)] + argv + ["--json"],
            env=env, timeout=180)
        # A non-zero exit carrying JSON is an answer, not a crash. With `--json`
        # these scripts put a refusal in the payload and still exit 1 so a shell
        # notices, and treating that as a failure would hide exactly the cases worth
        # asserting: a log with no User-Agent field, a file that is not a log at all.
        if not proc.stdout.strip():
            return key, {"__failed__": f"exit {proc.returncode}: "
                                       f"{(proc.stderr or '')[-400:]}"}
        try:
            return key, json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return key, {"__failed__": f"not JSON: {exc}: {proc.stdout[:200]}"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, payload in pool.map(run, RUNS):
            OUT[key] = payload


def tearDownModule():
    for site in (GOOD, BAD):
        if site:
            site.stop()
    if RENDER_ARTIFACTS:
        RENDER_ARTIFACTS.cleanup()


def out(key: str) -> dict:
    payload = OUT[key]
    if "__failed__" in payload:
        raise AssertionError(f"{key}: {payload['__failed__']}")
    return payload


class EveryScriptRan(unittest.TestCase):
    """Before any verdict is asserted: did the scripts run at all?

    A script that exits non-zero produces `{}` from the runner's point of view, and an
    empty dict satisfies a surprising number of assertions — that combination once
    scored a host that does not resolve at 61/100. If this test fails, every failure
    below it is noise.
    """

    def test_no_script_crashed_or_returned_unusable_output(self):
        failed = {k: v["__failed__"] for k, v in OUT.items() if "__failed__" in v}
        self.assertEqual(failed, {}, "\n".join(f"  {k}: {v}"
                                               for k, v in failed.items()))

    def test_every_run_is_asserted_on_somewhere_in_this_file(self):
        """An unused run is a script nobody checked, hiding behind a green suite."""
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            source = f.read()
        unused = [key for key, _, _ in RUNS
                  if source.count(f'"{key}"') < 2]
        self.assertEqual(unused, [], f"runs nothing asserts on: {unused}")


class ServerLogs(unittest.TestCase):
    """CI-018, the one item no request could ever answer.

    Its evidence is in the past, so the tests that matter here are not about
    arithmetic. They are about the four ways this script could report a confident
    number about nothing: a log that records no crawler, a window too short for
    absence to mean anything, a file that is not a log, and a `304` counted as waste.
    """

    def test_a_clean_crawl_produces_no_findings(self):
        """The good fixture's log: every sitemap URL fetched, then revalidated.
        Nothing here should be reported, or the item accuses every healthy site."""
        d = out("log_good")
        self.assertEqual(d["error"], None)
        self.assertEqual([i for i in d["issues"]
                          if i["severity"] in ("high", "medium")], [])

    def test_revalidation_is_not_waste(self):
        """A `304` is the cheapest exchange there is: the crawler kept its copy and
        the server sent no body. Counting it against the site would penalise exactly
        what `cache_compression_checker.py` asks for two items away."""
        d = out("log_good")
        self.assertGreater(d["summary"]["not_modified_requests"], 0,
                           "the fixture stopped exercising 304s")
        self.assertEqual(d["summary"]["wasted_requests"], 0)
        self.assertEqual(d["summary"]["wasted_pct"], 0.0)

    def test_a_wasted_crawl_budget_is_reported_as_high(self):
        d = out("log_waste")
        types = {i["type"]: i["severity"] for i in d["issues"]}
        self.assertEqual(types.get("crawl_budget_wasted"), "high", types)
        self.assertEqual(types.get("server_errors_to_crawlers"), "high", types)
        self.assertIn("parameter_crawl", types)
        self.assertGreater(d["summary"]["wasted_pct"], 20)
        # And it says which URLs, because "44% wasted" is not an action.
        self.assertTrue(d["top_wasted"])
        self.assertTrue(all(row["status"] >= 400 for row in d["top_wasted"]))

    def test_ai_crawlers_are_counted_apart_from_crawl_budget(self):
        """An AI crawler pulling pages is not Google's crawl budget, and folding the
        two together would put two claims in one number."""
        d = out("log_waste")
        self.assertGreater(d["summary"]["ai_bot_requests"], 0)
        self.assertIn("GPTBot", d["bots"])
        self.assertEqual(d["bots"]["GPTBot"]["kind"], "ai")
        self.assertEqual(d["bots"]["Googlebot"]["kind"], "search")
        self.assertNotIn("GPTBot", [k for k, v in d["bots"].items()
                                    if v["kind"] == "search"])

    def test_a_log_with_no_user_agent_refuses_to_answer(self):
        """Common Log Format records no User-Agent, so every question here is
        unanswerable. "No crawler visited" and "this file cannot say which crawlers
        visited" are opposite findings, and reporting the second as the first is the
        one thing this tool exists to refuse."""
        d = out("log_common")
        self.assertIs(d["user_agent_recorded"], False)
        self.assertEqual(d["format"], "common")
        self.assertIn("no User-Agent", d["error"])
        # No zeros left lying around for a rule to read as a pass.
        self.assertEqual(d["summary"], {})
        self.assertEqual(d["bots"], {})

    def test_json_lines_are_read_with_nginx_key_names(self):
        d = out("log_json")
        self.assertEqual(d["format"], "json")
        self.assertEqual(d["error"], None)
        self.assertEqual(d["summary"]["search_bot_requests"], 63)
        # 1 July to 21 July is a 20-day span, not 21 days of entries.
        self.assertEqual(d["window"]["days"], 20)

    def test_a_rotated_log_reads_the_same_as_a_plain_one(self):
        """Not merely that gzip did not crash: the same bytes must give the same
        answer, because a log worth analysing has usually been rotated."""
        plain, rotated = out("log_good"), out("log_gz")
        for field in ("lines_parsed", "search", "by_status_class"):
            self.assertEqual(rotated[field], plain[field], field)
        self.assertEqual(rotated["summary"]["search_bot_requests"],
                         plain["summary"]["search_bot_requests"])

    def test_a_file_that_is_not_a_log_says_so(self):
        d = out("log_junk")
        self.assertIn("parsed as an access log", d["error"])
        self.assertEqual(d["summary"], {})

    def test_a_missing_file_says_so(self):
        d = out("log_absent")
        self.assertIn("no such log file", d["error"])

    def test_coverage_findings_need_an_inventory_and_are_absent_without_one(self):
        """`None`, not `[]`. An empty list reads as "we looked and found none", and
        these two questions cannot be asked of a log alone at all."""
        d = out("log_good")
        self.assertIsNone(d["never_crawled"])
        self.assertIsNone(d["crawled_not_offered"])

    def test_the_user_agent_is_reported_as_a_claim(self):
        """It is a lookup table over a string the client chose. Anything that reads
        this output has to know that, so the caveat is a field rather than a comment
        in the source."""
        self.assertIn("not verified", out("log_good")["bot_identity"])

    def test_no_robots_only_token_is_treated_as_a_user_agent(self):
        """`Google-Extended` and `Applebot-Extended` are robots.txt tokens that
        nothing ever sends. Matching them would define a crawler that cannot appear
        and then report zero visits from it forever."""
        import server_log_audit as sla
        for token in sla.NOT_USER_AGENTS:
            self.assertNotIn(token, sla.AI_BOTS)
            self.assertNotIn(token, sla.SEARCH_BOTS)
            # `applebot-extended` contains `applebot`, so substring matching read it as
            # Apple's search crawler and therefore search crawl budget. What matters
            # is not which bucket it lands in but that it is neither of the two that
            # decide anything.
            self.assertNotIn(sla.classify_agent(token)[0], ("search", "ai"),
                             f"{token} is counted as a real crawler")


class CrawlerAddressesAreConfirmed(unittest.TestCase):
    """CI-018's `bot_identity`, and the reason `--verify-bots` exists.

    Classification is a lookup over a string the client chose, so a scraper announcing
    itself as Googlebot was counted as Googlebot — and the direction of that error was
    always towards *over*-reporting the crawl, because nobody forges a User-Agent to
    look less important. Every test here hands in a resolver, so the suite stays
    offline: the whole feature is one network call, and the seam that lets it be tested
    is what makes adding it acceptable at all.
    """

    REAL = "66.249.66.1"
    FAKE = "203.0.113.9"

    UA = ("Mozilla/5.0 (compatible; Googlebot/2.1; "
          "+http://www.google.com/bot.html)")

    def _log(self) -> str:
        """Three requests from Google's address, five 404s from somewhere else — both
        announcing themselves as Googlebot. Built in a method rather than a class
        attribute because a comprehension in a class body cannot see the class's own
        names."""
        rows = [f'{self.REAL} - - [01/Jul/2026:00:0{i}:00 +0000] "GET /p{i} HTTP/1.1" '
                f'200 12 "-" "{self.UA}"' for i in range(3)]
        rows += [f'{self.FAKE} - - [01/Jul/2026:01:0{i}:00 +0000] "GET /admin{i} '
                 f'HTTP/1.1" 404 9 "-" "{self.UA}"' for i in range(5)]
        return "\n".join(rows) + "\n"

    class Resolver:
        """Reverse and forward answers written down, plus a record of the questions
        asked — so a test can assert that one address costs one lookup."""

        def __init__(self, reverse_map, forward_map=None, fail=()):
            self.reverse_map, self.fail = reverse_map, set(fail)
            self.forward_map = forward_map or {}
            self.asked = []

        def reverse(self, ip):
            self.asked.append(ip)
            if ip in self.fail:
                raise OSError("no PTR record")
            return self.reverse_map[ip]

        def forward(self, host):
            return self.forward_map.get(host, [])

    def _audit(self, resolver, budget=64):
        import tempfile

        import server_log_audit as sla
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as fh:
            fh.write(self._log())
            path = fh.name
        try:
            return sla.audit(path, checker=sla.AddressCheck(resolver, budget))
        finally:
            os.unlink(path)

    def _both_ways(self):
        return self.Resolver(
            {self.REAL: "crawl-66-249-66-1.googlebot.com",
             self.FAKE: "host9.cheap-vps.example.com"},
            {"crawl-66-249-66-1.googlebot.com": [self.REAL]})

    def test_a_forged_googlebot_leaves_the_crawl_budget_figures(self):
        """The finding underneath the feature. Five 404s from an address that is not
        Google used to be five 404s of Google's crawl budget wasted — the exact number
        the item reports, inflated by whoever pointed a scraper at the site."""
        result = self._audit(self._both_ways())
        self.assertEqual(result["address_checks"]["Googlebot"],
                         {"verified": 3, "forged": 5})
        self.assertEqual(result["bots"]["Googlebot"]["requests"], 3)
        self.assertEqual(
            result["bots"]["Googlebot (address not confirmed)"]["kind"], "other")
        self.assertEqual(result["summary"]["search_bot_requests"], 3)
        self.assertIn("forged_crawler", [i.get("type") for i in result["issues"]])

    def test_a_reverse_lookup_alone_is_not_enough(self):
        """The half of the rule that is easy to skip and does the work. A PTR record is
        controlled by whoever owns the address, so anyone with a rented block can name
        it `crawl-….googlebot.com`. Only the forward zone is Google's, so a name that
        does not resolve back to the address is forged."""
        lying = self.Resolver(
            {self.REAL: "crawl-66-249-66-1.googlebot.com",
             self.FAKE: "crawl-203-0-113-9.googlebot.com"},        # says the words
            {"crawl-66-249-66-1.googlebot.com": [self.REAL],
             "crawl-203-0-113-9.googlebot.com": ["8.8.8.8"]})      # resolves elsewhere
        result = self._audit(lying)
        self.assertEqual(result["address_checks"]["Googlebot"],
                         {"verified": 3, "forged": 5})

    def test_a_hostname_that_merely_ends_in_the_domain_is_forged(self):
        """`notgooglebot.com` ends with the string "googlebot.com". The suffix has to
        match on a label boundary — the same class of bug as the robots.txt token that
        was read as Apple's crawler by substring."""
        import server_log_audit as sla
        check = sla.AddressCheck(self.Resolver(
            {self.FAKE: "www.notgooglebot.com"},
            {"www.notgooglebot.com": [self.FAKE]}))
        self.assertEqual(check.status("Googlebot", self.FAKE), "forged")

    def test_a_resolver_that_is_down_does_not_make_every_crawler_an_impostor(self):
        """The failure this feature could easily have introduced. Reading "DNS did not
        answer" as "not Googlebot" would turn one outage on the auditing machine into a
        report telling a client their whole crawl is fraudulent — the same shape as a
        busy W3C validator becoming "your HTML has errors"."""
        result = self._audit(self.Resolver({}, fail=(self.REAL, self.FAKE)))
        self.assertEqual(result["address_checks"]["Googlebot"], {"unresolved": 8})
        self.assertEqual(result["bots"]["Googlebot"]["requests"], 8)
        self.assertNotIn("forged_crawler", [i.get("type") for i in result["issues"]])

    def test_one_address_costs_one_lookup_however_many_requests_it_made(self):
        """Eight requests, two addresses, two questions. A log is millions of lines and
        a crawler reuses its addresses; asking DNS per line would be the fan-out the
        response cache and the shared crawl exist to remove."""
        resolver = self._both_ways()
        self._audit(resolver)
        self.assertEqual(sorted(resolver.asked), sorted([self.REAL, self.FAKE]))

    def test_beyond_the_budget_an_address_is_unchecked_and_not_assumed(self):
        """A bounded feature has to say where it stopped. `not_checked` is handled like
        `unresolved`: the requests stay attributed to the crawler that claimed them,
        because a budget running out is not evidence about anybody."""
        result = self._audit(self._both_ways(), budget=1)
        self.assertEqual(result["address_checks"]["Googlebot"],
                         {"verified": 3, "not_checked": 5})
        self.assertEqual(result["bots"]["Googlebot"]["requests"], 8)

    def test_a_crawler_with_no_published_rule_is_left_as_a_claim(self):
        """DuckDuckBot, SeznamBot and PetalBot publish address ranges rather than a DNS
        convention. Inventing a rule for them would report every one of their visits as
        forged, which is worse than the claim it replaces."""
        import server_log_audit as sla
        check = sla.AddressCheck(self.Resolver({}))
        for name in ("DuckDuckBot", "SeznamBot", "PetalBot"):
            self.assertNotIn(name, sla.CRAWLER_DOMAINS)
            self.assertEqual(check.status(name, self.FAKE), "no_published_rule")

    def test_nothing_asks_dns_unless_the_operator_asked_for_it(self):
        """The default has to stay a file read, and the audit of the good fixture is
        the one that proves it: no checker, no `address_checks`, and the identity field
        still says the word "claim" out loud."""
        self.assertEqual(out("log_good")["address_checks"], {})
        self.assertIn("not verified", out("log_good")["bot_identity"])


# ---------------------------------------------------------------------------
# Crawling and indexing
# ---------------------------------------------------------------------------

class Robots(unittest.TestCase):
    """AR-151 `status`, AR-152 `user_agents`, CI-006 `sitemaps`."""

    def test_a_present_robots_txt_is_parsed_into_rules_and_a_sitemap(self):
        good = out("robots")
        self.assertEqual(verdict("AR-151", good), PASS)
        self.assertEqual(good["user_agents"]["*"]["disallow"], ["/private/"])
        self.assertEqual(verdict("AR-152", good), PASS)
        self.assertEqual(len(good["sitemaps"]), 1)
        self.assertEqual(verdict("CI-006", good), PASS)

    def test_an_absent_robots_txt_is_a_404_and_no_rules(self):
        """Two origins is what makes this testable at all: robots.txt belongs to an
        origin, so one document root cannot be both present and absent."""
        bad = out("robots_bad")
        self.assertEqual(bad["status"], 404)
        self.assertEqual(verdict("AR-151", bad), FAIL)
        self.assertEqual(bad["user_agents"], {})
        self.assertEqual(verdict("AR-152", bad), FAIL)
        self.assertEqual(verdict("CI-006", bad), FAIL)


class Sitemap(unittest.TestCase):
    """GO-136 `issues`, GO-138 `issues` (with --fetch-urls).

    CI-002 read `summary.urls >= 1` here until 0.26.0 — one URL present in a sitemap,
    asserted under *Ensure Important Content Is Indexed*. Submission is not indexation,
    and `summary.urls` is still counted and still reported; no item grades it, because
    no item in this registry is about how many URLs a sitemap lists.
    """

    def test_a_clean_sitemap_reports_its_urls_and_no_serious_issue(self):
        good = out("sitemap")
        self.assertEqual(good["summary"]["urls"], 3)
        self.assertEqual(verdict("GO-136", good), PASS)

    def test_a_probed_path_that_does_not_exist_is_not_an_issue(self):
        """The bug that made GO-136 and GO-138 fail on every clean site ever audited.

        Discovery tries `/sitemap.xml`, `/sitemap_index.xml` and `/sitemap-index.xml`.
        Those are alternatives, not a set, so a site with one sitemap produced two
        404s — and both were reported as errors. Only the declared one counts.
        """
        good = out("sitemap")
        self.assertEqual([i for i in good["issues"] if "404" in i.get("message", "")], [])
        self.assertGreaterEqual(good["summary"].get("probed_absent", 0), 1)

    def test_a_sitemap_of_dead_and_insecure_urls_is_reported(self):
        bad = out("sitemap_urls_bad")
        self.assertIn(verdict("GO-136", bad), (FAIL, WARN))
        self.assertEqual(verdict("GO-138", bad), FAIL)
        self.assertRegex(json.dumps(bad["issues"]), "(?i)404")

    def test_fetching_a_clean_sitemap_finds_nothing_to_report(self):
        """The other direction for `--fetch-urls`: the flag has to be capable of
        producing a pass, or GO-138 has merely moved from never-failing to
        never-passing."""
        self.assertEqual(verdict("GO-138", out("sitemap_urls")), PASS)

    def test_go_138_needs_the_urls_fetched_to_find_anything(self):
        """It could only ever pass without `--fetch-urls`, which the registry did not
        pass until 0.6.0: 404/redirect/noindex issues are produced by fetching the
        listed URLs, so a run that never fetched them had nothing to match.

        The first assertion below failed once on CI, on 3.10, and passed on a re-run
        of the same commit — 0 failures in 15 local runs of the full suite and of this
        module alone. Reading the script settles what it *cannot* be: every issue
        whose text can match `404|redirect|noindex` is inside the `if fetch_urls`
        branch, and this run does not pass the flag. So the payload is the whole
        question, and guessing at it twice has already cost more than printing it
        once. The message carries the issues verbatim rather than a boolean, because
        a diagnostic that names the wrong cause is worse than no diagnostic — which
        is the standing lesson of 0.15.0."""
        self.assertIn("--fetch-urls", ITEMS["GO-138"]["check"]["args"])
        unfetched = out("sitemap_bad")
        self.assertEqual(verdict("GO-138", unfetched), PASS,
                         "without fetching, the dead URLs are invisible; the issues "
                         "this run actually produced were "
                         + json.dumps(unfetched.get("issues"), ensure_ascii=False))
        self.assertEqual(verdict("GO-138", out("sitemap_urls_bad")), FAIL)


class Redirects(unittest.TestCase):
    """CI-014 `has_loop`, AR-150 `total_hops`.

    A static file server cannot express a redirect, which is why the contract pair
    exempts both items — `served()` can, so this is the only place either is
    exercised against a real 301.
    """

    def test_no_redirect_is_no_hops_and_no_loop(self):
        direct = out("redirect")
        self.assertEqual(direct["total_hops"], 0)
        self.assertEqual(verdict("AR-150", direct), PASS)
        self.assertEqual(verdict("CI-014", direct), PASS)

    def test_a_three_hop_chain_exceeds_the_budget(self):
        hops = out("redirect_hops")
        self.assertEqual(hops["total_hops"], 3)
        self.assertEqual(verdict("AR-150", hops), FAIL)

    def test_a_loop_is_reported_as_a_loop(self):
        loop = out("redirect_loop")
        self.assertIs(loop["has_loop"], True)
        self.assertEqual(verdict("CI-014", loop), WARN)

    def test_a_loop_past_the_cap_is_not_answered_as_no_loop(self):
        """The walk stops at ten hops; `/deep1` loops back at the twelfth.

        Before 0.81.0 this served `has_loop: False` and CI-014 — `high`, and the item
        whose whole subject is loops — reported PASS on a site that loops. The field is
        now absent, which the runner reads as NO_DATA. Absent and not `None`: `falsy`
        is satisfied by a null, so a null here would be the same false PASS with a
        different spelling.
        """
        deep = out("redirect_deep_loop")
        self.assertNotIn("has_loop", deep)
        self.assertIs(deep["truncated"], True)
        self.assertEqual(deep["total_hops"], 10)
        self.assertEqual(verdict("CI-014", deep), NO_DATA)

    def test_a_chain_that_ends_on_the_last_allowed_hop_is_still_answered(self):
        """Ten redirects and a page: the walk uses its last hop and the chain ends.

        `total_hops` is 10 here and 10 on the truncated walk as well, so a repair that
        withheld on the number would withhold on a chain it had followed to the end.
        The two are told apart by *why* the walk stopped, which is what `for ... else`
        answers and a count cannot.
        """
        edge = out("redirect_at_the_cap")
        self.assertEqual(edge["total_hops"], 10)
        self.assertIs(edge["truncated"], False)
        self.assertIs(edge["has_loop"], False)
        self.assertEqual(verdict("CI-014", edge), PASS)

    def test_a_walk_stopped_by_a_network_error_withholds_the_same_field(self):
        """No verdict rests on this: the runner replaces a result carrying `error`
        before any rule reads it. The artifact is read by people too, and on its own it
        would otherwise say `has_loop: False` about a chain nobody finished."""
        import redirect_checker
        import requests

        calls = []

        def refuse(url, **kwargs):
            calls.append(url)
            raise requests.exceptions.ConnectionError("refused")

        original = redirect_checker.safe_head
        redirect_checker.safe_head = refuse
        try:
            result = redirect_checker.check_redirects("https://example.test/")
        finally:
            redirect_checker.safe_head = original

        self.assertEqual(len(calls), 1)
        self.assertNotIn("has_loop", result)
        self.assertIs(result["truncated"], True)
        self.assertIn("refused", result["error"])

    def test_the_chain_is_still_too_long_when_the_walk_was_cut_short(self):
        """`total_hops` is a floor rather than a count once the walk stops, and a floor
        of ten is enough for AR-150: the site is still told its chain is too long. Both
        halves matter — withholding one verdict must not withhold the other."""
        deep = out("redirect_deep_loop")
        self.assertEqual(verdict("AR-150", deep), FAIL)
        self.assertTrue(any("whether it loops is unknown" in issue
                            for issue in deep["issues"]),
                        deep["issues"])


class UrlQuality(unittest.TestCase):
    """CI-012 `rows.0.score`, AR-147 `rows.0.param_count`, AR-155 `rows.0.flags`."""

    def test_a_clean_root_url_scores_and_carries_no_flags(self):
        good = out("urls")
        for item_id in ("CI-012", "AR-147", "AR-155"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_a_url_full_of_tracking_and_session_parameters_fails(self):
        bad = out("urls_bad")
        self.assertGreater(bad["rows"][0]["param_count"], 2)
        self.assertEqual(verdict("AR-147", bad), FAIL)
        self.assertNotEqual(bad["rows"][0]["flags"], [])
        self.assertEqual(verdict("AR-155", bad), FAIL)
        self.assertIn(verdict("CI-012", bad), (FAIL, WARN))


class Indexability(unittest.TestCase):
    """AI crawler alignment, GEO-003 `rows` with a `field`-scoped value map."""

    def test_a_documented_policy_aligns_and_an_undocumented_one_does_not(self):
        self.assertEqual(verdict("GEO-003", out("aicrawl")), PASS)
        self.assertEqual(verdict("GEO-003", out("aicrawl_bad")), FAIL)

    def test_the_verdict_comes_from_the_alignment_field_of_each_row(self):
        """`value_map` with `field` is the operator that replaced matching prose. It
        reads one named key per row, so a row growing a new key cannot change the
        verdict by accident."""
        rows = out("aicrawl")["rows"]
        self.assertTrue(rows)
        self.assertTrue(all("alignment" in row for row in rows))

    def test_every_ai_crawler_has_a_scope_and_both_reach_scopes_are_present(self):
        """The values may be renamed, but training and answer fetching must remain
        distinct populated groups rather than collapsing back into one token list."""
        import ai_crawler_policy_matrix as matrix

        self.assertTrue(matrix.AI_CRAWLERS)
        rows = {row["crawler"]: row for row in out("aicrawl")["rows"]}
        self.assertEqual(set(rows), set(matrix.AI_CRAWLERS))
        self.assertTrue(all(row.get("scope") for row in rows.values()))
        self.assertTrue(all(isinstance(row.get("honours_robots_txt"), bool)
                            for row in rows.values()))
        training = {crawler for crawler, row in rows.items()
                    if row["scope"] == matrix.MODEL_TRAINING_SCOPE}
        answers = {crawler for crawler, row in rows.items()
                   if row["scope"] == matrix.ANSWER_FEEDING_SCOPE}
        self.assertTrue(training)
        self.assertTrue(answers)

    def test_anthropic_and_perplexity_tokens_keep_their_distinct_scopes(self):
        import ai_crawler_policy_matrix as matrix

        expected = {
            "ClaudeBot": matrix.MODEL_TRAINING_SCOPE,
            "Claude-User": matrix.ANSWER_FEEDING_SCOPE,
            "Claude-SearchBot": matrix.ANSWER_FEEDING_SCOPE,
            "PerplexityBot": matrix.ANSWER_FEEDING_SCOPE,
            "Perplexity-User": matrix.ANSWER_FEEDING_SCOPE,
        }
        self.assertEqual({token: matrix.AI_CRAWLERS[token].scope for token in expected},
                         expected)

    def test_claudebot_collects_training_data_instead_of_feeding_answers(self):
        """A direct regression guard: reverting only ClaudeBot's old classification
        must fail even while both broad scope groups remain populated."""
        import ai_crawler_policy_matrix as matrix

        self.assertEqual(matrix.AI_CRAWLERS["ClaudeBot"].scope,
                         matrix.MODEL_TRAINING_SCOPE)
        self.assertNotEqual(matrix.AI_CRAWLERS["ClaudeBot"].scope,
                            matrix.ANSWER_FEEDING_SCOPE)

    def test_a_fetcher_that_ignores_robots_txt_is_flagged_in_the_output(self):
        import ai_crawler_policy_matrix as matrix

        rows = {row["crawler"]: row for row in out("aicrawl")["rows"]}
        user_fetch = rows["Perplexity-User"]
        self.assertIs(user_fetch["honours_robots_txt"], False)
        self.assertEqual(user_fetch["policy"], matrix.NOT_ENFORCED_POLICY)

    def test_applebot_is_included_because_it_can_feed_ai_answer_context(self):
        """Apple documents search crawling and AI-answer context under Applebot;
        Applebot-Extended is the separate training-use control."""
        import ai_crawler_policy_matrix as matrix

        self.assertEqual(matrix.AI_CRAWLERS["Applebot"].scope,
                         matrix.ANSWER_FEEDING_SCOPE)

    def test_google_extended_does_not_control_search_answers(self):
        """Google's robots.txt token controls Gemini training and grounding, while
        AI Overviews and AI Mode follow the ordinary controls for Search."""
        import ai_crawler_policy_matrix as matrix

        self.assertNotEqual(matrix.AI_CRAWLERS["Google-Extended"].scope,
                            matrix.ANSWER_FEEDING_SCOPE)


class LlmsTxt(unittest.TestCase):
    """GEO-001 `exists`, GEO-002 `quality.score`."""

    def test_a_structured_llms_txt_exists_and_scores(self):
        good = out("llms")
        self.assertIs(good["exists"], True)
        self.assertEqual(verdict("GEO-001", good), PASS)
        self.assertGreaterEqual(good["quality"]["score"], 60)
        self.assertEqual(verdict("GEO-002", good), PASS)

    def test_an_absent_llms_txt_is_absent_rather_than_undecided(self):
        """`exists: false` and not a missing key: the difference between "this site
        does not have one" and "we could not tell" is the whole coverage metric."""
        bad = out("llms_bad")
        self.assertIs(bad["exists"], False)
        self.assertEqual(verdict("GEO-001", bad), FAIL)
        self.assertEqual(verdict("GEO-002", bad), FAIL)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

class DuplicateAndThinContent(unittest.TestCase):
    """MS-022 `summary.duplicate_title_groups`, CN-041 `summary.exact_duplicate_groups`,
    CN-039 `summary.thin_pages`, MS-029 `summary.duplicate_description_groups`.

    MS-029 *Eliminate Duplicate Meta Descriptions* asserted the content-duplication
    count until 0.22 — a different requirement reading CN-041's verdict, so a site
    with one description on forty pages passed it as long as the pages differed. The
    crawl inventory has carried `meta_description` per page since 0.9.0 and nothing
    read it.
    """

    def test_four_distinct_pages_are_not_duplicates_of_each_other(self):
        good = out("dupes")
        self.assertEqual(good["exact_duplicates"], [])
        for item_id in ("MS-022", "MS-029", "CN-041"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_the_home_page_is_not_its_own_duplicate(self):
        """It was, on every site with a `href="/"` in its navigation — which is every
        site. The trailing slash was stripped unconditionally, so `example.com/` and
        `example.com` were crawled as two URLs, returned identical bytes, and the
        hash comparison reported the home page as **Critical** duplicate content.
        """
        good = out("dupes")
        home = [u for group in good["exact_duplicates"] for u in group.get("urls", [])
                if u.rstrip("/") == GOOD.base]
        self.assertEqual(home, [])

    def test_two_paths_serving_one_document_are_found(self):
        bad = out("dupes_bad")
        self.assertEqual(bad["summary"]["exact_duplicate_groups"], 1)
        self.assertEqual(bad["summary"]["duplicate_title_groups"], 1)
        for item_id in ("MS-022", "CN-041"):
            self.assertEqual(verdict(item_id, bad), FAIL, item_id)

    def test_missing_titles_are_not_duplicates_but_case_and_spacing_are(self):
        import duplicate_content
        pages = {
            "/absent-a": {"title": ""},
            "/absent-b": {"title": "   "},
            "/shared-a": {"title": "Summer Menu"},
            "/shared-b": {"title": " summer   menu "},
            "/unique": {"title": "Contact"},
        }
        groups = duplicate_content.duplicate_titles(pages)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["urls"], ["/shared-a", "/shared-b"])

    def test_ms_022_fails_on_shared_titles_and_not_on_shared_content(self):
        shared_title = {"summary": {"duplicate_title_groups": 1,
                                    "exact_duplicate_groups": 0}}
        shared_body = {"summary": {"duplicate_title_groups": 0,
                                   "exact_duplicate_groups": 1}}
        self.assertEqual(verdict("MS-022", shared_title), FAIL)
        self.assertEqual(verdict("CN-041", shared_title), PASS)
        self.assertEqual(verdict("MS-022", shared_body), PASS)
        self.assertEqual(verdict("CN-041", shared_body), FAIL)

    def test_ms_029_fails_on_shared_descriptions_and_not_on_shared_content(self):
        """The wiring, on a payload built for it rather than on a fixture.

        This origin's duplicate pages carry no description at all, so it can show
        CN-041 failing and cannot show MS-029 failing — and a site where exactly one
        of the two is wrong is the case that proves they are two items. The pair is
        built here instead: same content, different descriptions, then the reverse.

        The rest of the fixture is left alone on purpose. Adding pages to reach the
        crawl would mean adding them to `SITEMAP_BAD`, which is where this origin's
        pages are discovered — and the sitemap's contents are counted by four other
        items and the orphan arithmetic.
        """
        shared_desc = {"summary": {"exact_duplicate_groups": 0,
                                   "duplicate_description_groups": 1}}
        shared_body = {"summary": {"exact_duplicate_groups": 1,
                                   "duplicate_description_groups": 0}}
        self.assertEqual(verdict("MS-029", shared_desc), FAIL)
        self.assertEqual(verdict("CN-041", shared_desc), PASS)
        self.assertEqual(verdict("MS-029", shared_body), PASS)
        self.assertEqual(verdict("CN-041", shared_body), FAIL)

    def test_a_page_with_no_description_is_not_a_duplicate_of_another_with_none(self):
        """MS-028's finding, made once. Counting the absent ones here would report
        one defect under two items and drag a third — CN-041 — into a question about
        descriptions it does not ask."""
        import duplicate_content
        pages = {"/a": {"meta_description": ""}, "/b": {"meta_description": "   "},
                 "/c": {"meta_description": "One of a kind"}}
        self.assertEqual(duplicate_content.duplicate_descriptions(pages), [])

    def test_descriptions_differing_only_in_case_or_spacing_are_one_description(self):
        """Two of these are the same line to anyone reading a SERP, and treating
        them as distinct is exactly how a duplicate hides from this check."""
        import duplicate_content
        pages = {"/a": {"meta_description": "Fresh bread daily"},
                 "/b": {"meta_description": "fresh  bread   daily "},
                 "/c": {"meta_description": "Something else"}}
        groups = duplicate_content.duplicate_descriptions(pages)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["urls"], ["/a", "/b"])

    def test_an_indexable_thin_page_is_counted(self):
        thin = {p["url"]: p for p in out("dupes_bad").get("thin_content") or []}
        stub = f"{BAD.base}/thin-indexable.html"
        self.assertIn(stub, thin, f"the 20-word page was not called thin: {list(thin)}")
        self.assertLess(thin[stub]["word_count"], thin[stub]["threshold"])
        self.assertIn(verdict("CN-039", out("dupes_bad")), (FAIL, WARN))

    def test_a_noindex_page_is_not_a_thin_content_problem(self):
        """Deliberate, and worth pinning: a page kept out of the index is not
        competing for anything, so asking somebody to write 300 words for it is a fix
        list entry that should not exist."""
        thin = {p["url"] for p in out("dupes_bad").get("thin_content") or []}
        self.assertNotIn(BAD.url, thin)
        self.assertNotIn(f"{BAD.base}/shop", thin)

    def test_a_404_page_is_not_analysed_as_content(self):
        """It was. An error page is HTML, so a site with one dead internal link
        collected a `Critical` thin-content finding telling somebody to expand a page
        that does not exist — and it counted against CN-039. A broken link is
        `broken_links.py`'s finding, and it should be made once.
        """
        analysed = {p["url"] for p in out("dupes_bad").get("thin_content") or []}
        self.assertNotIn(f"{BAD.base}/gone", analysed)


class EeatSignals(unittest.TestCase):
    """CN-040 `signals.privacy_links`, CN-044 `signals.trust_links`,
    CN-057 `signals.authorship`, CN-068 `score`."""

    @staticmethod
    def _check_html(html):
        import eeat_signal_checker
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return eeat_signal_checker.check_eeat(path)
        finally:
            os.unlink(path)

    @staticmethod
    def _schema_script(document):
        return ('<script type="application/ld+json">' + json.dumps(document) +
                '</script>')

    def test_a_commenters_json_ld_author_does_not_pass_cn_057(self):
        publisher = self._schema_script({
            "@type": "WebSite",
            "publisher": {"@type": "Organization", "name": "Page Press"},
        })
        author = self._schema_script({
            "@type": "Article", "author": {"@type": "Person", "name": "D Petras"},
        })
        result = self._check_html(
            publisher + '<div itemprop="comment">' + author + '</div>')
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(result["signals"]["authorship"],
                         {"author": False, "publisher": True})
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_the_pages_own_json_ld_author_still_passes_cn_057(self):
        result = self._check_html(self._schema_script({
            "@type": "Article",
            "author": {"@type": "Person", "name": "M K"},
            "publisher": {"@type": "Organization", "name": "Page Press"},
        }))
        self.assertEqual(result["signals"]["authors"], ["M K"])
        self.assertEqual(result["signals"]["authorship"],
                         {"author": True, "publisher": True})
        self.assertEqual(verdict("CN-057", result), PASS)

    def test_only_the_pages_json_ld_author_survives_beside_a_commenters(self):
        own = self._schema_script({
            "@type": "Article",
            "author": {"@type": "Person", "name": "M K"},
            "publisher": {"@type": "Organization", "name": "Page Press"},
        })
        foreign = self._schema_script({
            "@type": "Article", "author": {"@type": "Person", "name": "D Petras"},
        })
        result = self._check_html(
            own + '<div itemprop="comment">' + foreign + '</div>')
        self.assertEqual(result["signals"]["authors"], ["M K"])

    # `itemref` puts elements from elsewhere in the document inside an item, so the
    # ancestor walk alone is not the boundary microdata describes. Measured before the
    # repair: the first page below passed CN-057 — `high` — on a byline that belongs
    # to a commenter, indistinguishably from a page whose author is its own.
    PUBLISHER_META = '<meta property="og:site_name" content="Page Press">'

    def test_a_commenters_byline_claimed_by_itemref_does_not_pass_cn_057(self):
        result = self._check_html(
            self.PUBLISHER_META
            + '<article itemscope itemtype="https://schema.org/Article"><h1>T</h1>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment"'
            ' itemref="c1"></div></article>'
            '<span id="c1" itemprop="author" class="author">D Petras</span>')
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_byline_inside_a_claimed_wrapper_is_claimed_too(self):
        """A claim reaches the referenced element's subtree, not only the element:
        microdata crawls a referenced element for properties the same way it crawls a
        descendant one."""
        result = self._check_html(
            self.PUBLISHER_META
            + '<article itemscope itemtype="https://schema.org/Article"><h1>T</h1>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment"'
            ' itemref="w1"></div></article>'
            '<div id="w1"><span itemprop="author" class="author">D Petras</span></div>')
        self.assertEqual(result["signals"]["authors"], [])

    def test_the_claim_is_followed_through_a_chain_of_itemrefs(self):
        """Two hops, and the second owner is foreign only because the first claimed it.

        The comment claims `w1`; `w1` is an item of its own and claims `w2`; the byline
        is in `w2`. Nothing about `w1` or `w2` is foreign by DOM nesting, so a rule
        that resolves one hop and stops credits the commenter to the page. Verified by
        installing exactly that rule.
        """
        result = self._check_html(
            self.PUBLISHER_META
            + '<article itemscope itemtype="https://schema.org/Article"><h1>T</h1>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment"'
            ' itemref="w1"></div></article>'
            '<div id="w1" itemscope itemtype="https://schema.org/Comment"'
            ' itemref="w2"></div>'
            '<div id="w2"><span class="author">D Petras</span></div>')
        self.assertEqual(result["signals"]["authors"], [])

    def test_an_itemref_without_itemscope_is_still_honoured(self):
        """The specification allows `itemref` only beside `itemscope`, and this reads
        it anyway. Deliberate, because the two ways of being wrong do not cost the
        same: honouring an invalid `itemref` can drop a credit the page deserved,
        ignoring one hands the page a commenter's. Only the second is a false pass."""
        result = self._check_html(
            self.PUBLISHER_META
            + '<div itemprop="comment" itemref="c1"></div>'
            '<span id="c1" class="author">D Petras</span>')
        self.assertEqual(result["signals"]["authors"], [])

    def test_a_byline_no_comment_claims_is_untouched_by_the_itemref_rule(self):
        """The other half, so the rule above is known to remove what a comment claims
        rather than everything on a page that happens to contain an `itemref`."""
        result = self._check_html(
            self.PUBLISHER_META
            + '<article itemscope itemtype="https://schema.org/Article"><h1>T</h1>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment"'
            ' itemref="c1"></div>'
            '<span id="mine" class="author">M Kazlauskiene</span></article>'
            '<span id="c1" class="author">D Petras</span>')
        self.assertEqual(result["signals"]["authors"], ["M Kazlauskiene"])
        self.assertEqual(verdict("CN-057", result), PASS)

    def test_the_claim_resolver_survives_the_markup_that_can_break_it(self):
        """`itemref` is author-written, so it arrives broken: ids that name nothing,
        two elements sharing one id, an item naming itself, a pair naming each other.
        The resolver walks to a fixed point, and a cycle is where that stops
        terminating if the loop is written to re-enter what it has already claimed.
        """
        untouched = [
            # names an id no element carries
            '<div itemprop="comment" itemref="nope"></div>',
            # a cycle between two elements, neither holding the byline
            '<div itemprop="comment" id="a" itemref="b"></div><div id="b" itemref="a">'
            '</div>',
            '<div itemprop="comment" id="s" itemref="s"></div>',
            '<div itemprop="comment" itemref=""></div>',
        ]
        for prefix in untouched:
            with self.subTest(markup=prefix):
                result = self._check_html(
                    self.PUBLISHER_META + prefix
                    + '<span class="author">M Kazlauskiene</span>')
                self.assertEqual(result["signals"]["authors"], ["M Kazlauskiene"])
        # Two elements share `x`, and the second one claims further. A claim reaches
        # "the element with that id", and invalid markup offers two; both are claimed,
        # which is the direction this rule is allowed to be wrong in.
        result = self._check_html(
            self.PUBLISHER_META
            + '<div itemprop="comment" itemref="x"></div><div id="x"></div>'
            '<div id="x" itemref="y"></div>'
            '<div id="y"><span class="author">D Petras</span></div>')
        self.assertEqual(result["signals"]["authors"], [])

    def test_a_byline_two_items_both_claim_stays_withheld(self):
        """The reverse direction, and it is a decision rather than an oversight.

        The byline is nested in the comment *and* claimed by the article through
        `itemref`, so microdata declares the same person for both items and nothing
        says which was meant. This withholds — the answer `page_nodes` gives an
        ambiguous graph — rather than preferring the outer claim, which would let any
        `itemscope` on a page rescue a commenter by naming their id.
        """
        result = self._check_html(
            self.PUBLISHER_META
            + '<article itemscope itemtype="https://schema.org/Article" itemref="b1">'
            '<h1>T</h1>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment">'
            '<span id="b1" itemprop="author" class="author">M Kazlauskiene</span>'
            '</div></article>')
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_commenters_json_ld_publisher_is_not_the_pages(self):
        publisher = self._schema_script({
            "@type": "Article",
            "publisher": {"@type": "Organization", "name": "Commenter Blog"},
        })
        result = self._check_html(
            '<div itemprop="comment">' + publisher + '</div>')
        self.assertEqual(result["signals"]["publishers"], [])
        self.assertFalse(result["signals"]["authorship"]["publisher"])

    def test_a_commenters_publisher_meta_is_not_the_pages(self):
        result = self._check_html(
            '<div itemprop="comment"><meta property="og:site_name" '
            'content="Commenter Blog"></div>')
        self.assertEqual(result["signals"]["publishers"], [])
        self.assertFalse(result["signals"]["authorship"]["publisher"])

    def test_the_pages_own_publisher_meta_in_head_still_counts(self):
        result = self._check_html(
            '<html><head><meta property="og:site_name" content="Page Press">'
            '</head><body></body></html>')
        self.assertEqual(result["signals"]["publishers"], ["Page Press"])
        self.assertTrue(result["signals"]["authorship"]["publisher"])

    def test_json_ld_under_every_review_credit_spelling_is_excluded(self):
        publisher = self._schema_script({
            "@type": "WebSite",
            "publisher": {"@type": "Organization", "name": "Page Press"},
        })
        author = self._schema_script({
            "@type": "Article", "author": {"@type": "Person", "name": "D Petras"},
        })
        for key in ("review", "itemReviewed"):
            with self.subTest(key=key):
                result = self._check_html(
                    publisher + f'<div itemprop="{key}">' + author + '</div>')
                self.assertEqual(result["signals"]["authors"], [])
                self.assertEqual(verdict("CN-057", result), FAIL)

    @staticmethod
    def _twin_html(lang):
        words = {
            "en": {
                "credential": "Certified specialist.",
                "experience": "We tested the oven. Our testing measured every loaf.",
                "links": (
                    ("/editorial-standards", "Editorial standards"),
                    ("/about", "About us"),
                    ("/contact", "Contact"),
                    ("/privacy-terms", "Privacy policy and terms"),
                ),
            },
            "lt": {
                "credential": "Sertifikuotas specialistas.",
                "experience": "Mes išbandėme orkaitę. Mūsų bandymai apėmė kiekvieną kepalą.",
                "links": (
                    ("/redakciniai-standartai", "Redakciniai standartai"),
                    ("/apie", "Apie mus"),
                    ("/kontaktai", "Kontaktai"),
                    ("/privatumo-politika-ir-salygos", "Privatumo politika ir sąlygos"),
                ),
            },
        }[lang]
        links = "".join(f'<a href="{href}">{text}</a>' for href, text in words["links"])
        return f'''<!doctype html><html lang="{lang}"><head>
        <script type="application/ld+json">{{"@type":"Article","author":
        {{"@type":"Person","name":"A Baker"}},"publisher":
        {{"@type":"Organization","name":"Fixture Bakery"}}}}</script>
        </head><body><span name="author">A Baker</span>
        <p>{words["credential"]} {words["experience"]}</p>{links}
        <a href="https://source-one.example/study">Study one</a>
        <a href="https://source-two.example/data">Study two</a>
        </body></html>'''

    @staticmethod
    def _locale_snapshot(result):
        signals = result["signals"]
        counts = tuple(len(signals[key]) for key in (
            "credential_markers", "first_hand_experience_markers", "policy_links",
            "trust_links", "privacy_links",
        ))
        verdicts = tuple(verdict(item_id, result)
                         for item_id in ("CN-040", "CN-044", "CN-057", "CN-068"))
        return counts, verdicts

    def test_links_carry_the_shared_foreign_credit_answer(self):
        from seo_common import parse_html

        links = parse_html(
            '<a href="/own">Own</a>'
            '<div itemprop="comment"><a href="/foreign">Foreign</a></div>',
            "",
        )["links"]
        self.assertEqual(links, [
            {"href": "/own", "text": "Own", "rel": [], "foreign_credit": False},
            {"href": "/foreign", "text": "Foreign", "rel": [],
             "foreign_credit": True},
        ])

    def test_link_flags_follow_the_shared_boundary_exactly(self):
        from seo_common import parse_html

        links = parse_html(
            '<div itemprop="commentary"><a href="/own">Own</a></div>'
            '<div itemprop="mainEntity comment"><a href="/foreign">Foreign</a></div>',
            "",
        )["links"]
        self.assertEqual([link["foreign_credit"] for link in links], [False, True])

    def test_the_shared_link_list_keeps_a_commenters_link(self):
        from seo_common import parse_html

        parsed = parse_html(
            '<div itemprop="comment"><a href="/comment-link">Comment link</a></div>',
            "",
        )
        self.assertEqual(len(parsed["links"]), 1)

    def test_only_a_commenters_privacy_about_and_email_give_no_page_credit(self):
        result = self._check_html(
            '<p class="author">A Baker</p><div itemprop="comment">'
            '<a href="/privacy">Privacy</a><a href="/about">About</a>'
            '<a href="mailto:commenter@example.net">Email</a></div>')
        self.assertEqual(result["signals"]["privacy_links"], [])
        self.assertEqual(result["signals"]["trust_links"], [])
        self.assertEqual(result["score"], 20)
        self.assertEqual(verdict("CN-040", result), FAIL)
        self.assertEqual(verdict("CN-044", result), FAIL)

    def test_the_pages_own_privacy_contact_and_email_keep_their_credit(self):
        result = self._check_html(
            '<p class="author">A Baker</p><footer>'
            '<a href="/privacy-policy">Privacy</a><a href="/contact">Contact</a>'
            '<a href="mailto:hello@example.net">Email</a></footer>')
        self.assertEqual(
            [link["href"] for link in result["signals"]["privacy_links"]],
            ["/privacy-policy"],
        )
        self.assertEqual(len(result["signals"]["trust_links"]), 3)
        self.assertEqual(result["score"], 35)
        self.assertEqual(verdict("CN-040", result), PASS)
        self.assertEqual(verdict("CN-044", result), PASS)

    def test_only_the_pages_links_survive_beside_a_commenters(self):
        result = self._check_html(
            '<p class="author">A Baker</p><footer>'
            '<a href="/privacy-policy">Privacy</a><a href="/contact">Contact</a>'
            '<a href="mailto:hello@example.net">Email</a></footer>'
            '<div itemprop="comment"><a href="/privacy">Privacy</a>'
            '<a href="/about">About</a>'
            '<a href="mailto:commenter@example.net">Email</a></div>')
        self.assertEqual(
            [link["href"] for link in result["signals"]["privacy_links"]],
            ["/privacy-policy"],
        )
        self.assertEqual(
            [link["href"] for link in result["signals"]["trust_links"]],
            ["/privacy-policy", "/contact", "mailto:hello@example.net"],
        )

    def test_a_page_with_neither_kind_of_link_stays_unchanged(self):
        result = self._check_html('<p class="author">A Baker</p>')
        self.assertEqual(result["signals"]["privacy_links"], [])
        self.assertEqual(result["signals"]["trust_links"], [])
        self.assertEqual(result["score"], 20)
        self.assertEqual(verdict("CN-040", result), FAIL)
        self.assertEqual(verdict("CN-044", result), FAIL)

    def test_a_foreign_link_matched_only_by_text_is_removed(self):
        result = self._check_html(
            '<div itemprop="comment"><a href="/x">Privacy Policy</a></div>')
        self.assertEqual(result["signals"]["privacy_links"], [])

    def test_same_url_survives_only_for_the_pages_own_link(self):
        result = self._check_html(
            '<footer><a href="/privacy">Privacy</a></footer>'
            '<div itemprop="comment"><a href="/privacy">Privacy</a></div>')
        self.assertEqual(
            [link["href"] for link in result["signals"]["privacy_links"]],
            ["/privacy"],
        )
        self.assertEqual(len(result["signals"]["trust_links"]), 1)

    def test_a_commenters_outbound_links_are_not_the_pages_citations(self):
        links = "".join(
            f'<a href="https://source-{index}.example/study">Study {index}</a>'
            for index in range(5)
        )
        result = self._check_html(
            f'<p class="author">A Baker</p><div itemprop="comment">{links}</div>')
        self.assertEqual(result["signals"]["external_citations"], 0)
        self.assertEqual(result["score"], 20)

    def test_a_commenters_email_is_not_the_pages_contact_route(self):
        result = self._check_html(
            '<footer><a href="mailto:hello@example.net">Page email</a></footer>'
            '<div itemprop="comment">'
            '<a href="mailto:commenter@example.net">Commenter email</a></div>')
        self.assertEqual(
            [link["href"] for link in result["signals"]["trust_links"]],
            ["mailto:hello@example.net"],
        )

    def test_a_commenters_editorial_standards_link_is_not_the_pages_policy(self):
        result = self._check_html(
            '<p class="author">A Baker</p><div itemprop="comment">'
            '<a href="/editorial-standards">Editorial standards</a></div>')
        self.assertEqual(result["signals"]["policy_links"], [])
        self.assertEqual(result["score"], 20)

    def test_an_faq_answer_loses_its_own_links_under_the_shared_boundary(self):
        # This is the current answer, not the right one: KNOWN-ISSUES.md records the
        # open question about the foreign-credit key set's width.
        result = self._check_html(
            '<main itemscope itemtype="https://schema.org/FAQPage">'
            '<p class="author">A Baker</p><div itemprop="acceptedAnswer">'
            '<a href="/privacy">Privacy</a><a href="/contact">Contact</a>'
            '</div></main>')
        self.assertEqual(result["signals"]["privacy_links"], [])
        self.assertEqual(result["signals"]["trust_links"], [])
        self.assertEqual(result["score"], 20)

    def test_comment_links_stay_in_shared_and_anchor_text_lists(self):
        import anchor_text_audit
        from seo_common import parse_html

        parsed = parse_html(
            '<div itemprop="comment"><a href="/bread">Best bread</a></div>',
            "https://example.test/page",
        )
        self.assertEqual(len(parsed["links"]), 1)
        self.assertTrue(parsed["links"][0]["foreign_credit"])
        projected = anchor_text_audit.anchors_from_inventory({"pages": {
            "https://example.test/page": {
                "status": 200,
                "html": "present",
                "links": [{"internal": True, "target": "https://example.test/bread",
                           "anchor": "Best bread", "rel": [], "nofollow": False}],
            },
        }})
        self.assertEqual(
            projected["links"],
            [{"source": "https://example.test/page",
              "target": "https://example.test/bread", "anchor": "Best bread",
              "rel": [], "nofollow": False}],
        )

    def test_a_microdata_comment_byline_is_not_the_pages_author(self):
        result = self._check_html(
            '<div itemprop="comment"><span class="author">D Petras</span></div>')
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(result["signals"]["authorship"],
                         {"author": False, "publisher": False})

    def test_the_pages_byline_survives_beside_a_commenters(self):
        result = self._check_html(
            '<p class="author">M Kazlauskiene</p>'
            '<div itemprop="comment"><span class="author">D Petras</span></div>')
        self.assertEqual(result["signals"]["authors"], ["M Kazlauskiene"])

    def test_english_and_lithuanian_twins_get_the_same_signals_and_verdicts(self):
        english = self._check_html(self._twin_html("en"))
        lithuanian = self._check_html(self._twin_html("lt"))
        expected = ((2, 2, 1, 3, 1), (PASS, PASS, PASS, PASS))
        self.assertEqual((self._locale_snapshot(english), self._locale_snapshot(lithuanian)),
                         (expected, expected))

    def test_lithuanian_and_russian_privacy_labels_are_recognised(self):
        pages = {
            "lt": '<a href="/legal">Privatumo politika</a>',
            "ru": '<a href="/legal">Политика конфиденциальности</a>',
        }
        for lang, link in pages.items():
            with self.subTest(lang=lang):
                result = self._check_html(f'<html lang="{lang}"><body>{link}</body></html>')
                self.assertEqual(len(result["signals"]["privacy_links"]), 1)

    def test_a_page_gets_no_cross_language_privacy_credit(self):
        result = self._check_html('''<html lang="en"><body>
        <a href="/legal">Privatumo politika</a></body></html>''')
        self.assertEqual(result["signals"]["privacy_links"], [])

    def test_an_undeclared_lithuanian_page_falls_back_to_the_old_english_score(self):
        html = self._twin_html("lt").replace(' lang="lt"', "", 1)
        result = self._check_html(html)
        self.assertEqual(result["score"], 24)

    def test_declared_language_precedence_and_meta_fallbacks(self):
        pages = (
            ('<html lang="lt"><head><meta http-equiv="content-language" content="ru">'
             '<meta property="og:locale" content="en_US"></head>', "lt"),
            ('<html><head><meta http-equiv="content-language" content="lt-LT">'
             '<meta property="og:locale" content="ru_RU"></head>', "lt"),
            ('<html><head><meta property="og:locale" content="ru_RU"></head>', "ru"),
        )
        for head, expected in pages:
            with self.subTest(expected=expected):
                result = self._check_html(
                    f'{head}<body><a href="/legal">Privatumo politika</a></body></html>')
                self.assertEqual(result["lang"], expected)

    def test_the_english_literal_expansions_keep_exact_marker_counts(self):
        twin = self._check_html(self._twin_html("en"))
        self.assertEqual((len(twin["signals"]["credential_markers"]),
                          len(twin["signals"]["first_hand_experience_markers"])),
                         (2, 2))

        credentials = (
            "phd", "md", "m.d", "doctor", "professor", "certified", "licensed",
            "editor", "reviewed by", "fact-checked", "fact checked",
            "year of experience", "years of experience", "award-winning",
            "award winning", "expert", "specialist",
        )
        first_hand = (
            "we tested", "our testing", "hands-on", "hands on", "first-hand",
            "first hand", "case study", "in our experience", "we measured",
            "we reviewed", "original research", "surveyed",
        )
        institutional = (
            "editorial", "review policy", "fact-check", "fact check", "correction",
            "corrections", "ethics", "about", "contact", "privacy", "terms", "team",
            "author", "authors", "data protection", "gdpr", "cookie policy",
            "cookie notice",
        )
        exhaustive = self._check_html(
            '<html lang="en"><body><p>'
            + ". ".join(credentials + first_hand + institutional)
            + ".</p></body></html>")
        self.assertEqual(
            (len(exhaustive["signals"]["credential_markers"]),
             len(exhaustive["signals"]["first_hand_experience_markers"])),
            (17, 12))

    def test_inflected_lithuanian_and_russian_credential_stems_match(self):
        pages = {
            "lt": "Parengta sertifikuoto kepėjo",
            "ru": "Написано сертифицированным врачом",
        }
        for lang, prose in pages.items():
            with self.subTest(lang=lang):
                result = self._check_html(
                    f'<html lang="{lang}"><body><p>{prose}</p></body></html>')
                self.assertEqual(len(result["signals"]["credential_markers"]), 1)

    def test_russian_whole_word_does_not_behave_like_a_stem(self):
        result = self._check_html('''<html lang="ru"><body>
        <a href="/article">Как правильно выбрать</a></body></html>''')
        self.assertEqual(result["signals"]["trust_links"], [])

    def test_href_anchoring_is_carried_by_each_literal_fragment(self):
        result = self._check_html('''<html lang="en"><body>
        <a href="/blog/all-about-bread">Bread notes</a>
        <a href="/our-privacy-thoughts">Legal thoughts</a>
        <a href="/datenschutz">Legal notice</a>
        <a href="/blog/editorial-thoughts">Standards</a>
        </body></html>''')
        self.assertEqual(result["signals"]["trust_links"], [])
        self.assertEqual([link["href"] for link in result["signals"]["privacy_links"]],
                         ["/datenschutz"])
        self.assertEqual([link["href"] for link in result["signals"]["policy_links"]],
                         ["/blog/editorial-thoughts"])

    def test_an_lt_page_reports_both_vocabularies_it_used(self):
        result = self._check_html(self._twin_html("lt"))
        self.assertEqual(result["matched_locales"], ["en", "lt"])

    def test_the_three_signal_families_are_found_separately(self):
        """Separately is the point. CN-040 is about a *privacy* policy and used to read
        `policy_links`, which this script fills with editorial policy — fact-checking,
        corrections, ethics. A site with a normal privacy policy failed unless it also
        published editorial standards, and a site with an ethics page and no privacy
        policy passed. The check answered a different question in both directions.
        """
        good = out("eeat")
        self.assertTrue(good["signals"]["privacy_links"])
        self.assertTrue(good["signals"]["trust_links"])
        self.assertTrue(good["signals"]["authors"])
        self.assertEqual(good["signals"]["publishers"], ["Fixture Bakery"])
        self.assertEqual(good["signals"]["authorship"],
                         {"author": True, "publisher": True})
        self.assertIsNot(good["signals"]["privacy_links"],
                         good["signals"].get("policy_links"))
        for item_id in ("CN-040", "CN-044", "CN-057"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_a_page_with_no_author_policy_or_contact_fails_all_three(self):
        bad = out("eeat_bad")
        for item_id in ("CN-040", "CN-044", "CN-057"):
            self.assertEqual(verdict(item_id, bad), FAIL, item_id)

    def test_the_score_separates_the_two_pages(self):
        """Asserted as a direction rather than a threshold, and the direction is what
        the item rests on: a fixture page cannot earn the top of this score without
        things it has no business inventing — an author page with a real byline
        history, an organisation with verifiable sameAs targets. The floor moved to 35
        in 0.87.0 and this assertion did not, because it never named the floor."""
        self.assertGreater(out("eeat")["score"], out("eeat_bad")["score"] + 30)

    def test_the_floor_is_the_sum_of_the_page_type_neutral_components(self):
        """35 = authors 20 + trust 15, and the test fails if either weight moves.

        The floor is not a round number: it is what a page of any type can carry out
        of this script's six components. Credentials (20), first-hand experience (20)
        and external citations (10) are article signals — a privacy policy has no
        business carrying them — and the editorial-standards component (15) is 0 on
        every page of every tree this repository serves. If a weight changes, the
        derivation changes with it and the floor has to be re-read rather than kept.
        """
        with open(os.path.join(SCRIPTS, "eeat_signal_checker.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("score += 20 if authors else 0", source)
        self.assertIn("score += 15 if trust_links else 0", source)
        self.assertEqual(ITEMS["CN-068"]["check"]["assert"]["gte"], 20 + 15)

    def test_a_publisher_only_page_fails_cn_057(self):
        """This fails if a publisher re-enters authors or CN-057 reads only one half."""
        result = self._check_html("""<!doctype html><html><head>
        <script type="application/ld+json">{"@type":"Article","publisher":
        {"@type":"Organization","name":"Acme"}}</script></head><body></body></html>""")
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(result["signals"]["publishers"], ["Acme"])
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_only_exact_byline_class_tokens_name_authors(self):
        """This fails if substring matching returns or `_` stops reading as `-`."""
        result = self._check_html("""<!doctype html><html><body>
        <div class="author-grid"><span>Bread</span><span>Cake</span></div>
        <p class="byline">A Baker</p><p class="article_author">B Baker</p>
        </body></html>""")
        self.assertEqual(result["signals"]["authors"], ["A Baker", "B Baker"])

    def test_the_shared_byline_helper_normalizes_underscores_without_substrings(self):
        """This fails if `_` stops reading as `-` or substring matching returns."""
        from seo_common import has_byline_class, parse_html
        soup = parse_html("""<div id="layout" class="author-grid"></div>
        <p id="credit" class="article_author">A Baker</p>""")["soup"]
        self.assertTrue(has_byline_class(soup.find(id="credit")))
        self.assertFalse(has_byline_class(soup.find(id="layout")))

    def test_an_organisation_author_is_not_also_a_publisher(self):
        """This fails if one credited organisation can satisfy both CN-057 halves."""
        result = self._check_html("""<!doctype html><html><head>
        <script type="application/ld+json">{"@type":"Article","author":
        {"@type":"Organization","name":"Acme"}}</script></head><body></body></html>""")
        self.assertEqual(result["signals"]["authors"], ["Acme"])
        self.assertEqual(result["signals"]["publishers"], [])
        self.assertEqual(result["signals"]["authorship"],
                         {"author": True, "publisher": False})
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_phone_and_email_links_are_language_neutral_contact_routes(self):
        import tempfile
        import eeat_signal_checker
        html = """<!doctype html><html lang="lt"><body>
        <a href="tel:+37060000000">+370 600 00000</a>
        <a href="mailto:labas@example.lt">Rašykite mums</a>
        </body></html>"""
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            result = eeat_signal_checker.check_eeat(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(result["signals"]["trust_links"]), 2)
        self.assertEqual(verdict("CN-044", result), PASS)

    # --- 0.66.0: the author set is the page's own credits -------------------
    #
    # `_schema_values` walked the whole JSON-LD graph, so a credit written on any node
    # anywhere was read as a credit of the page. Four shapes passed CN-057 — *Show
    # Author and Publisher Clearly* — with no author at all: a `reviewedBy`
    # organisation, a customer review, a comment, and an answer. Every test below names
    # the input that isolates it, because the whole family fails to the same repair and
    # a test that shares an input with its neighbour cannot say which half broke.

    @staticmethod
    def _person(name="A Baker"):
        return {"@type": "Person", "name": name}

    @staticmethod
    def _org(name="Fixture Bakery"):
        return {"@type": "Organization", "name": name}

    def _ld(self, document, body="<p>Bread.</p>"):
        return self._check_html(
            '<!doctype html><html lang="en"><head>'
            '<script type="application/ld+json">' + json.dumps(document) +
            '</script></head><body>' + body + '</body></html>')

    def test_a_reviewer_is_not_an_author(self):
        """A review board is not the author, and this page names nobody else."""
        result = self._ld({"@type": "Article",
                           "reviewedBy": self._person("Dr Rye")})
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(result["signals"]["reviewers"], ["Dr Rye"])
        self.assertEqual(result["signals"]["authorship"],
                         {"author": False, "publisher": False})
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_publisher_and_a_reviewer_do_not_add_up_to_an_author(self):
        """The collapse this release closes. 0.51.0 stopped a publisher standing in
        for an author; nothing stopped a reviewer doing it, so a page naming a
        publisher and a review board and no human passed a `high` item asking for two
        parties."""
        result = self._ld({"@type": "Article",
                           "publisher": self._org(),
                           "reviewedBy": self._org("Review Board")})
        self.assertEqual(result["signals"]["authorship"],
                         {"author": False, "publisher": True})
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_reviewer_organisation_is_not_publisher_evidence(self):
        """This fails if `_credited_nodes` stops holding `reviewedBy` — a third-party
        review board would then be reported as the site's own identity.

        The test above cannot catch that: its publisher list is already non-empty, so
        the extra name changes no boolean. This one has no publisher to hide behind.
        """
        result = self._ld({"@type": "Article",
                           "reviewedBy": self._org("Review Board")})
        self.assertEqual(result["signals"]["publishers"], [])

    def test_an_author_and_a_reviewer_are_reported_apart(self):
        result = self._ld({"@type": "Article",
                           "author": self._person(),
                           "reviewedBy": self._person("Dr Rye")})
        self.assertEqual(result["signals"]["authors"], ["A Baker"])
        self.assertEqual(result["signals"]["reviewers"], ["Dr Rye"])

    def test_a_reviewer_is_read_as_a_string_a_node_and_a_list(self):
        """Each form must assert both halves. Checking only `reviewers` would pass an
        implementation that writes the name into `authors` as well, which is the
        behaviour being removed."""
        forms = {
            "string": "Dr Rye",
            "node": self._person("Dr Rye"),
            "list": [self._person("Dr Rye")],
        }
        for label, value in forms.items():
            with self.subTest(label):
                result = self._ld({"@type": "Article", "reviewedBy": value})
                self.assertEqual(result["signals"]["reviewers"], ["Dr Rye"])
                self.assertEqual(result["signals"]["authors"], [])

    def test_a_customer_review_does_not_author_the_product_page(self):
        """Every e-commerce product page carrying one customer review passed CN-057
        on the strength of the shopper's name."""
        result = self._ld({"@type": "Product", "name": "Tin",
                           "brand": self._org(),
                           "review": [{"@type": "Review",
                                       "author": self._person("Shopper Sam")}]})
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_comment_does_not_author_the_page(self):
        result = self._ld({"@type": "Article", "publisher": self._org(),
                           "comment": [{"@type": "Comment",
                                        "author": self._person("Commenter Cal")}]})
        self.assertEqual(result["signals"]["authors"], [])

    def test_an_answer_does_not_author_the_faq_page(self):
        result = self._ld({"@type": "FAQPage", "publisher": self._org(),
                           "mainEntity": [{"@type": "Question", "name": "Why?",
                                           "acceptedAnswer": {
                                               "@type": "Answer",
                                               "author": self._person("Answerer Ann")}}]})
        self.assertEqual(result["signals"]["authors"], [])

    def test_a_page_with_an_author_keeps_only_its_own(self):
        """The verdict here was already right; the evidence was not. A page naming its
        author also reported the shopper as a second one.

        This catches an implementation that drops every nested credit rather than the
        foreign ones. It does *not* catch pruning by node type — that removes the
        `Review` node and leaves the author, so this test still passes — which is what
        `test_an_editorial_review_page_credits_its_own_author` is for.
        """
        result = self._ld({"@type": "Article", "author": self._person(),
                           "publisher": self._org(),
                           "review": [{"@type": "Review",
                                       "author": self._person("Shopper Sam")}]})
        self.assertEqual(result["signals"]["authors"], ["A Baker"])

    def test_the_nestings_a_cms_really_uses_still_credit(self):
        """The boundary this change must not cross. Every one of these puts the
        article somewhere other than the document root, and all of them are ordinary
        CMS output."""
        documents = {
            "@graph": {"@context": "https://schema.org",
                       "@graph": [{"@type": "WebSite", "name": "Fixture Bakery"},
                                  {"@type": "Article", "author": self._person(),
                                   "publisher": self._org()}]},
            "mainEntity": {"@type": "WebPage",
                           "mainEntity": {"@type": "Article",
                                          "author": self._person(),
                                          "publisher": self._org()}},
            "mainEntityOfPage": {"@type": "Article", "author": self._person(),
                                 "publisher": self._org(),
                                 "mainEntityOfPage": {"@type": "WebPage",
                                                      "@id": "https://x.example/"}},
            "blogPost": {"@type": "Blog",
                         "blogPost": [{"@type": "BlogPosting",
                                       "author": self._person(),
                                       "publisher": self._org()}]},
        }
        for label, document in documents.items():
            with self.subTest(label):
                result = self._ld(document)
                self.assertEqual(result["signals"]["authors"], ["A Baker"])
                self.assertEqual(result["signals"]["publishers"], ["Fixture Bakery"])

        both = self._ld({"@type": "Article", "publisher": self._org(),
                         "author": [self._person(), self._person("B Baker")]})
        self.assertEqual(both["signals"]["authors"], ["A Baker", "B Baker"])

    def test_an_editorial_review_page_credits_its_own_author(self):
        """A specialist publication's review *is* the page. Nothing descended into it
        through `review`, so its author is the page's author.

        This is the test that fails the moment exclusion is written against the
        `Review` type instead of the key that reached it.
        """
        result = self._ld({"@type": "Review", "author": self._person(),
                           "publisher": self._org(),
                           "itemReviewed": {"@type": "Product", "name": "Tin"}})
        self.assertEqual(result["signals"]["authors"], ["A Baker"])

    def test_a_reviewed_but_unauthored_page_says_so(self):
        """No registry rule reads this script's findings, so this text is checked by
        nobody unless it is checked here. The second half is the control: without it
        an implementation that drops the `if reviewers` guard passes."""
        reviewed = self._ld({"@type": "Article",
                             "reviewedBy": self._person("Dr Rye")})
        self.assertEqual(
            [issue["message"] for issue in reviewed["issues"]],
            ["No clear author or byline signal found.",
             "Content is credited to a reviewer but names no author.",
             "No publisher or site-identity signal found.",
             "No visible credential or review language found.",
             "No editorial, review, corrections, or fact-check policy link detected.",
             "No obvious about/contact/privacy/team trust links detected.",
             "No privacy policy link detected."])

        neither = self._ld({"@type": "Article", "publisher": self._org()})
        self.assertNotIn("Content is credited to a reviewer but names no author.",
                         [issue["message"] for issue in neither["issues"]])

    def test_a_reviewer_adds_nothing_to_an_authored_page_score(self):
        """Asserting `score == 0` on a reviewer-only page would prove nothing: with
        `authors == []` already established, zero is arithmetic. Two pages differing
        only by a `reviewedBy` key is the comparison that has content."""
        authored = self._ld({"@type": "Article", "author": self._person(),
                             "publisher": self._org()})
        also_reviewed = self._ld({"@type": "Article", "author": self._person(),
                                  "publisher": self._org(),
                                  "reviewedBy": self._person("Dr Rye")})
        self.assertEqual(authored["score"], also_reviewed["score"])
        self.assertEqual(also_reviewed["signals"]["reviewers"], ["Dr Rye"])

    def test_a_hoisted_customer_review_still_does_not_author_the_page(self):
        """Flattening a page into `@graph` lifts the customer review to the top level
        and leaves `"review": {"@id": "#r1"}` behind. Pruning by key alone never
        reaches it, and the shopper is credited again."""
        shopper = self._person("Shopper Sam")
        documents = {
            "product first": {"@context": "https://schema.org", "@graph": [
                {"@type": "Product", "name": "Tin", "brand": self._org(),
                 "review": {"@id": "#r1"}},
                {"@type": "Review", "@id": "#r1", "author": shopper}]},
            "review first": {"@context": "https://schema.org", "@graph": [
                {"@type": "Review", "@id": "#r1", "author": shopper},
                {"@type": "Product", "name": "Tin", "brand": self._org(),
                 "review": {"@id": "#r1"}}]},
        }
        for label, document in documents.items():
            with self.subTest(label):
                result = self._ld(document)
                self.assertEqual(result["signals"]["authors"], [])
                self.assertEqual(verdict("CN-057", result), FAIL)

    def test_a_hoisted_subject_keeps_the_page_node(self):
        """The other direction, and the reason the `@id` rule covers contributions
        only. A review site hoists the product and points at it with `itemReviewed`;
        treating that reference the way a `review` reference is treated would prune the
        page's own product node and lose the brand that is its publisher evidence.

        **Reversed in 0.78.0, and the argument above is kept because it is half of the
        trade.** The same markup is emitted by a review site reviewing somebody else's
        product, where that brand is the manufacturer; reporting it as the review page's
        publisher passed `CN-057` — a `high` item — on a page that never names its own.
        The markup cannot separate the two, so neither is credited. A page that wants the
        old answer declares its subject, which
        `test_a_declared_subject_keeps_its_brand_however_the_claim_is_written` in
        `tests/test_page_boundary.py` proves."""
        result = self._ld({"@context": "https://schema.org", "@graph": [
            {"@type": "Product", "@id": "#p", "name": "Tin", "brand": self._org()},
            {"@type": "Review", "itemReviewed": {"@id": "#p"},
             "author": self._person("Staff Journalist")}]})
        self.assertEqual(result["signals"]["authors"], ["Staff Journalist"])
        self.assertEqual(result["signals"]["publishers"], [])

    def test_the_reviewed_work_and_the_cited_work_are_not_the_page(self):
        """A review of Moby Dick reported Herman Melville among its authors."""
        reviewed = self._ld({"@type": "Review", "author": self._person("Reviewer A"),
                             "publisher": self._org("Book Review Weekly"),
                             "itemReviewed": {
                                 "@type": "Book", "name": "Moby Dick",
                                 "author": self._person("Herman Melville")}})
        self.assertEqual(reviewed["signals"]["authors"], ["Reviewer A"])

        cited = self._ld({"@type": "Article", "author": self._person(),
                          "publisher": self._org(),
                          "citation": {"@type": "ScholarlyArticle",
                                       "author": self._person("Smith")}})
        self.assertEqual(cited["signals"]["authors"], ["A Baker"])

    def test_every_contribution_key_is_covered(self):
        """Without this, an implementation naming three of the seven keys passes every
        other test here — the three that happen to have a test of their own."""
        from seo_common import CONTRIBUTION_KEYS
        self.assertTrue(CONTRIBUTION_KEYS, "the key set is empty")
        for key in sorted(CONTRIBUTION_KEYS):
            with self.subTest(key):
                result = self._ld({"@type": "Article", "publisher": self._org(),
                                   key: [{"@type": "Review",
                                          "author": self._person("Shopper Sam")}]})
                self.assertEqual(result["signals"]["authors"], [])


class Freshness(unittest.TestCase):
    """CN-038 `score`, CN-056 `dates`."""

    PUBLISHED_2020 = '<meta property="article:published_time" content="2020-01-01">'

    @staticmethod
    def _check_document(document, *, body="", today=None):
        import freshness_checker
        html = ('<!doctype html><html><head><script type="application/ld+json">' +
                json.dumps(document) + '</script></head><body>' + body + '</body></html>')
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return freshness_checker.check_freshness(path, today=today)
        finally:
            os.unlink(path)

    @staticmethod
    def _check_html(markup, *, head="", today):
        import freshness_checker
        html = ('<!doctype html><html><head>' + head + '</head><body>'
                '<p>Bread rises when the yeast is warm.</p>' + markup +
                '</body></html>')
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return freshness_checker.check_freshness(path, today=today)
        finally:
            os.unlink(path)

    def test_a_date_a_comment_claims_by_itemref_is_not_the_pages_date(self):
        """The same `itemref` boundary as the byline one, through the other reader
        that has verdicts on it. It is here as well as in `EeatSignals` because this
        reader is handed the document's answer rather than computing it, and a wrong
        set threaded in would be invisible to a test that only asks about authors.
        """
        claimed = self._check_html(
            '<div itemprop="comment" itemscope itemref="t1"></div>'
            '<time id="t1" datetime="2018-05-10">2018</time>',
            today=date(2026, 8, 18),
        )
        self.assertEqual(claimed["dates"], [])
        self.assertIsNone(claimed["latest_date"])
        # And the same `<time>` with nothing claiming it is still the page's own, so
        # the assertion above is known to be about the claim.
        own = self._check_html('<time datetime="2018-05-10">2018</time>',
                               today=date(2026, 8, 18))
        self.assertEqual([entry["raw"] for entry in own["dates"]], ["2018-05-10"])

    def test_json_ld_date_inside_a_comment_is_not_the_pages_date(self):
        script = ('<script type="application/ld+json">' + json.dumps({
            "@type": "Article", "datePublished": "2019-01-01",
        }) + '</script>')
        result = self._check_html(
            '<div itemprop="comment">' + script + '</div>',
            today=date(2026, 8, 18),
        )
        self.assertEqual(result["dates"], [])
        self.assertIsNone(result["latest_date"])

    def test_a_commenters_published_time_meta_is_not_the_pages_date(self):
        result = self._check_html(
            '<div itemprop="comment"><meta property="article:published_time" '
            'content="2019-01-01"></div>',
            today=date(2026, 8, 18),
        )
        self.assertEqual(result["dates"], [])
        self.assertIsNone(result["latest_date"])

    def test_a_dated_article_is_fresh_and_its_dates_are_found(self):
        good = out("fresh")
        self.assertTrue(good["dates"])
        self.assertEqual(verdict("CN-056", good), PASS)
        self.assertEqual(verdict("CN-038", good), PASS)

    def test_a_page_with_no_date_anywhere_reports_no_dates(self):
        bad = out("fresh_bad")
        self.assertEqual(bad["dates"], [])
        self.assertEqual(verdict("CN-056", bad), FAIL)
        self.assertEqual(verdict("CN-038", bad), FAIL)

    def test_a_customer_review_date_is_not_the_page_date(self):
        result = self._check_document({
            "@type": "Product", "name": "Tin",
            "review": {"@type": "Review", "datePublished": "2019-04-02"},
        })
        self.assertEqual(result["dates"], [])
        self.assertEqual(verdict("CN-056", result), FAIL)

    def test_a_reviewed_works_date_is_not_the_page_date(self):
        result = self._check_document({
            "@type": "Review", "datePublished": "2026-07-01",
            "itemReviewed": {
                "@type": "Book", "datePublished": "1851-10-18",
            },
        })
        self.assertEqual(result["latest_date"], "2026-07-01")
        self.assertFalse(any("1851" in entry["raw"] for entry in result["dates"]))

    def test_a_cited_papers_date_is_not_the_page_date(self):
        result = self._check_document({
            "@type": "Article", "datePublished": "2026-07-02",
            "citation": {
                "@type": "ScholarlyArticle", "datePublished": "2020-01-01",
            },
        })
        self.assertEqual(result["latest_date"], "2026-07-02")
        self.assertFalse(any("2020" in entry["raw"] for entry in result["dates"]))

    def test_the_pages_own_dates_still_count(self):
        published = "2026-07-01"
        modified = "2026-07-20"
        dated = {"datePublished": published, "dateModified": modified}
        documents = {
            "@graph": {"@graph": [{"@type": "Article", **dated}]},
            "mainEntity": {"@graph": [
                {"@type": "WebPage", "mainEntity": {"@id": "#article"}},
                {"@type": "Article", "@id": "#article", **dated},
            ]},
            "blogPost": {"@type": "Blog", "blogPost": {
                "@type": "BlogPosting", **dated,
            }},
        }
        for label, document in documents.items():
            with self.subTest(label):
                result = self._check_document(document)
                self.assertEqual({entry["raw"] for entry in result["dates"]},
                                 {published, modified})

    def test_a_future_prose_date_is_not_freshness(self):
        today = date(2026, 8, 17)
        document = {"@type": "Article", "datePublished": "2020-01-01"}
        stale = self._check_document(document, today=today)
        with_future = self._check_document(
            document, body="The event is on March 14, 2027.", today=today)
        self.assertEqual(stale["latest_date"], "2020-01-01")
        self.assertEqual(with_future["latest_date"], "2020-01-01")
        self.assertEqual(with_future["score"], stale["score"])
        self.assertEqual(verdict("CN-038", stale), FAIL)
        self.assertEqual(verdict("CN-038", with_future), FAIL)

    def test_a_future_date_is_still_reported(self):
        today = date(2026, 8, 17)
        result = self._check_document(
            {"@type": "Article", "datePublished": "2020-01-01"},
            body="The event is on March 14, 2027.", today=today)
        future = [entry for entry in result["dates"]
                  if entry["date"] == "2027-03-14"]
        self.assertEqual(len(future), 1)
        self.assertEqual(future[0]["source"], "body")
        info = [issue for issue in result["issues"] if issue["severity"] == "info"]
        self.assertEqual(info, [{
            "severity": "info",
            "message": "1 date(s) on this page are more than 2 days in the future "
                       "and were read as content rather than as publication dates: "
                       "March 14, 2027",
        }])

    def test_a_future_roled_date_stays_in_dates_but_not_in_latest(self):
        today = date(2026, 8, 17)
        result = self._check_document(
            {"@type": "Article", "datePublished": "2027-03-14"}, today=today)
        self.assertEqual(len(result["dates"]), 1)
        self.assertEqual(result["dates"][0]["source"], "schema_published")
        self.assertEqual(verdict("CN-056", result), PASS)
        self.assertIsNone(result["latest_date"])
        self.assertEqual(result["score"], 65)

    def test_the_tolerance_boundary(self):
        today = date(2026, 8, 17)
        for days_ahead in range(4):
            candidate = today + timedelta(days=days_ahead)
            with self.subTest(days_ahead=days_ahead):
                result = self._check_document(
                    {"@type": "Article", "datePublished": candidate.isoformat()},
                    today=today)
                expected = candidate.isoformat() if days_ahead <= 2 else None
                self.assertEqual(result["latest_date"], expected)

    def test_the_tolerance_constant_is_the_one_in_use(self):
        import freshness_checker
        today = date(2026, 8, 17)
        tomorrow = (today + timedelta(days=1)).isoformat()
        with mock.patch.object(freshness_checker, "FUTURE_DATE_TOLERANCE_DAYS", 0):
            result = self._check_document(
                {"@type": "Article", "datePublished": tomorrow}, today=today)
        self.assertIsNone(result["latest_date"])

    def test_a_future_modified_date_does_not_report_a_mismatch(self):
        today = date(2026, 8, 17)
        result = self._check_document({
            "@type": "Article",
            "datePublished": "2026-08-01",
            "dateModified": "2027-03-14",
        }, today=today)
        self.assertIs(result["schema_date_mismatch"], False)
        self.assertEqual(result["latest_date"], "2026-08-01")

    def test_a_real_mismatch_is_still_reported(self):
        today = date(2026, 8, 17)
        result = self._check_document({
            "@type": "Article",
            "datePublished": "2026-08-01",
            "dateModified": "2026-07-01",
        }, today=today)
        self.assertIs(result["schema_date_mismatch"], True)
        self.assertEqual(result["score"], 85)

    def test_a_page_dated_only_in_the_future_reports_no_date(self):
        today = date(2026, 8, 17)
        result = self._check_document(
            {"@type": "Article", "datePublished": "2027-03-14"},
            body="The event is on March 14, 2027.", today=today)
        self.assertIsNone(result["latest_date"])
        self.assertEqual(result["score"], 65)
        messages = [issue["message"] for issue in result["issues"]]
        self.assertIn("No parseable published or modified date found.", messages)
        self.assertTrue(any("March 14, 2027" in message for message in messages))

    def test_an_ordinary_stale_page_is_unchanged(self):
        today = date(2026, 8, 17)
        result = self._check_document(
            {"@type": "Article", "datePublished": "2020-01-01"}, today=today)
        self.assertEqual(result["score"], 55)
        self.assertEqual(result["age_days"], 2420)

    def test_a_microdata_comments_date_is_not_the_pages(self):
        # 0.73.0 moved this DOM boundary into the shared helper used by author signals.
        today = date(2026, 8, 17)
        result = self._check_html(
            '<article itemscope itemtype="https://schema.org/Article">'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment">'
            '<p>Great post.</p>'
            '<time itemprop="datePublished" datetime="2026-08-01">fresh</time>'
            '</div></article>', head=self.PUBLISHED_2020, today=today)
        self.assertEqual(result["latest_date"], "2020-01-01")
        self.assertEqual(result["age_days"], 2420)
        self.assertEqual(result["score"], 55)
        self.assertEqual(verdict("CN-038", result), FAIL)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2020-01-01"})

    def test_a_microdata_reviewed_works_date_is_not_the_pages(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<div itemprop="itemReviewed" itemscope '
            'itemtype="https://schema.org/Book">'
            '<time itemprop="datePublished" datetime="1851-10-18">old</time>'
            '</div>', head=self.PUBLISHED_2020, today=today)
        self.assertEqual(result["latest_date"], "2020-01-01")
        self.assertEqual(result["age_days"], 2420)
        self.assertEqual(result["score"], 55)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2020-01-01"})

    def test_a_review_page_keeps_its_own_date(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<article itemscope itemtype="https://schema.org/Review">'
            '<time itemprop="datePublished" datetime="2026-08-01">fresh</time>'
            '</article>', today=today)
        self.assertEqual(result["latest_date"], "2026-08-01")
        self.assertEqual(result["age_days"], 16)
        self.assertEqual(result["score"], 100)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2026-08-01"})

    def test_a_sidebar_card_does_not_date_the_page(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<main><time datetime="2026-08-01">fresh</time></main>'
            '<aside><div itemscope itemtype="https://schema.org/NewsArticle">'
            '<time itemprop="datePublished" datetime="2018-05-10">archive</time>'
            '</div></aside>', today=today)
        self.assertEqual(result["latest_date"], "2026-08-01")
        self.assertEqual(result["age_days"], 16)
        self.assertEqual(result["score"], 100)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2018-05-10", "2026-08-01"})

    def test_a_foreign_itemprop_is_matched_as_a_token(self):
        today = date(2026, 8, 17)
        for itemprop in ("reviewCount", "commentCount"):
            with self.subTest(itemprop=itemprop):
                result = self._check_html(
                    f'<div itemprop="{itemprop}">'
                    '<time datetime="2026-08-01">fresh</time></div>',
                    head=self.PUBLISHED_2020, today=today)
                self.assertEqual(result["latest_date"], "2026-08-01")
                self.assertEqual(result["age_days"], 16)
                self.assertEqual(result["score"], 100)
                self.assertEqual({entry["raw"] for entry in result["dates"]},
                                 {"2020-01-01", "2026-08-01"})

    def test_the_boundary_holds_through_nested_markup(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<div itemprop="comment"><section><div><span><em><strong><small>'
            '<time datetime="2026-08-01">fresh</time>'
            '</small></strong></em></span></div></section></div>',
            head=self.PUBLISHED_2020, today=today)
        self.assertEqual(result["latest_date"], "2020-01-01")
        self.assertEqual(result["age_days"], 2420)
        self.assertEqual(result["score"], 55)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2020-01-01"})

    def test_a_time_carrying_the_foreign_itemprop_itself_is_excluded(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<time itemprop="comment" datetime="2026-08-01">fresh</time>',
            head=self.PUBLISHED_2020, today=today)
        self.assertEqual(result["latest_date"], "2020-01-01")
        self.assertEqual(result["age_days"], 2420)
        self.assertEqual(result["score"], 55)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2020-01-01"})

    def test_both_representations_of_one_page_agree(self):
        today = date(2026, 8, 17)
        json_ld = json.dumps({
            "@type": "Article", "datePublished": "2020-01-01",
            "comment": {"@type": "Comment", "datePublished": "2026-08-01"},
        })
        schema = self._check_html(
            f'<script type="application/ld+json">{json_ld}</script>', today=today)
        microdata = self._check_html(
            '<div itemprop="comment" itemscope>'
            '<time datetime="2026-08-01">fresh</time></div>',
            head=self.PUBLISHED_2020, today=today)
        for field in ("latest_date", "age_days", "score"):
            self.assertEqual(microdata[field], schema[field], field)
        self.assertEqual(schema["latest_date"], "2020-01-01")
        self.assertEqual(schema["age_days"], 2420)
        self.assertEqual(schema["score"], 55)
        self.assertEqual({entry["raw"] for entry in microdata["dates"]},
                         {entry["raw"] for entry in schema["dates"]})
        self.assertEqual({entry["raw"] for entry in schema["dates"]},
                         {"2020-01-01"})

    def test_a_page_with_no_microdata_is_unchanged(self):
        # 0.73.0's shared traversal must still leave an unguarded `<time>` alone.
        today = date(2026, 8, 17)
        result = self._check_html(
            '<time datetime="2020-01-01">old</time>'
            '<time datetime="2026-08-01">fresh</time>', today=today)
        self.assertEqual(result["latest_date"], "2026-08-01")
        self.assertEqual(result["age_days"], 16)
        self.assertEqual(result["score"], 100)
        self.assertEqual({entry["raw"] for entry in result["dates"]},
                         {"2020-01-01", "2026-08-01"})

    def test_every_foreign_key_is_covered_for_microdata_dates(self):
        from seo_common import FOREIGN_CREDIT_KEYS
        today = date(2026, 8, 17)
        self.assertEqual(len(FOREIGN_CREDIT_KEYS), 10)
        for key in sorted(FOREIGN_CREDIT_KEYS):
            with self.subTest(key=key):
                result = self._check_html(
                    f'<div itemprop="{key}" itemscope>'
                    '<time datetime="2026-08-01">fresh</time></div>',
                    head=self.PUBLISHED_2020, today=today)
                self.assertEqual(result["latest_date"], "2020-01-01")
                self.assertEqual(result["age_days"], 2420)
                self.assertEqual(result["score"], 55)
                self.assertEqual({entry["raw"] for entry in result["dates"]},
                                 {"2020-01-01"})

    def test_the_walk_reads_every_ancestor_and_every_token(self):
        today = date(2026, 8, 17)
        cases = {
            "multiple tokens": (
                '<div itemprop="comment text">'
                '<time datetime="2026-08-01">fresh</time></div>'),
            "intermediate property": (
                '<div itemprop="comment"><div itemprop="text">'
                '<time datetime="2026-08-01">fresh</time></div></div>'),
            "six levels": (
                '<div itemprop="comment"><section><div><span><em><strong><small>'
                '<time datetime="2026-08-01">fresh</time>'
                '</small></strong></em></span></div></section></div>'),
        }
        for label, markup in cases.items():
            with self.subTest(label=label):
                result = self._check_html(
                    markup, head=self.PUBLISHED_2020, today=today)
                self.assertEqual(result["latest_date"], "2020-01-01")
                self.assertEqual(result["age_days"], 2420)
                self.assertEqual(result["score"], 55)
                self.assertEqual({entry["raw"] for entry in result["dates"]},
                                 {"2020-01-01"})

    def test_the_key_match_is_exact_like_the_json_ld_half(self):
        today = date(2026, 8, 17)
        for itemprop in ("itemreviewed", "schema:comment"):
            with self.subTest(itemprop=itemprop):
                result = self._check_html(
                    f'<div itemprop="{itemprop}">'
                    '<time datetime="2026-08-01">fresh</time></div>',
                    head=self.PUBLISHED_2020, today=today)
                self.assertEqual(result["latest_date"], "2026-08-01")
                self.assertEqual(result["age_days"], 16)
                self.assertEqual(result["score"], 100)
                self.assertEqual({entry["raw"] for entry in result["dates"]},
                                 {"2020-01-01", "2026-08-01"})

    def test_a_hoisted_customer_review_date_is_not_the_page_date(self):
        result = self._check_document({"@graph": [
            {"@type": "Product", "name": "Tin", "review": {"@id": "#r1"}},
            {"@type": "Review", "@id": "#r1", "datePublished": "2019-04-02"},
        ]})
        self.assertEqual(result["dates"], [])

    def test_a_hoisted_subjects_date_is_not_the_page_date(self):
        result = self._check_document({"@graph": [
            {"@type": "Review", "itemReviewed": {"@id": "#b"}},
            {"@type": "Book", "@id": "#b", "datePublished": "1851-10-18"},
        ]})
        self.assertEqual(result["dates"], [])

    def test_every_foreign_key_is_covered_for_dates(self):
        from seo_common import FOREIGN_CREDIT_KEYS
        self.assertTrue(FOREIGN_CREDIT_KEYS, "the key set is empty")
        for key in sorted(FOREIGN_CREDIT_KEYS):
            with self.subTest(key):
                result = self._check_document({
                    "@type": "Thing",
                    key: {"@type": "Thing", "datePublished": "2019-04-02"},
                })
                self.assertEqual(result["dates"], [])

    def test_declared_microdata_reaches_the_publication_mismatch_only_once(self):
        today = date(2026, 8, 17)
        modified = '<meta property="article:modified_time" content="2026-07-01">'
        result = self._check_html(
            '<time itemprop="datePublished" datetime="2026-08-01">1 August</time>',
            head=modified, today=today)
        self.assertIs(result["schema_date_mismatch"], True)
        self.assertEqual(result["score"], 85)
        self.assertIn("dateModified appears older than datePublished.",
                      [issue["message"] for issue in result["issues"]])
        self.assertEqual(result["dates"], [
            {"source": "meta", "raw": "2026-07-01", "date": "2026-07-01"},
            {"source": "time", "raw": "2026-08-01", "date": "2026-08-01"},
        ])

        control = self._check_html("", head=modified +
            '<script type="application/ld+json">'
            '{"@type":"Article","datePublished":"2026-08-01"}</script>',
            today=today)
        self.assertIs(control["schema_date_mismatch"], True)
        self.assertEqual(control["score"], 85)

    def test_every_published_time_meta_reaches_the_publication_mismatch(self):
        today = date(2026, 10, 1)
        modified = '<meta property="article:modified_time" content="2026-08-01">'
        later = '<meta property="article:published_time" content="2026-09-09">'
        earlier = '<meta property="article:published_time" content="2026-07-01">'
        result = self._check_html("", head=modified + later + earlier, today=today)
        self.assertIs(result["schema_date_mismatch"], True)
        self.assertEqual(result["score"], 85)
        self.assertIn("dateModified appears older than datePublished.",
                      [issue["message"] for issue in result["issues"]])
        self.assertEqual([entry["raw"] for entry in result["dates"]],
                         ["2026-08-01", "2026-07-01"])

        control = self._check_html("", head=modified + later, today=today)
        self.assertIs(control["schema_date_mismatch"], True)
        self.assertEqual(control["score"], 85)

    def test_non_time_microdata_reaches_the_latest_fallback(self):
        today = date(2026, 8, 17)
        result = self._check_html(
            '<span itemprop="datePublished" content="2026-08-01">1 August</span>',
            today=today)
        self.assertEqual(result["latest_date"], "2026-08-01")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["dates"], [])
        self.assertNotIn("No parseable published or modified date found.",
                         [issue["message"] for issue in result["issues"]])

        control = self._check_html(
            '<time itemprop="datePublished" datetime="2026-08-01">1 August</time>',
            today=today)
        self.assertEqual(control["latest_date"], "2026-08-01")
        self.assertEqual(control["score"], 100)
        self.assertEqual([entry["source"] for entry in control["dates"]], ["time"])


class FaviconDisplay(unittest.TestCase):
    """MB-104 fetches the declaration and grades only dimensions it could read."""

    PAGE = ('<!doctype html><html><head><title>Icon test</title>'
            '<link rel="icon" href="/icon"></head><body></body></html>')

    def run_url(self, url: str) -> dict:
        proc = harness.spawn(
            [sys.executable, os.path.join(SCRIPTS, "favicon_check.py"), url, "--json"],
            env=script_env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip(), proc.stderr)
        return json.loads(proc.stdout)

    def served_icon(self, body: bytes | str, content_type: str = "image/png",
                    status: int = 200) -> dict:
        routes = {"/": self.PAGE,
                  "/icon": (status, {"Content-Type": content_type}, body)}
        with served(routes) as site:
            return self.run_url(site.url)

    def rule_evidence(self, output: dict) -> tuple[bool | None, str]:
        return evaluate(ITEMS["MB-104"]["check"]["assert"], output)

    def test_the_good_mock_reaches_a_measured_48px_pass(self):
        result = out("favicon")
        self.assertEqual(verdict("MB-104", result), PASS)
        self.assertEqual(result["favicon"]["format"], "ico")
        self.assertEqual(result["favicon"]["min_side_px"], 48)
        self.assertEqual(self.rule_evidence(result),
                         (True, "favicon.displays_at_48px = True"))

    def test_no_declared_icon_is_a_failure_with_a_reason_and_issue(self):
        result = out("favicon_bad")
        self.assertEqual(verdict("MB-104", result), FAIL)
        self.assertIs(result["favicon"]["displays_at_48px"], False)
        self.assertIn("No favicon is declared", result["favicon"]["reason"])
        self.assertTrue(result["issues"])

    def test_a_declared_404_is_unreachable_not_too_small(self):
        result = self.served_icon(b"", status=404)
        self.assertEqual(verdict("MB-104", result), FAIL)
        self.assertIn("unreachable", result["favicon"]["reason"].lower())
        self.assertNotIn("small", result["favicon"]["reason"].lower())
        self.assertIsNone(result["favicon"]["min_side_px"])
        self.assertTrue(result["issues"])

    def test_a_64px_png_passes_with_its_measured_size(self):
        result = self.served_icon(valid_png(64, 64))
        self.assertEqual(verdict("MB-104", result), PASS)
        self.assertEqual(result["favicon"]["href"], "/icon")
        self.assertTrue(result["favicon"]["url"].endswith("/icon"))
        self.assertEqual((result["favicon"]["width"], result["favicon"]["height"]),
                         (64, 64))
        self.assertIn("64x64", result["favicon"]["reason"])

    def test_a_32px_png_fails_and_names_the_measured_size(self):
        result = self.served_icon(valid_png(32, 32))
        self.assertEqual(verdict("MB-104", result), FAIL)
        self.assertEqual(result["favicon"]["min_side_px"], 32)
        self.assertIn("32x32", result["favicon"]["reason"])

    def test_an_unrecognised_body_is_no_data_not_a_small_icon(self):
        cases = (
            (b"<!doctype html><title>error</title>", "text/html"),
            (b"", "application/octet-stream"),
            (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\0" * 8, "image/png"),
        )
        for body, content_type in cases:
            with self.subTest(content_type=content_type, bytes=len(body)):
                result = self.served_icon(body, content_type)
                self.assertEqual(verdict("MB-104", result), NO_DATA)
                self.assertNotIn("displays_at_48px", result["favicon"])
                self.assertIsNone(result["favicon"]["min_side_px"])
                self.assertIn("not recognised", result["favicon"]["reason"])

    def test_an_unreachable_page_is_no_data(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        result = self.run_url(f"http://127.0.0.1:{port}/")
        self.assertEqual(verdict("MB-104", result), NO_DATA)
        self.assertNotIn("displays_at_48px", result["favicon"])
        self.assertIn("could not be fetched", result["favicon"]["reason"])

    def test_svg_passes_even_with_a_one_pixel_viewbox(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'
        result = self.served_icon(svg, "image/svg+xml")
        self.assertEqual(verdict("MB-104", result), PASS)
        self.assertEqual(result["favicon"]["format"], "svg")
        self.assertEqual((result["favicon"]["width"], result["favicon"]["height"]),
                         (1, 1))
        self.assertIsNone(result["favicon"]["min_side_px"])

    def test_the_largest_ico_entry_decides(self):
        multi = self.served_icon(valid_ico((16, 16), (32, 32), (48, 48)),
                                 "image/x-icon")
        small = self.served_icon(valid_ico((16, 16)), "image/x-icon")
        self.assertEqual(verdict("MB-104", multi), PASS)
        self.assertEqual(multi["favicon"]["min_side_px"], 48)
        self.assertEqual(verdict("MB-104", small), FAIL)
        self.assertEqual(small["favicon"]["min_side_px"], 16)

    def test_a_zero_ico_size_byte_means_256(self):
        result = self.served_icon(valid_ico((256, 256)), "image/x-icon")
        self.assertEqual(verdict("MB-104", result), PASS)
        self.assertEqual((result["favicon"]["width"], result["favicon"]["height"]),
                         (256, 256))

    def test_a_non_square_icon_is_judged_on_its_shorter_side(self):
        result = self.served_icon(valid_png(96, 32))
        self.assertEqual(verdict("MB-104", result), FAIL)
        self.assertEqual(result["favicon"]["min_side_px"], 32)
        self.assertIn("96x32", result["favicon"]["reason"])

    def test_gif_jpeg_and_each_webp_header_are_measured(self):
        cases = (
            ("gif", valid_gif(64, 64), "image/gif"),
            ("jpeg", valid_jpeg(64, 64), "image/jpeg"),
            ("webp", valid_webp(64, 64, "VP8 "), "image/webp"),
            ("webp", valid_webp(64, 64, "VP8L"), "image/webp"),
            ("webp", valid_webp(64, 64, "VP8X"), "image/webp"),
        )
        for expected_format, body, content_type in cases:
            with self.subTest(format=expected_format, body=body[12:16]):
                result = self.served_icon(body, content_type)
                self.assertEqual(verdict("MB-104", result), PASS)
                self.assertEqual(result["favicon"]["format"], expected_format)
                self.assertEqual(result["favicon"]["min_side_px"], 64)


class AnswerBlocks(unittest.TestCase):
    """GO-144 and GEO-004, both `score`."""

    def test_questions_with_snippet_length_answers_score(self):
        """A "direct answer" is a paragraph of 20 to 70 words immediately after a
        question heading, which is roughly what a featured snippet takes. A page
        answering in eight words scores nothing — correctly, and it is worth knowing
        that is the rule rather than discovering it in a client's report."""
        good = out("answers")
        self.assertTrue(good["direct_answers"])
        self.assertEqual(verdict("GO-144", good), PASS)
        self.assertEqual(verdict("GEO-004", good), PASS)

    def test_the_floor_is_one_direct_answer_and_one_definition(self):
        """32 is derived from the script's own weights, not chosen as a round number.

        `direct_answer` is the only one of the four signals a snippet can be lifted
        from verbatim; a definition is the one that says what the subject is. At 70 the
        item needed at least four signals, because the three strongest sum to 60, and
        the cheapest four are three direct answers and a list — an FAQ page, asked of
        every sampled page including a privacy policy. Both twins carry the same floor
        because `scores_with` makes them one check.

        The floor is a number and not a requirement, and this asserts only that it
        equals the derivation: four lists reach 40 and clear it with no direct answer
        anywhere.
        """
        sys.path.insert(0, SCRIPTS)
        import answer_block_scanner
        points = answer_block_scanner.SIGNAL_POINTS
        for item_id in ("GO-144", "GEO-004"):
            self.assertEqual(ITEMS[item_id]["check"]["assert"]["gte"],
                             points["direct_answer"] + points["definition"], item_id)
        # The claim about the old floor, computed rather than remembered: no three
        # signals reach 70, whatever they are.
        strongest = sorted(points.values(), reverse=True)
        self.assertLess(sum(strongest[:3]), 70)

    def test_a_page_with_no_questions_scores_zero(self):
        bad = out("answers_bad")
        self.assertEqual(bad["score"], 0)
        self.assertEqual(verdict("GEO-004", bad), FAIL)


class CitationReadiness(unittest.TestCase):
    """GO-145 and GEO-005, both `score`."""

    AUTHOR_FINDING = "No clear author or byline signal detected."

    @staticmethod
    def _check_html(html):
        import citation_readiness
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return citation_readiness.check_citation_readiness(path)
        finally:
            os.unlink(path)

    def test_a_commenters_json_ld_author_adds_no_citation_score(self):
        publisher = ('<script type="application/ld+json">' + json.dumps({
            "@type": "WebSite",
            "publisher": {"@type": "Organization", "name": "Page Press"},
        }) + '</script>')
        author = ('<script type="application/ld+json">' + json.dumps({
            "@type": "Article", "author": {"@type": "Person", "name": "D Petras"},
        }) + '</script>')
        result = self._check_html(
            publisher + '<div itemprop="comment">' + author + '</div>')
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_commenters_cite_and_blockquote_tags_add_no_citation_score(self):
        result = self._check_html(
            '<p>A 2025 study found that warm dough rises.</p>'
            '<div itemprop="comment"><blockquote>Quoted source</blockquote>'
            '<cite>Source one</cite><cite>Source two</cite></div>')
        self.assertEqual(result["citation_signals"]["cite_or_blockquote_tags"], 0)
        self.assertEqual(result["score"], 0)

    def test_cited_claims_and_named_sources_score(self):
        self.assertEqual(verdict("GO-145", out("citation")), PASS)
        self.assertEqual(verdict("GEO-005", out("citation")), PASS)

    def test_a_page_with_no_sources_or_dates_does_not(self):
        self.assertEqual(verdict("GEO-005", out("citation_bad")), FAIL)

    def test_layout_author_substrings_do_not_add_fifteen_points(self):
        """This fails if the substring class match returns to citation readiness."""
        layout = self._check_html('<div class="author-grid">A Baker</div>')
        neutral = self._check_html('<div class="team-grid">A Baker</div>')
        byline = self._check_html('<p class="byline">A Baker</p>')
        self.assertEqual(layout["score"], neutral["score"])
        self.assertGreater(byline["score"], layout["score"])

    def _ld(self, document):
        return self._check_html(
            '<!doctype html><html><head><script type="application/ld+json">' +
            json.dumps(document) + '</script></head><body></body></html>')

    @staticmethod
    def _messages(result):
        return [issue["message"] for issue in result["issues"]]

    def test_a_product_name_is_not_an_author(self):
        result = self._ld({"@type": "Product", "name": "Tin"})
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))
        self.assertEqual(result["entity_signals"]["names"], ["Tin"])

    def test_a_meta_author_is_an_author(self):
        result = self._check_html(
            '<!doctype html><html><head><meta name="author" content="A Baker">'
            '</head><body></body></html>')
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_rel_author_link_is_an_author(self):
        result = self._check_html('<a rel="author">A Baker</a>')
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_byline_class_is_still_an_author(self):
        result = self._check_html('<span class="byline">A Baker</span>')
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_customer_reviews_author_is_still_not_the_pages(self):
        result = self._ld({
            "@type": "Product",
            "review": {
                "@type": "Review",
                "author": {"@type": "Person", "name": "Shopper Sam"},
            },
        })
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_bare_string_author_is_an_author(self):
        result = self._ld({"@type": "Article", "author": "A Baker"})
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_both_scripts_now_answer_the_same_question(self):
        import eeat_signal_checker

        documents = {
            "R1 product name": self._ld_html(
                {"@type": "Product", "name": "Tin"}),
            "R2 reviewed book": self._ld_html({
                "@type": "Review",
                "itemReviewed": {
                    "@type": "Book",
                    "name": "Moby Dick",
                    "sameAs": "https://www.wikidata.org/wiki/Q14924",
                },
            }),
            "R3 review author": self._ld_html({
                "@type": "Review",
                "author": {"@type": "Person", "name": "A Baker"},
                "itemReviewed": {"@type": "Book", "name": "Moby Dick"},
            }),
            "R4 byline class": '<span class="byline">A Baker</span>',
            "R5 meta author": '<meta name="author" content="A Baker">',
            "R6 nothing": '<div>Nothing.</div>',
            "R7 customer review": self._ld_html({
                "@type": "Product",
                "review": {
                    "@type": "Review",
                    "author": {"@type": "Person", "name": "Shopper Sam"},
                },
            }),
        }
        for label, html in documents.items():
            with self.subTest(label):
                citation = self._check_html(html)
                with tempfile.NamedTemporaryFile(
                        "w", suffix=".html", delete=False, encoding="utf-8") as fh:
                    fh.write(html)
                    path = fh.name
                try:
                    eeat = eeat_signal_checker.check_eeat(path)
                finally:
                    os.unlink(path)
                self.assertEqual(
                    self.AUTHOR_FINDING not in self._messages(citation),
                    bool(eeat["signals"]["authors"]),
                )

    def test_an_empty_byline_class_names_nobody(self):
        for html in ('<span class="byline"></span>',
                     '<span class="byline">   </span>'):
            with self.subTest(html=html):
                result = self._check_html(html)
                self.assertEqual(result["score"], 0)
                self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_co_author_rel_still_counts(self):
        result = self._check_html('<a rel="co-author">John Doe</a>')
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_microdata_comment_byline_does_not_score_as_the_pages_author(self):
        result = self._check_html(
            '<div itemprop="comment"><span class="author">D Petras</span></div>')
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_microdata_comment_rel_author_does_not_score(self):
        result = self._check_html(
            '<div itemprop="comment"><a rel="author">D Petras</a></div>')
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_a_reviewed_items_author_does_not_score_as_the_pages(self):
        result = self._check_html(
            '<div itemprop="itemReviewed">'
            '<span class="author">Herman Melville</span></div>')
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))

    def test_an_editorial_review_keeps_its_own_html_author(self):
        result = self._check_html(
            '<article itemscope itemtype="https://schema.org/Review">'
            '<span itemprop="author" class="author">M Kazlauskiene</span></article>')
        self.assertEqual(result["score"], 15)
        self.assertNotIn(self.AUTHOR_FINDING, self._messages(result))

    def test_page_author_names_is_shared(self):
        import seo_common

        self.assertTrue(callable(seo_common.page_author_names))
        self.assertTrue(callable(seo_common.under_foreign_credit))
        self.assertTrue(callable(seo_common.schema_values))

        evidence_path = os.path.join(ROOT, "tests", "test_evidence.py")
        with open(evidence_path, encoding="utf-8") as stream:
            evidence_tree = ast.parse(stream.read(), filename=evidence_path)
        shared_class = next(
            node for node in evidence_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "SharedHelpersStayShared"
        )
        guarded_names = {
            node.value for node in ast.walk(shared_class)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue(
            {"page_author_names", "_page_author_names",
             "under_foreign_credit", "_under_foreign_credit",
             "schema_values", "_schema_values"}.issubset(guarded_names))

        for filename in ("citation_readiness.py", "eeat_signal_checker.py"):
            path = os.path.join(SCRIPTS, filename)
            with open(path, encoding="utf-8") as stream:
                tree = ast.parse(stream.read(), filename=path)
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "seo_common"
                for alias in node.names
            }
            with self.subTest(filename=filename):
                self.assertIn("page_author_names", imported)

        freshness_path = os.path.join(SCRIPTS, "freshness_checker.py")
        with open(freshness_path, encoding="utf-8") as stream:
            freshness_tree = ast.parse(stream.read(), filename=freshness_path)
        freshness_imports = {
            alias.name
            for node in ast.walk(freshness_tree)
            if isinstance(node, ast.ImportFrom) and node.module == "seo_common"
            for alias in node.names
        }
        self.assertIn("under_foreign_credit", freshness_imports)

    def test_under_foreign_credit_is_the_shared_dom_boundary(self):
        from seo_common import parse_html, under_foreign_credit

        plain = parse_html('<span class="author">A Baker</span>', "")["soup"].span
        comment = parse_html(
            '<div itemprop="comment"><span class="author">A Baker</span></div>',
            "",
        )["soup"].span
        custom = parse_html(
            '<div itemprop="staffCredit"><span class="author">A Baker</span></div>',
            "",
        )["soup"].span
        self.assertFalse(under_foreign_credit(plain))
        self.assertTrue(under_foreign_credit(comment))
        self.assertFalse(under_foreign_credit(custom))
        self.assertTrue(under_foreign_credit(custom, {"staffCredit"}))

    def test_page_author_names_returns_the_names_not_a_verdict(self):
        from seo_common import page_author_names, parse_html

        rows = [
            ('<meta name="author" content="A Baker">', ["A Baker"]),
            ('<meta name="author" content="">', []),
            ('<meta name="author">', []),
            ('<meta name="author" content="  A Baker  ">', ["A Baker"]),
            ('<span class="byline">   </span>', []),
            (self._ld_html({"author": [{"name": "B"}, {"name": "A"}]}),
             ["A", "B"]),
            (self._ld_html({"author": "A Baker"}), ["A Baker"]),
            (self._ld_html({"author": {"@type": "Person"}}), []),
            ('<meta name="author" content="A Baker">' + self._ld_html(
                {"author": {"name": "A Baker"}}), ["A Baker"]),
            ('<meta name="author" content="A Baker">'
             '<span class="byline">C Dough</span>' + self._ld_html(
                 {"author": {"name": "B Cook"}}),
             ["A Baker", "B Cook", "C Dough"]),
        ]
        for html, expected in rows:
            with self.subTest(html=html, expected=expected):
                parsed = parse_html(html, "")
                self.assertEqual(page_author_names(parsed), expected)

    def test_html_author_credits_stop_at_foreign_properties(self):
        from seo_common import page_author_names, parse_html

        rows = [
            ('<div itemprop="comment"><span class="author">D Petras</span></div>', []),
            ('<div itemprop="comment"><a rel="author">D Petras</a></div>', []),
            ('<div itemprop="comment"><meta name="author" content="D Petras"></div>',
             []),
            ('<div itemprop="comment"><div><section><span class="byline">D Petras'
             '</span></section></div></div>', []),
            ('<article itemscope itemtype="https://schema.org/Review">'
             '<span itemprop="author" class="author">M Kazlauskiene</span></article>',
             ["M Kazlauskiene"]),
            ('<div itemprop="itemReviewed"><span class="author">Herman Melville'
             '</span></div>', []),
            ('<div itemprop="citation"><a rel="author">R Franklin</a></div>', []),
            ('<div itemprop="mainEntity comment"><span class="byline">D Petras'
             '</span></div>', []),
            ('<p class="author">M Kazlauskiene</p><div itemprop="comment">'
             '<span class="author">D Petras</span></div>', ["M Kazlauskiene"]),
            # Kept this foreign author until 0.83.0, which follows `itemref`. The
            # `itemref` is on an element with no `itemscope`, where the specification
            # gives it no meaning; honoured anyway, because a removal rule that reads
            # an invalid claim costs a false fail and one that ignores it costs a
            # false pass.
            ('<div itemprop="comment" itemref="c1"></div>'
             '<span id="c1" class="author">D Petras</span>', []),
            ('<span class="author" itemprop="comment">D Petras</span>', []),
            ('<div itemprop="commentary"><span class="author">D Petras</span></div>',
             ["D Petras"]),
            # Finding 5: the six-key boundary keeps this subject; current, not right.
            ('<article itemscope itemtype="https://schema.org/Article">'
             '<div itemprop="about" itemscope itemtype="https://schema.org/Book">'
             '<span class="author">Herman Melville</span></div></article>',
             ["Herman Melville"]),
            # Read as a defect until 0.83.0 and re-read then: the article's `itemref`
            # claims the *element* and no property — `b1` carries no `itemprop`, and a
            # referenced element without one contributes nothing to the item that named
            # it. Removing the byline is right here, and `EeatSignals` carries the
            # spelling where it does carry one, which is ambiguous and withheld.
            ('<div itemprop="comment"><span id="b1" class="author">M Kazlauskiene'
             '</span></div><article itemscope itemref="b1"></article>', []),
        ]
        for html, expected in rows:
            with self.subTest(html=html, expected=expected):
                self.assertEqual(page_author_names(parse_html(html, "")), expected)

    @staticmethod
    def _ld_html(document):
        return ('<!doctype html><html><head><script type="application/ld+json">' +
                json.dumps(document) + '</script></head><body></body></html>')

    def test_a_contributors_identity_is_not_the_pages_entity(self):
        profiles = [f"https://social.example/shopper/{index}" for index in range(4)]
        bare = self._ld({"@type": "Product", "name": "Tin"})
        reviewed = self._ld({
            "@type": "Product", "name": "Tin",
            "review": {"@type": "Review", "author": {
                "@type": "Person", "name": "Shopper Sam", "sameAs": profiles,
            }},
        })
        self.assertEqual(bare["entity_signals"],
                         {"types": ["Product"], "names": ["Tin"], "sameAs": []})
        self.assertEqual(reviewed["entity_signals"], bare["entity_signals"])
        self.assertEqual(reviewed["score"], bare["score"])

    def test_the_reviewed_subject_is_still_the_pages_entity(self):
        result = self._ld({
            "@type": "Review",
            "itemReviewed": {
                "@type": "Book", "name": "Moby Dick",
                "sameAs": "https://www.wikidata.org/wiki/Q14924",
            },
        })
        self.assertEqual(result["entity_signals"]["sameAs"],
                         ["https://www.wikidata.org/wiki/Q14924"])
        self.assertEqual(result["score"], 5)

    def test_a_hoisted_contributor_is_not_the_pages_entity(self):
        profiles = [f"https://social.example/commenter/{index}" for index in range(4)]
        result = self._ld({"@graph": [
            {"@type": "Article", "comment": {"@id": "#c1"}},
            {"@type": "Person", "@id": "#c1", "name": "Commenter Cal",
             "sameAs": profiles},
        ]})
        self.assertEqual(result["entity_signals"]["sameAs"], [])
        self.assertNotIn("Commenter Cal", result["entity_signals"]["names"])

    def test_the_two_callers_ask_for_different_keys(self):
        import freshness_checker
        contributor = "https://social.example/shopper"
        subject = "https://www.wikidata.org/wiki/Q14924"
        document = {
            "@type": "Review",
            "review": {
                "@type": "Review", "datePublished": "2019-04-02",
                "author": {"@type": "Person", "name": "Shopper Sam",
                           "sameAs": contributor},
            },
            "itemReviewed": {
                "@type": "Book", "name": "Moby Dick", "sameAs": subject,
                "datePublished": "1851-10-18",
            },
        }
        html = ('<!doctype html><html><head><script type="application/ld+json">' +
                json.dumps(document) + '</script></head><body></body></html>')
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            citation = self._check_html(html)
            freshness = freshness_checker.check_freshness(path)
        finally:
            os.unlink(path)
        self.assertEqual(freshness["dates"], [])
        self.assertIn(subject, citation["entity_signals"]["sameAs"])
        self.assertNotIn(contributor, citation["entity_signals"]["sameAs"])

    def test_page_nodes_parameters_are_independent(self):
        from seo_common import CONTRIBUTION_KEYS, FOREIGN_CREDIT_KEYS, page_nodes

        def names(document, **kwargs):
            return {node["name"] for node in page_nodes(document, **kwargs)
                    if "name" in node}

        document = {"@graph": [
            {"@type": "Thing", "name": "Page", "review": {"@id": "#c"},
             "itemReviewed": {"name": "Nested subject"},
             "citation": {"@id": "#s"}},
            {"@id": "#c", "name": "Hoisted contributor"},
            {"@id": "#s", "name": "Hoisted subject"},
        ]}
        with self.subTest("defaults reproduce 0.78.0"):
            self.assertEqual(names(document), {"Page"})
        with self.subTest("hoisted accepts subject keys"):
            self.assertEqual(names(document, hoisted=FOREIGN_CREDIT_KEYS), {"Page"})
        with self.subTest("exclude can keep nested subjects"):
            nested = {"name": "Page", "review": {"name": "Contributor"},
                      "itemReviewed": {"name": "Nested subject"}}
            self.assertEqual(names(nested, exclude=CONTRIBUTION_KEYS),
                             {"Page", "Nested subject"})
        with self.subTest("a custom exclude changes traversal"):
            custom = {"name": "Page", "custom": {"name": "Custom child"}}
            self.assertEqual(names(custom), {"Page", "Custom child"})
            self.assertEqual(names(custom, exclude={"custom"}), {"Page"})

    def test_the_floor_is_an_author_and_a_canonical(self):
        """25 is the two components of this score any page type can carry.

        Claim coverage (35), trusted links (20) and `sameAs` (20) are article and
        entity signals: a privacy policy carries none of them and scored 25 on the
        exemplary fixture, against a floor of 60. Read from the script so that moving
        either weight breaks this rather than silently changing what the floor means.
        """
        with open(os.path.join(SCRIPTS, "citation_readiness.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("score += 15 if author_signals else 0", source)
        self.assertIn('score += 10 if parsed.get("canonical") else 0', source)
        for item_id in ("GO-145", "GEO-005"):
            self.assertEqual(ITEMS[item_id]["check"]["assert"]["gte"], 15 + 10, item_id)

    def test_a_tracking_parameter_is_not_a_footnote(self):
        """`utm_source` is not a source, and six of them were six citations.

        The footnote match read the whole href. On the deliberately failing evidence
        page, six faceted-navigation links of the form `/shop?utm_source=s0&sort=k0`
        were counted, which is most of what took that page to 45 of 100 — above the
        good page's 42. The match now reads `rel` tokens and the URL path only.
        """
        claim = '<p>A 2025 study found that warm dough rises.</p>'
        counted = {
            "a tracking parameter": ('<a href="/shop?utm_source=news">F</a>', 0),
            "a word inside a segment": ('<a href="/blog/open-source">Os</a>', 0),
            "a hyphenated segment": ('<a href="/docs/api-reference">Api</a>', 0),
            "an unrelated fragment": ('<a href="/notes#chapter-2">2</a>', 0),
            "a segment that is the word": ('<a href="/sources/the-study">S</a>', 1),
            "a footnote fragment": ('<a href="/notes#footnote-1">1</a>', 1),
            "a cite fragment": ('<a href="/notes#cite-3">3</a>', 1),
            "a rel token": ('<a rel="footnote" href="/x">n</a>', 1),
        }
        for label, (markup, expected) in counted.items():
            with self.subTest(label):
                result = self._check_html(claim + markup)
                self.assertEqual(
                    result["citation_signals"]["footnote_links"], expected)

    def test_a_bare_fragment_link_never_reaches_this_script(self):
        """The boundary, asserted so it is a decision rather than a surprise.

        `parse_html` drops a link whose href is only a fragment, so the commonest
        footnote spelling of all — `<a href="#footnote-1">` — is invisible here however
        this match is written. Widening the link set changes what every item over
        `links` sees, so it is not done from this script.
        """
        result = self._check_html(
            '<p>A 2025 study found that warm dough rises.</p>'
            '<a href="#footnote-1">1</a>')
        self.assertEqual(result["citation_signals"]["footnote_links"], 0)

    def test_a_page_with_no_factual_claims_earns_no_coverage(self):
        """Nothing to cover is not everything covered.

        `min(1.0, capacity / max(1, claims))` gave a page asserting nothing the whole
        35-point coverage component as soon as it carried one citation signal. This is
        the family 0.49.0 and 0.50.0 removed from image_inventory and
        image_weight_audit: an empty input must not produce a verdict-shaped number.
        """
        silent = self._check_html('<p>Bread.</p><a href="/sources/x">Source</a>')
        claiming = self._check_html(
            '<p>A 2025 study found that warm dough rises.</p>'
            '<a href="/sources/x">Source</a>')
        self.assertEqual(silent["factual_claims"], 0)
        self.assertEqual(silent["citation_signals"]["footnote_links"], 1)
        self.assertGreater(claiming["score"], silent["score"])
        self.assertEqual(claiming["score"] - silent["score"], 35)

    def test_an_ordinary_outbound_link_is_not_citation_capacity(self):
        """A social profile in the footer is not a source for the claim above it.

        Measured on the two fixture origins: the broken entry page carries no cite,
        no blockquote, no footnote link and no schema citation, and took 23 of the 35
        coverage points from two ordinary outbound links. A high-trust host still
        counts, because a link to a .gov is a source whether or not it is wrapped.
        """
        claim = '<p>A 2025 study found that warm dough rises.</p>'
        ordinary = self._check_html(claim + '<a href="https://example.net/x">Us</a>')
        trusted = self._check_html(claim + '<a href="https://www.cdc.gov/x">CDC</a>')
        self.assertEqual(ordinary["citation_signals"]["external_links"], 1)
        self.assertEqual(ordinary["score"], 0)
        self.assertGreater(trusted["score"], ordinary["score"])

    def test_a_cited_works_sameas_is_not_the_pages_entity(self):
        """A page is not about the works it cites.

        Before 0.86.0 `citation` sat in the entity reader's kept set with
        `itemReviewed` and `isBasedOn`, on a reason written about the reviewed subject.
        A DOI resolves the cited paper, never the citing page.
        """
        result = self._ld({
            "@type": "Article", "name": "A piece",
            "citation": {"@type": "ScholarlyArticle", "name": "The paper",
                         "sameAs": ["https://doi.org/10.0000/paper"]}})
        self.assertEqual(result["entity_signals"]["sameAs"], [])
        self.assertNotIn("The paper", result["entity_signals"]["names"])

    def test_four_cited_works_no_longer_take_the_whole_entity_component(self):
        """The measurement this release was decided on.

        Five points per `sameAs` and a cap of twenty: four cited works took the entire
        component — a third of the floor of 60 that GO-145 and GEO-005 assert, both
        `high` — for identifiers belonging to somebody else's work.
        """
        cited = [{"@type": "ScholarlyArticle", "name": f"Paper {index}",
                  "sameAs": [f"https://doi.org/10.0000/paper{index}"]}
                 for index in range(4)]
        result = self._ld({"@type": "Article", "name": "A piece",
                           "citation": cited})
        self.assertEqual(result["entity_signals"]["sameAs"], [])

    def test_a_declared_citation_counts_as_citation_capacity(self):
        """And it is moved rather than deleted.

        `claim_coverage` reads `cite`, `blockquote` and footnote links out of the DOM
        and has never read JSON-LD, so dropping the key with no new home would make a
        machine-readable bibliography worth nothing on an item about citation
        readiness. Both pages below make the same single factual claim; only the second
        declares where it comes from.
        """
        claim = '<p>A 2025 study found that warm dough rises.</p>'
        bare = self._check_html(
            '<!doctype html><html><head><title>t</title></head><body>'
            + claim + '</body></html>')
        declared = self._check_html(
            '<!doctype html><html><head><title>t</title>'
            '<script type="application/ld+json">' + json.dumps({
                "@type": "Article", "name": "A piece",
                "citation": {"@type": "ScholarlyArticle", "name": "The paper"}})
            + '</script></head><body>' + claim + '</body></html>')
        self.assertEqual(bare["citation_signals"]["schema_citations"], 0)
        self.assertEqual(declared["citation_signals"]["schema_citations"], 1)
        self.assertGreater(declared["score"], bare["score"])

    def test_a_citation_inside_a_customers_review_is_not_the_pages(self):
        """The count is read through the same boundary as the entity signals."""
        result = self._ld({
            "@type": "Product", "name": "Tin",
            "review": {"@type": "Review",
                       "citation": {"@type": "ScholarlyArticle", "name": "Theirs"}}})
        self.assertEqual(result["citation_signals"]["schema_citations"], 0)

    def test_the_same_work_cited_twice_counts_twice(self):
        """Deliberate, and it is here so that a later dedup is a decision.

        Two `<cite>` tags naming one source count twice, and so do two links to one
        URL. All four sources feed one `citation_capacity`; deduplicating the schema
        one alone would make it the odd source out.
        """
        paper = {"@type": "ScholarlyArticle", "name": "A",
                 "sameAs": ["https://doi.org/10.0/a"]}
        result = self._ld({"@type": "Article", "name": "P",
                           "citation": [paper, dict(paper)]})
        self.assertEqual(result["citation_signals"]["schema_citations"], 2)

    def test_a_citation_under_an_excluded_key_is_not_readmitted_by_a_declaration(self):
        """The exemption is an `@id` mechanism, and this is where that shows.

        The review below declares itself the page's own subject through
        `mainEntityOfPage`, and its citation is still not counted: the node is written
        out in place rather than hoisted, so it carries no `@id` for `page_own_ids` to
        name. A reader who expects `protected` to reopen a nested subtree will find
        this test rather than a wrong number in a report.
        """
        result = self._ld({
            "@type": "Product", "name": "T",
            "review": {"@type": "Review", "name": "R",
                       "mainEntityOfPage": "https://example.com/p",
                       "citation": {"@type": "ScholarlyArticle", "name": "A"}}})
        self.assertEqual(result["citation_signals"]["schema_citations"], 0)

    def test_a_work_the_page_is_based_on_is_still_its_subject(self):
        """`isBasedOn` keeps its place beside `itemReviewed`.

        A derivative work's subject is the work it derives from, which is 0.68's reason
        and not a new one. This is the test that fails an implementation that answers
        the release by excluding every subject key.
        """
        result = self._ld({
            "@type": "Article", "name": "A piece",
            "isBasedOn": {"@type": "ScholarlyArticle", "name": "The paper",
                          "sameAs": ["https://doi.org/10.0000/paper"]}})
        self.assertEqual(result["entity_signals"]["sameAs"],
                         ["https://doi.org/10.0000/paper"])

    def test_a_reviewed_works_title_is_not_an_author(self):
        result = self._ld({
            "@type": "Review",
            "itemReviewed": {"@type": "Book", "name": "Moby Dick"},
        })
        self.assertEqual(result["entity_signals"]["names"], ["Moby Dick"])
        self.assertEqual(result["score"], 0)
        self.assertIn(self.AUTHOR_FINDING, self._messages(result))


class ArticleAuthorAndDate(unittest.TestCase):
    @staticmethod
    def _json_ld(document):
        return ('<script type="application/ld+json">' + json.dumps(document) +
                '</script>')

    @classmethod
    def _content(cls, markup):
        import article_seo
        from seo_common import parse_html
        parsed = parse_html('<!doctype html><html><head></head><body>' + markup +
                            '</body></html>')
        return article_seo.extract_content(parsed, "generic")

    @staticmethod
    def _conflicts(content):
        import article_seo
        issues = article_seo.detect_seo_issues(content, [], {"word_count": 1000})
        return [issue for issue in issues
                if issue.get("area") == "Freshness"
                and issue.get("severity") == "Warning"]

    def test_a1_an_author_grid_is_not_an_author(self):
        content = self._content(
            '<div class="author-grid">Meet the team<span>Recipes by many hands</span></div>')
        self.assertEqual(content["authors"], [])

    def test_a2_json_ld_author_is_read(self):
        content = self._content(self._json_ld({
            "@type": "Article", "author": {"@type": "Person", "name": "A Fixture"},
        }))
        self.assertEqual(content["authors"], ["A Fixture"])

    def test_a3_a_commenter_byline_is_not_the_author(self):
        content = self._content(
            '<div itemprop="comment"><p class="byline">D Petras</p></div>')
        self.assertEqual(content["authors"], [])

    def test_a4_author_meta_is_read(self):
        content = self._content('<meta name="author" content="A Baker">')
        self.assertEqual(content["authors"], ["A Baker"])

    def test_a5_a_reviewed_works_author_is_not_the_author(self):
        content = self._content(
            '<div itemprop="itemReviewed"><span class="author">Herman Melville</span></div>')
        self.assertEqual(content["authors"], [])

    def test_a6_an_exact_byline_class_is_read(self):
        content = self._content('<p class="byline">M Kazlauskiene</p>')
        self.assertEqual(content["authors"], ["M Kazlauskiene"])

    def test_a7_rel_author_is_read(self):
        content = self._content('<a rel="author">A Fixture Baker</a>')
        self.assertEqual(content["authors"], ["A Fixture Baker"])

    def test_d1_a_published_widget_is_not_a_publication_date(self):
        content = self._content(
            '<div class="published-widget"><p>Newsletter</p><p>Sign up</p></div>')
        self.assertEqual(content["publish_date"], "")

    def test_d2_json_ld_publication_date_is_read(self):
        content = self._content(self._json_ld({
            "@type": "Article", "datePublished": "2026-07-01",
        }))
        self.assertEqual(content["publish_date"], "2026-07-01")

    def test_d3_property_published_time_is_read(self):
        content = self._content(
            '<meta property="article:published_time" content="2026-07-01">')
        self.assertEqual(content["publish_date"], "2026-07-01")

    def test_d4_name_published_time_stays_read(self):
        content = self._content(
            '<meta name="article:published_time" content="2026-07-01">')
        self.assertEqual(content["publish_date"], "2026-07-01")

    def test_d5_a_commenters_publication_date_is_not_the_pages(self):
        content = self._content(
            '<div itemprop="comment"><time itemprop="datePublished" '
            'datetime="2019-01-01"></time></div>')
        self.assertEqual(content["publish_date"], "")

    def test_d6_the_pages_microdata_publication_date_stays_read(self):
        content = self._content(
            '<time itemprop="datePublished" datetime="2026-08-01"></time>')
        self.assertEqual(content["publish_date"], "2026-08-01")

    def test_d7_a_bare_time_is_not_a_declared_publication_date(self):
        content = self._content(
            '<p>Published <time datetime="2026-07-18">18 July 2026</time></p>')
        self.assertEqual(content["publish_date"], "")

    def test_d8_a_nested_citation_date_is_not_the_pages(self):
        content = self._content(self._json_ld({
            "@type": "Article",
            "citation": {"@type": "ScholarlyArticle", "datePublished": "1998-01-01"},
        }))
        self.assertEqual(content["publish_date"], "")

    def test_a_published_time_meta_under_a_foreign_credit_is_not_the_pages(self):
        content = self._content(
            '<div itemprop="comment"><meta property="article:published_time" '
            'content="2019-01-01"></div>')
        self.assertEqual(content["publish_date"], "")

    def test_a_hoisted_citation_date_is_not_the_pages(self):
        content = self._content(self._json_ld({"@graph": [
            {"@id": "#page", "@type": "Article", "citation": {"@id": "#paper"}},
            {"@id": "#paper", "@type": "ScholarlyArticle",
             "datePublished": "1998-01-01"},
        ]}))
        self.assertEqual(content["publish_date"], "")

    def test_itemprop_is_an_exact_token_list(self):
        content = self._content(
            '<time itemprop="startDate datePublished" datetime="2026-08-01"></time>')
        self.assertEqual(content["publish_date"], "2026-08-01")
        content = self._content(
            '<time itemprop="datePublishedX" datetime="2026-08-01"></time>')
        self.assertEqual(content["publish_date"], "")

    def test_conflicting_declarations_warn_but_equal_declarations_do_not(self):
        schema = self._json_ld({
            "@type": "Article", "datePublished": "2026-07-01",
        })
        content = self._content(
            schema + '<meta property="article:published_time" content="2026-09-09">')
        self.assertEqual(content["publish_date"], "2026-07-01")
        conflicts = self._conflicts(content)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("2026-07-01", conflicts[0]["finding"])
        self.assertIn("2026-09-09", conflicts[0]["finding"])

        same = self._content(
            schema + '<meta property="article:published_time" content="2026-07-01">')
        self.assertEqual(self._conflicts(same), [])

    def test_the_json_contract_uses_an_author_list(self):
        result = out("article")
        self.assertIsInstance(result["authors"], list)
        self.assertNotIn("author", result)

    def test_the_exemplary_article_reports_its_declared_author_and_date(self):
        result = out("article_fixture_post")
        self.assertEqual(result["authors"], ["A Fixture"])
        self.assertEqual(result["publish_date"], "2026-07-01")
        findings = [issue["finding"] for issue in result["seo_issues"]]
        self.assertNotIn("No author attribution detected.", findings)
        self.assertNotIn("No publish date detected in markup.", findings)

    def test_bare_time_fixture_pages_still_have_no_declared_publication_date(self):
        for key in ("article_fixture_about", "article_fixture_index",
                    "article_fixture_privacy"):
            with self.subTest(key=key):
                result = out(key)
                self.assertEqual(result["publish_date"], "")
                self.assertIn("No publish date detected in markup.",
                              [issue["finding"] for issue in result["seo_issues"]])


class ArticleKeyword(unittest.TestCase):
    """KW-076 `keyword_usage.in_body`."""

    def test_a_supplied_keyword_present_in_body_passes(self):
        """`--no-autocomplete` because the script otherwise asks Google for related
        terms, and this suite does not leave loopback."""
        result = out("article_keyword_present")
        self.assertEqual(result["keyword_usage"]["keyword"], "sourdough starter")
        self.assertGreater(result["keyword_usage"]["body_occurrences"], 0)
        self.assertEqual(verdict("KW-076", result), PASS)

    def test_a_supplied_keyword_absent_from_body_fails_and_names_the_keyword(self):
        result = out("article_keyword_absent")
        self.assertEqual(result["keyword_usage"]["body_occurrences"], 0)
        self.assertEqual(verdict("KW-076", result), FAIL)
        check = ITEMS["KW-076"]["check"]
        _, evidence = evaluate(check["assert"], result)
        self.assertIn("technical SEO", evidence)

    def test_an_unfetched_page_has_no_measurement_and_is_undecided(self):
        result = out("article_unfetched")
        self.assertNotIn("keyword_usage", result)
        self.assertEqual(verdict("KW-076", result), NO_DATA)

    def test_no_keyword_input_stops_the_item_at_the_plan(self):
        item = ITEMS["KW-076"]
        plan, skipped = build_plan([item], {"url": GOOD.url}, {"fetch"}, "page")
        self.assertEqual(plan, {})
        self.assertEqual(skipped["KW-076"][0], NEEDS_INPUT)
        self.assertIn("--keyword", skipped["KW-076"][1])

    def test_a_substring_inside_a_longer_word_does_not_match(self):
        result = out("article_keyword_substring")
        self.assertIn("Seoul", " ".join(result["paragraphs"]))
        self.assertEqual(result["keyword_usage"]["body_occurrences"], 0)
        self.assertEqual(verdict("KW-076", result), FAIL)

    def test_keyword_matching_is_case_insensitive(self):
        result = out("article_keyword_case")
        self.assertEqual(result["keyword_usage"]["keyword"], "SEO Audit")
        self.assertEqual(verdict("KW-076", result), PASS)

    def test_no_keyword_flag_emits_no_usage_measurement(self):
        result = out("article")
        self.assertTrue(result["target_keyword"])
        self.assertNotIn("keyword_usage", result)

    def test_a_page_with_almost_no_prose_yields_none(self):
        """Keep the independent target-keyword fallback contract unchanged."""
        self.assertNotIn("target_keyword", out("article_bad"))
        self.assertNotIn("keyword_usage", out("article_bad"))

    def test_lithuanian_stopwords_leave_a_content_phrase(self):
        import article_seo
        text = "pas mus gardūs šašlykai. pas mus gardūs šašlykai."
        self.assertEqual(article_seo.extract_keywords_frequency(text, lang="lt"),
                         ["gardūs šašlykai"])

    def test_russian_words_are_extracted_and_its_stopwords_removed(self):
        import article_seo
        text = "у нас вкусные шашлыки. у нас вкусные шашлыки."
        self.assertEqual(article_seo.extract_keywords_frequency(text, lang="ru"),
                         ["вкусные шашлыки"])

    def test_a_language_list_is_not_applied_to_another_language(self):
        import article_seo
        text = "pas pas pas pas"
        self.assertEqual(article_seo.extract_keywords_frequency(text, lang="lt"), [])
        self.assertTrue(article_seo.extract_keywords_frequency(text, lang="en"))

    def test_the_page_declares_which_language_list_to_use(self):
        import article_seo
        soup = article_seo.BeautifulSoup('<html lang="lt-LT"></html>', "html.parser")
        self.assertEqual(article_seo.page_language(soup), "lt")


class TopicalClusters(unittest.TestCase):
    """AR-153 `score`."""

    def test_a_single_topic_site_scores_as_coherent(self):
        self.assertEqual(verdict("AR-153", out("clusters")), PASS)


class CollectionPage(unittest.TestCase):
    """AR-154 `issues`, read by severity rather than by wording."""

    def test_a_page_with_copy_raises_nothing_serious(self):
        self.assertEqual(verdict("AR-154", out("collection")), PASS)

    def test_a_thin_collection_page_warns(self):
        bad = out("collection_bad")
        self.assertEqual(verdict("AR-154", bad), WARN)
        self.assertIn("warning", [i["severity"] for i in bad["issues"]])


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

class ImageInventory(unittest.TestCase):
    """CI-016 and MD-186 `missing_alt`, CN-054 `summary.lazy_lcp_candidates`,
    MD-184 `count`."""

    def test_images_with_alt_text_pass_both_alt_items(self):
        good = out("images")
        self.assertEqual(good["missing_alt"], 0)
        for item_id in ("CI-016", "MD-186"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_a_missing_and_an_empty_alt_are_counted_separately(self):
        bad = out("images_bad")
        self.assertEqual(bad["missing_alt"], 1)
        self.assertEqual(bad["empty_alt"], 1)
        for item_id in ("CI-016", "MD-186"):
            self.assertEqual(verdict(item_id, bad), FAIL, item_id)

    def test_an_img_without_src_is_skipped_and_reported(self):
        import tempfile
        import image_inventory
        html = """<!doctype html><html><body>
        <img src="informative.jpg">
        <img src="decoration.svg" alt="">
        <img id="lightbox" alt="">
        </body></html>"""
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            result = image_inventory.inventory(path)
        finally:
            os.unlink(path)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["missing_alt"], 1)
        self.assertEqual(result["empty_alt"], 1)
        self.assertEqual(result["skipped_no_src"], 1)

    def test_a_native_lazy_hero_remains_discoverable_without_an_unread_counter(self):
        self.assertEqual(verdict("CN-054", out("images")), PASS)
        lazy = out("images_lazy")
        self.assertNotIn("lazy_lcp_performance_candidates", lazy["summary"])
        self.assertEqual(lazy["summary"]["lazy_lcp_candidates"], 0)
        self.assertEqual(verdict("CN-054", lazy), PASS)

    def test_a_js_deferred_image_without_native_source_is_not_discoverable(self):
        import tempfile
        import image_inventory
        html = """<!doctype html><html><body>
        <img data-src="hero.jpg" width="800" height="400" class="lazy">
        </body></html>"""
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            result = image_inventory.inventory(path)
        finally:
            os.unlink(path)
        self.assertEqual(result["summary"]["lazy_lcp_candidates"], 1)
        self.assertIs(result["images"][0]["discoverable"], False)
        self.assertEqual(verdict("CN-054", result), FAIL)

    def test_the_image_count_is_the_count(self):
        self.assertEqual(verdict("MD-184", out("images")), PASS)
        self.assertEqual(out("images_bad")["count"], 2)

    def image_free(self) -> dict:
        import tempfile
        import image_inventory
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("<!doctype html><html><body><p>No images here.</p>"
                     "</body></html>")
            path = fh.name
        try:
            return image_inventory.inventory(path)
        finally:
            os.unlink(path)

    def test_an_image_free_page_decides_none_of_the_four_image_items(self):
        """The twin of `test_an_image_free_page_does_not_fail_responsive_images`
        in `test_evidence.py`, which `image_weight_audit.py` has passed since 0.45.

        Emitted as zero, these three fields answered four items about images for a
        page that has none: a FAIL for MD-184 and a free PASS for the other three.
        Under `--sample 3` the FAIL was the one that showed — on the *good* fixture,
        whose `/about.html` and `/privacy.html` carry no image at all.
        """
        result = self.image_free()
        for field in ("count", "missing_alt"):
            self.assertNotIn(field, result, field)
        self.assertNotIn("lazy_lcp_candidates", result["summary"])
        for item_id in ("MD-184", "CI-016", "MD-186", "CN-054"):
            self.assertEqual(verdict(item_id, result), NO_DATA, item_id)

    def test_an_image_free_page_emits_these_keys_and_no_others(self):
        """Only the three fields the registry reads as a verdict are withheld. A
        page describing itself as having zero images is a fact; an item claiming
        its images are fine is not.

        The assertion is the whole key set rather than the fields I kept, and that
        is the point: naming only the survivors passes just as happily with the
        repair reverted, because the repair did not touch how any of them is
        populated. A set fails in both directions — an extra key means a verdict
        field came back, a missing one means the next repair withheld too much.
        """
        result = self.image_free()
        self.assertEqual(set(result), {"url", "empty_alt", "skipped_no_src",
                                       "summary", "issues", "images",
                                       "fetch_error"})
        self.assertEqual(set(result["summary"]),
                         {"images", "empty_alt", "skipped_no_src"})
        self.assertEqual(result["summary"]["images"], 0)
        self.assertEqual(result["empty_alt"], 0)
        self.assertEqual(result["skipped_no_src"], 0)
        self.assertEqual(result["images"], [])
        self.assertEqual(result["issues"], [])


class VideoSchema(unittest.TestCase):
    """MD-188, MD-190 and MB-102, all `issues` by severity."""

    def test_a_videoobject_missing_publisher_warns_rather_than_passing(self):
        video = out("video")
        self.assertIn("warning", [i["severity"] for i in video["issues"]])
        self.assertEqual(verdict("MD-190", video), WARN)

    def test_a_page_with_no_video_reports_zero_for_the_applicability_rule(self):
        self.assertEqual(out("video_bad")["videos"], 0)


# ---------------------------------------------------------------------------
# Structured data
# ---------------------------------------------------------------------------

class SchemaRequiredProps(unittest.TestCase):
    """MS-032 `summary.errors` and GO-143 `issues` by pattern."""

    def test_complete_schema_produces_no_errors(self):
        good = out("props")
        self.assertEqual(good["summary"]["errors"], 0)
        self.assertEqual(verdict("MS-032", good), PASS)

    def test_a_missing_required_property_and_unparsable_json_are_errors(self):
        bad = out("props_bad")
        self.assertGreaterEqual(bad["summary"]["errors"], 2)
        self.assertEqual(verdict("MS-032", bad), FAIL)

class RichResults(unittest.TestCase):
    """TE-172 `summary.errors`, TECH-001 `summary.warnings`."""

    def test_valid_schema_has_no_errors(self):
        self.assertEqual(verdict("TE-172", out("rich")), PASS)

    def test_broken_schema_blocks_rich_results(self):
        bad = out("rich_bad")
        self.assertGreaterEqual(bad["summary"]["errors"], 1)
        self.assertEqual(verdict("TE-172", bad), FAIL)


class Entities(unittest.TestCase):
    """GEO-006 `summary.sameas_missing_critical`."""

    def test_an_organisation_with_no_sameas_targets_is_unresolvable(self):
        """The contract pair exempts this item because verifying `sameAs` means
        fetching Wikidata, and this suite does not leave loopback. The *absence*
        side needs no egress, and that is what is asserted here."""
        entity = out("entity")
        self.assertGreater(entity["summary"]["sameas_missing_critical"], 0)
        self.assertEqual(verdict("GEO-006", entity), FAIL)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

class BrokenLinks(unittest.TestCase):
    """TE-168 `summary.broken_or_redirected`, warning on `summary.broken`."""

    def test_a_site_whose_links_all_resolve_passes(self):
        self.assertEqual(verdict("TE-168", out("broken")), PASS)

    def test_a_dead_internal_link_and_a_dead_host_are_both_found(self):
        bad = out("broken_bad")
        self.assertGreaterEqual(bad["summary"]["broken"], 1)
        self.assertEqual(verdict("TE-168", bad), WARN)

    def test_the_cap_is_declared_in_the_output(self):
        """It had none until 0.3.0, so a page with 4,000 links produced 4,000
        requests. `truncated` exists so a capped run cannot be read as a complete
        one."""
        self.assertIn("truncated", out("broken"))

    def test_redirects_warn_and_the_existing_broken_tolerance_survives(self):
        self.assertEqual(verdict("TE-168", {"summary": {
            "broken": 0, "redirected": 0, "broken_or_redirected": 0}}), PASS)
        self.assertEqual(verdict("TE-168", {"summary": {
            "broken": 0, "redirected": 12, "broken_or_redirected": 12}}), WARN)
        for broken in (1, 3):
            with self.subTest(broken=broken):
                self.assertEqual(verdict("TE-168", {"summary": {
                    "broken": broken, "redirected": 0,
                    "broken_or_redirected": broken}}), WARN)
        self.assertEqual(verdict("TE-168", {"summary": {
            "broken": 4, "redirected": 0, "broken_or_redirected": 4}}), FAIL)

    def test_inventory_counts_only_internal_redirect_targets(self):
        import broken_links
        inventory = {
            "site": "https://example.test/",
            "fetch_error": None,
            "summary": {"unique_internal_targets": 1, "truncated": False},
            "pages": {
                "https://example.test/": {
                    "links": [
                        {"target": "https://example.test/go", "internal": True,
                         "anchor": "Go", "nofollow": False},
                        {"target": "https://outside.test/go", "internal": False,
                         "anchor": "Away", "nofollow": False},
                    ],
                },
                "https://example.test/go": {
                    "url": "https://example.test/go",
                    "final_url": "https://example.test/there",
                    "status": 200,
                    "error": None,
                    "robots_blocked": False,
                    "redirect_chain": ["https://example.test/there"],
                    "links": [],
                },
            },
            # The crawl can report external activity elsewhere; this reader derives
            # its population from internal inbound targets and must ignore it.
            "redirected": [{"url": "https://outside.test/go",
                            "to": "https://outside.test/there", "hops": 1}],
        }
        result = broken_links.links_from_inventory(inventory)
        self.assertEqual(result["summary"]["redirected"], 1)
        self.assertEqual(result["summary"]["broken_or_redirected"], 1)
        self.assertEqual([row["url"] for row in result["redirected"]],
                         ["https://example.test/go"])
        self.assertTrue(all(row["is_internal"] for row in result["redirected"]))


class LocalSeoNap(unittest.TestCase):
    """LO-200 `nap_complete`."""

    def check_nodes(self, *nodes):
        import local_seo_checker
        scripts = "".join(
            '<script type="application/ld+json">'
            + json.dumps(node)
            + "</script>"
            for node in nodes
        )
        page = f"<html><head>{scripts}</head><body>Fixture page</body></html>"
        with harness.allow_loopback(), served({"/": page}) as site:
            return local_seo_checker.check_local_seo(site.url)

    @staticmethod
    def complete_node():
        return {
            "@context": "https://schema.org",
            "@type": "Bakery",
            "name": "Fixture Bakery",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "1 Fixture Street",
            },
            "telephone": "+370 5 000 0000",
        }

    def test_complete_name_address_and_telephone_pass(self):
        result = self.check_nodes(self.complete_node())
        self.assertTrue(result["nap_complete"])
        self.assertEqual(verdict("LO-200", result), PASS)

    def test_missing_telephone_fails(self):
        node = self.complete_node()
        del node["telephone"]
        result = self.check_nodes(node)
        self.assertFalse(result["nap_complete"])
        self.assertEqual(verdict("LO-200", result), FAIL)

    def test_missing_name_fails(self):
        node = self.complete_node()
        del node["name"]
        result = self.check_nodes(node)
        self.assertFalse(result["nap_complete"])
        self.assertEqual(verdict("LO-200", result), FAIL)

    def test_missing_address_fails(self):
        node = self.complete_node()
        del node["address"]
        result = self.check_nodes(node)
        self.assertFalse(result["nap_complete"])
        self.assertEqual(verdict("LO-200", result), FAIL)

    def test_one_incomplete_node_makes_two_nodes_incomplete(self):
        incomplete = self.complete_node()
        incomplete["@type"] = "Restaurant"
        del incomplete["telephone"]
        result = self.check_nodes(self.complete_node(), incomplete)
        self.assertFalse(result["nap_complete"])
        self.assertEqual(verdict("LO-200", result), FAIL)

    def test_a_page_without_local_business_data_has_no_nap_verdict(self):
        result = self.check_nodes()
        self.assertNotIn("nap_complete", result)
        self.assertEqual(verdict("LO-200", result), NO_DATA)

    def test_a_page_without_local_business_data_has_only_info_findings(self):
        result = self.check_nodes()
        self.assertTrue(result["issues"])
        self.assertEqual({row["severity"] for row in result["issues"]}, {"info"})


class LocalBusinessInventory(unittest.TestCase):
    def test_site_crawl_keeps_a_type_declared_only_inside_a_comment(self):
        import site_crawl
        page = ('<html><body><div itemprop="comment">'
                '<script type="application/ld+json">'
                '{"@type":"CommentOnlyType"}</script></div></body></html>')
        routes = {
            "/": page,
            "/robots.txt": (200, "User-agent: *\nAllow: /\n"),
        }
        with harness.allow_loopback(), served(routes) as site:
            inventory = site_crawl.crawl(site.url, use_sitemap=False, workers=1)
        self.assertEqual(
            inventory["pages"][site.url]["schema_nodes"],
            [{"types": ["CommentOnlyType"]}],
        )

    def test_lo_198_finds_a_contact_page_node_when_the_entry_has_none(self):
        import local_seo_checker
        import site_crawl
        home = '<html><body><a href="/contact">Contact</a></body></html>'
        contact = ('<html><head><script type="application/ld+json">'
                   '{"@context":"https://schema.org","@type":"Restaurant",'
                   '"name":"Fixture"}</script></head><body>Contact</body></html>')
        routes = {
            "/": home,
            "/contact": contact,
            "/robots.txt": (200, "User-agent: *\nAllow: /\n"),
        }
        with harness.allow_loopback(), served(routes) as site:
            inventory = site_crawl.crawl(site.url, use_sitemap=False, workers=1)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                             delete=False) as handle:
                json.dump(inventory, handle)
                handle.flush()
                path = handle.name
            try:
                result = local_seo_checker.check_local_business_inventory(
                    site.url, path)
            finally:
                os.unlink(path)

        self.assertEqual(inventory["pages"][site.url]["schema_nodes"], [])
        contact_row = inventory["pages"][site.base + "/contact"]
        self.assertEqual(contact_row["schema_nodes"], [{"types": ["Restaurant"]}])
        self.assertEqual(result["scope"], "site")
        self.assertEqual(result["pages_checked"], 2)
        self.assertEqual(result["local_business_nodes"], 1)
        self.assertEqual(result["local_business_pages"], [site.base + "/contact"])
        self.assertEqual(verdict("LO-198", result), PASS)
        self.assertEqual(verdict("LO-198", dict(result, local_business_nodes=0)),
                         FAIL)

        check = ITEMS["LO-198"]["check"]
        self.assertEqual(check["requires"], "crawl")
        self.assertEqual(check["args"], ["{url}", "--inventory", "{inventory_json}"])
        from checklist_runner import is_page_level
        self.assertFalse(is_page_level({"check": check}))
        self.assertEqual(ITEMS["LO-200"]["check"]["requires"], "fetch")


class ExternalLinks(unittest.TestCase):
    """BL-083 `summary.broken_links`."""

    def test_links_that_resolve_are_not_broken(self):
        self.assertEqual(verdict("BL-083", out("extlinks")), PASS)

    def test_a_host_that_does_not_resolve_counts_as_broken(self):
        """The gap this closed. The test was `status >= 400`, and a dead domain
        produces no status at all — so the *ordinary* form of external link rot was
        the one form this check could not see, and a page of links to expired domains
        reported zero broken links.
        """
        bad = out("extlinks_bad")
        self.assertGreaterEqual(bad["summary"]["unreachable_links"], 1)
        self.assertEqual(verdict("BL-083", bad), FAIL)

    def test_a_timeout_is_not_called_broken(self):
        """It is a fact about this run, not about the link. Kept in its own count so
        a slow host does not arrive in a fix list as a dead one."""
        self.assertIn("unchecked_links", out("extlinks")["summary"])


class AnchorText(unittest.TestCase):
    """BL-081 `summary.overused_exact_match_targets`."""

    def test_varied_navigation_anchors_are_not_overused(self):
        self.assertEqual(verdict("BL-081", out("anchor")), PASS)

    def test_five_identical_anchors_to_one_target_are(self):
        spam = out("anchor_spam")
        self.assertGreaterEqual(spam["summary"]["overused_exact_match_targets"], 1)
        self.assertEqual(verdict("BL-081", spam), WARN)


class InternalLinks(unittest.TestCase):
    """AR-149 `pages`."""

    def test_the_crawl_reports_incoming_and_outgoing_counts_per_page(self):
        pages = out("intlinks")["pages"]
        self.assertTrue(pages)
        self.assertEqual(verdict("AR-149", out("intlinks")), PASS)
        first = next(iter(pages.values()))
        self.assertIn("incoming_links", first)
        self.assertIn("outgoing_links", first)


class LinkProfile(unittest.TestCase):
    """CI-008 `orphan_pages.count`, AR-162 `issues`."""

    def profile_from_inventory(self, links_by_path):
        origin = "https://example.test"
        pages = {}
        for path, targets in links_by_path.items():
            url = f"{origin}{path}"
            pages[url] = {
                "html": True,
                "links": [{
                    "target": (target if target.startswith("http")
                               else f"{origin}{target}"),
                    "anchor": target,
                    "internal": not target.startswith("http"),
                } for target in targets],
            }
        inventory = {
            "inventory_version": 4,
            "site": f"{origin}/",
            "entry": f"{origin}/",
            "pages": pages,
            "robots_blocked": {},
        }
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "inventory.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(inventory, handle)
            proc = harness.spawn(
                [sys.executable, os.path.join(SCRIPTS, "link_profile.py"),
                 f"{origin}/", "--inventory", path, "--json"],
                env=script_env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_a_site_whose_pages_all_link_to_each_other_has_no_orphans(self):
        good = out("profile")
        self.assertEqual(good["orphan_pages"]["count"], 0)
        self.assertEqual(verdict("CI-008", good), PASS)
        self.assertEqual(verdict("AR-162", good), PASS)

    def test_sitemap_pages_nothing_links_to_are_orphans(self):
        bad = out("profile_bad")
        self.assertGreaterEqual(bad["orphan_pages"]["count"], 1)
        self.assertEqual(verdict("CI-008", bad), FAIL)
        self.assertEqual(verdict("AR-162", bad), FAIL)

    def test_a_page_with_no_outbound_internal_links_fails_on_the_dead_end(self):
        profile = self.profile_from_inventory({
            "/": ["/a", "/b", "/dead", "/a"],
            "/a": ["/", "/b", "/dead", "/b"],
            "/b": ["/", "/a", "/dead", "/a"],
            "/dead": ["https://outside.example/source"],
        })
        self.assertEqual(profile["orphan_pages"]["count"], 0)
        self.assertGreaterEqual(profile["avg_internal_links_per_page"], 3)
        self.assertEqual([issue["type"] for issue in profile["issues"]],
                         ["dead_end_pages"])
        self.assertEqual(verdict("AR-162", profile), FAIL)

    def test_no_orphans_no_dead_ends_and_a_healthy_average_passes(self):
        profile = self.profile_from_inventory({
            "/": ["/a", "/b", "/a"],
            "/a": ["/", "/b", "/"],
            "/b": ["/", "/a", "/"],
        })
        self.assertEqual(profile["orphan_pages"]["count"], 0)
        self.assertEqual(profile["dead_end_pages"]["count"], 0)
        self.assertGreaterEqual(profile["avg_internal_links_per_page"], 3)
        self.assertEqual(verdict("AR-162", profile), PASS)

    def test_an_orphan_still_fails_the_internal_linking_item(self):
        profile = self.profile_from_inventory({
            "/": ["/a", "/b", "/a"],
            "/a": ["/", "/b", "/"],
            "/b": ["/", "/a", "/"],
            "/orphan": ["/", "/a", "/b"],
        })
        self.assertEqual(profile["dead_end_pages"]["count"], 0)
        self.assertEqual([issue["type"] for issue in profile["issues"]],
                         ["orphan_pages"])
        self.assertEqual(verdict("AR-162", profile), FAIL)

    def test_ci_008_ignores_dead_ends_and_reads_only_the_orphan_count(self):
        profile = self.profile_from_inventory({
            "/": ["/a", "/b", "/dead", "/a"],
            "/a": ["/", "/b", "/dead", "/b"],
            "/b": ["/", "/a", "/dead", "/a"],
            "/dead": [],
        })
        self.assertEqual(profile["dead_end_pages"]["count"], 1)
        self.assertEqual(verdict("AR-162", profile), FAIL)
        self.assertEqual(verdict("CI-008", profile), PASS)


class FacetedNavigation(unittest.TestCase):
    """AR-163 `issues`."""

    PAGE_URL_LIMIT = 3

    def from_page(self, internal_links: int) -> dict:
        links = "".join(f'<a href="/plain-{i}">plain</a>'
                        for i in range(internal_links))
        page = f"<html><body>{links}</body></html>"
        routes = {"/": page, **{f"/plain-{i}": page
                                for i in range(internal_links)}}
        with served(routes) as site:
            proc = harness.spawn(
                [sys.executable, os.path.join(SCRIPTS, "faceted_nav_audit.py"),
                 f"{site.base}/", "--from-page", "--fetch", "--max-urls",
                 str(self.PAGE_URL_LIMIT), "--json"],
                env=script_env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_a_site_with_no_parameter_urls_raises_nothing(self):
        self.assertEqual(verdict("AR-163", out("facets")), PASS)

    def test_six_parameter_variants_on_one_path_are_a_crawl_trap(self):
        """And the item could not fail until the registry passed `--from-page`. A trap
        is a property of a *set* of URLs — five variants sharing a path, or one
        parameter recurring three times — and the registry handed the script the entry
        URL alone, which supplies one of each.
        """
        self.assertIn("--from-page", ITEMS["AR-163"]["check"]["args"])
        bad = out("facets_bad")
        self.assertEqual(verdict("AR-163", bad), WARN)
        self.assertRegex(json.dumps(bad["issues"]), "(?i)parameter")

    def test_a_page_with_more_urls_than_the_limit_reports_truncation(self):
        result = self.from_page(self.PAGE_URL_LIMIT)
        self.assertEqual(result["count"], self.PAGE_URL_LIMIT)
        self.assertIs(result["truncated"], True)

    def test_a_page_with_fewer_urls_than_the_limit_reports_a_complete_input(self):
        result = self.from_page(self.PAGE_URL_LIMIT - 1)
        self.assertEqual(result["count"], self.PAGE_URL_LIMIT)
        self.assertIs(result["truncated"], False)

    def test_ar_163_withholds_only_the_clean_verdict_over_a_truncated_input(self):
        capped = self.from_page(self.PAGE_URL_LIMIT)
        complete = self.from_page(self.PAGE_URL_LIMIT - 1)
        self.assertEqual(graded_verdict("AR-163", capped), NO_DATA)
        self.assertEqual(graded_verdict("AR-163", complete), PASS)

    def test_robots_disallow_is_a_third_facet_control(self):
        """Checking only that the allowed facet errors would pass before this repair;
        the blocked URL's absence from the error evidence makes a revert fail.
        """
        page = "<html><head><title>Facet</title></head><body></body></html>"
        routes = {
            "/robots.txt": (200, {"Content-Type": "text/plain"},
                            "User-agent: *\nDisallow: /blocked\n"),
            "/blocked": page,
            "/allowed": page,
        }
        with served(routes) as site:
            blocked = f"{site.base}/blocked?color=red"
            allowed = f"{site.base}/allowed?color=red"
            proc = harness.spawn(
                [sys.executable, os.path.join(SCRIPTS, "faceted_nav_audit.py"),
                 blocked, allowed, "--fetch", "--json"],
                env=script_env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        errors = [issue for issue in result["issues"]
                  if issue["severity"] == "error"]
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["evidence"], [allowed])
        self.assertNotIn(blocked, errors[0]["evidence"])


# ---------------------------------------------------------------------------
# Speed, mobile, technical
# ---------------------------------------------------------------------------

class CacheAndCompression(unittest.TestCase):
    """TE-170 `issues`."""

    ASSET_LIMIT = 1

    def with_assets(self, asset_count: int) -> dict:
        assets = "".join(f'<script src="/asset-{i}"></script>'
                         for i in range(asset_count))
        routes = {
            "/": f"<html><body>{assets}</body></html>",
            **{f"/asset-{i}": "ok" for i in range(asset_count)},
        }
        with served(routes) as site:
            proc = harness.spawn(
                [sys.executable,
                 os.path.join(SCRIPTS, "cache_compression_checker.py"),
                 f"{site.base}/", "--include-assets", "--max-assets",
                 str(self.ASSET_LIMIT), "--json"],
                env=script_env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_asset_cap_reports_completeness_and_controls_the_clean_verdict(self):
        capped = self.with_assets(self.ASSET_LIMIT + 1)
        complete = self.with_assets(self.ASSET_LIMIT)
        self.assertIs(capped["truncated"], True)
        self.assertIs(complete["truncated"], False)
        self.assertEqual(capped["resources_checked"], self.ASSET_LIMIT + 1)
        self.assertEqual(complete["resources_checked"], self.ASSET_LIMIT + 1)
        self.assertEqual(graded_verdict("TE-170", capped), NO_DATA)
        self.assertEqual(graded_verdict("TE-170", complete), PASS)

    def test_uncompressed_text_is_graded_by_known_size(self):
        """A large-only assertion would still pass before this repair; the small and
        unknown-length branches make a revert fail as well as checking the high path.
        """
        bodies = {
            "/small": b"{" + (b" " * 298) + b"}",
            "/large": b"{" + (b" " * 1023) + b"}",
            "/unknown": b"{" + (b" " * 2046) + b"}",
        }

        class LengthHandler(http.server.BaseHTTPRequestHandler):
            def _respond(self, body_too):
                body = bodies[self.path]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Last-Modified", "Sat, 15 Aug 2026 12:00:00 GMT")
                if self.path != "/unknown":
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body_too:
                    self.wfile.write(body)

            def do_GET(self):
                self._respond(True)

            def do_HEAD(self):
                self._respond(False)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LengthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            rows = {}
            for label in ("small", "large", "unknown"):
                proc = harness.spawn(
                    [sys.executable,
                     os.path.join(SCRIPTS, "cache_compression_checker.py"),
                     f"{base}/{label}", "--json"],
                    env=script_env(), timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                rows[label] = json.loads(proc.stdout)["resources"][0]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        compression = {
            label: [issue for issue in row["issues"]
                    if issue["message"].startswith("Compressible response")]
            for label, row in rows.items()
        }
        self.assertEqual(compression["small"], [])
        self.assertEqual(compression["large"], [{
            "severity": "error",
            "message": "Compressible response is not Brotli/gzip encoded",
        }])
        self.assertEqual(compression["unknown"], [{
            "severity": "warning",
            "message": "Compressible response is not Brotli/gzip encoded "
                       "(length unknown)",
        }])

    def test_an_uncompressed_response_fails_with_the_reason(self):
        """Both directions now, which is new in 0.50.0.

        The docstring this replaces said "one direction only: nothing in this harness
        can make `http.server` send a `Content-Encoding`". That had stopped being a
        fact about the harness and become a fact about nobody having tried — the
        fixture server compresses for the good origins now, and the item that grades
        server configuration can tell a configured server from an unconfigured one.

        Text served uncompressed is graded `error` = high, so this is FAIL rather than
        the WARN it was: before, `cache_compression_checker.py` had no word above
        `warning` and TE-170 could not reach FAIL on any site in the world.
        """
        cache = out("cache")
        self.assertEqual(verdict("TE-170", cache), FAIL)
        self.assertRegex(json.dumps(cache["issues"]), "(?i)gzip|brotli|encod")

    def test_a_compressed_response_passes(self):
        """The other direction, which is what stops this being a check that can only
        ever accuse. Same page, same script, one server setting apart.

        Run against `FixtureSite` rather than this module's `served()` routes, because
        compression is a property of the origin and only the fixture pair has one
        origin that compresses and one that does not. As a subprocess with that
        origin's own environment, for the reason the whole file runs scripts that way:
        called in-process it inherits this process's environment, the private-address
        guard refuses 127.0.0.1, and every header comes back `None` — which reads
        exactly like a server that sends no `Content-Encoding`.
        """
        rows = {}
        with harness.FixtureSite() as fixture:
            for label in ("good", "broken"):
                proc = harness.spawn(
                    [sys.executable,
                     os.path.join(SCRIPTS, "cache_compression_checker.py"),
                     getattr(fixture, label), "--json"],
                    env=fixture.environment(label), timeout=120)
                rows[label] = json.loads(proc.stdout)
        self.assertEqual(rows["good"]["resources"][0]["content_encoding"], "gzip")
        self.assertIsNone(rows["broken"]["resources"][0]["content_encoding"])
        self.assertEqual(verdict("TE-170", rows["good"]), PASS)
        self.assertEqual(verdict("TE-170", rows["broken"]), FAIL)

    def test_good_fixture_honours_its_last_modified_validator(self):
        """An unconditional gzip assertion still passes without this repair; requiring
        the same request with the returned validator to become 304 makes a revert fail.
        """
        with harness.FixtureSite() as fixture:
            parsed = urlsplit(fixture.good)

            def request(headers):
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port,
                                                        timeout=10)
                try:
                    connection.request("GET", parsed.path or "/", headers=headers)
                    response = connection.getresponse()
                    result = response.status, dict(response.getheaders())
                    response.read()
                    return result
                finally:
                    connection.close()

            status, headers = request({"Accept-Encoding": "gzip"})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Content-Encoding"), "gzip")
            modified = headers["Last-Modified"]
            status, conditional_headers = request({
                "Accept-Encoding": "gzip",
                "If-Modified-Since": modified,
            })
        self.assertEqual(status, 304)
        self.assertNotIn("Content-Encoding", conditional_headers)


class CriticalChain(unittest.TestCase):
    """SP-110 `issues`."""

    def test_a_stylesheet_in_the_head_is_reported_and_no_longer_graded(self):
        """Still found, and `info` since 0.87.0.

        The finding is not withdrawn: a render-blocking stylesheet is worth telling an
        operator about, and the chain output still carries it. What changed is that it
        stopped deciding a verdict. `warning` aliases to medium, and SP-110 asserts
        against medium, so one ordinary stylesheet in the head — which every site has —
        left the item unable to report PASS anywhere. This test fails if that grading
        returns.
        """
        chain = out("chain")
        self.assertEqual(verdict("SP-110", chain), PASS)
        blocking = [issue for issue in chain["issues"]
                    if "render-blocking" in issue["message"].lower()]
        self.assertTrue(blocking)
        self.assertEqual({issue["severity"] for issue in blocking}, {"info"})

    def test_a_parser_blocking_script_in_the_head_still_fails_the_item(self):
        """The finding this script grades as a defect on every site, unchanged."""
        bad = out("chain_bad")
        self.assertEqual(verdict("SP-110", bad), FAIL)
        self.assertRegex(json.dumps(bad["issues"]), "(?i)parser-blocking script in")


class ThirdPartyScripts(unittest.TestCase):
    """SP-109 `blocking_third_party_count`."""

    def test_a_page_loading_only_its_own_scripts_has_none(self):
        self.assertEqual(out("thirdparty")["blocking_third_party_count"], 0)
        self.assertEqual(verdict("SP-109", out("thirdparty")), PASS)

    def test_synchronous_third_party_scripts_are_counted(self):
        bad = out("thirdparty_bad")
        self.assertGreaterEqual(bad["blocking_third_party_count"], 1)
        self.assertEqual(verdict("SP-109", bad), FAIL)


class CssMinification(unittest.TestCase):
    """TE-174 `unminified_count`."""

    def test_a_minified_stylesheet_is_not_counted(self):
        self.assertEqual(verdict("TE-174", out("cssmin")), PASS)

    def test_a_stylesheet_full_of_whitespace_and_comments_is(self):
        bad = out("cssmin_bad")
        self.assertEqual(bad["unminified_count"], 1)
        self.assertEqual(verdict("TE-174", bad), FAIL)
        self.assertGreater(bad["wasted_bytes"], 0)


class FontLoading(unittest.TestCase):
    """TECH-002 `issues`."""

    def test_a_page_loading_no_web_font_raises_nothing(self):
        """Fails if a page with no font face stops reading as clean."""
        self.assertEqual(verdict("TECH-002", out("fonts")), PASS)
        self.assertEqual(out("fonts")["font_face_count"], 0)

    def test_an_external_font_face_without_font_display_fails(self):
        """Fails if linked CSS is not read or its blocking face is not an error."""
        result = out("fonts_external_blocking")
        blocking = [issue for issue in result["issues"]
                    if issue["message"] == "@font-face missing font-display"]
        self.assertEqual([issue["severity"] for issue in blocking], ["error"])
        self.assertTrue(blocking[0]["url"].endswith("/font-blocking.css"))
        self.assertEqual(verdict("TECH-002", result), FAIL)

    def test_an_external_font_face_with_swap_passes(self):
        """Fails if a non-blocking face in linked CSS is graded as an error."""
        result = out("fonts_external_swap")
        self.assertFalse(any(issue["severity"] == "error" for issue in result["issues"]))
        self.assertEqual(verdict("TECH-002", result), PASS)

    def test_an_inline_font_face_without_font_display_still_fails(self):
        """Fails if adding linked-CSS support loses the existing inline path."""
        result = out("fonts_inline_blocking")
        self.assertIn("error", [issue["severity"] for issue in result["issues"]])
        self.assertEqual(verdict("TECH-002", result), FAIL)

    def test_an_unfetchable_stylesheet_is_not_clean(self):
        """Fails if unreadable linked CSS is mistaken for CSS with no font defect."""
        result = out("fonts_unfetchable")
        unreadable = [issue for issue in result["issues"]
                      if issue["message"] == "Stylesheet could not be fetched"]
        self.assertEqual([issue["severity"] for issue in unreadable], ["warning"])
        self.assertTrue(unreadable[0]["url"].endswith("/missing-fonts.css"))
        self.assertIn("404", unreadable[0]["evidence"])


class LcpSubparts(unittest.TestCase):
    """TECH-003 `subparts.ttfb_ms`."""

    def test_ttfb_is_measured_as_a_number_of_milliseconds(self):
        """Loopback answers in about a millisecond, so this can only ever pass here.
        What it does prove is that the field is measured rather than defaulted — a
        hard-coded 0 would make TECH-003 unable to fail on any site."""
        lcp = out("lcp")
        self.assertIsInstance(lcp["subparts"]["ttfb_ms"], (int, float))
        self.assertEqual(verdict("TECH-003", lcp), PASS)


class MobileRender(unittest.TestCase):
    """MB-100 `issues`."""

    @staticmethod
    def _check_html(fragment):
        import mobile_render_checker

        html = ("<!doctype html><html><head>"
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                f"</head><body>{fragment}</body></html>")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return mobile_render_checker.check_mobile_render(path)
        finally:
            os.unlink(path)

    def test_a_responsive_page_with_a_viewport_passes(self):
        self.assertEqual(verdict("MB-100", out("mobile")), PASS)

    def test_a_fixed_width_wider_than_a_phone_decides_failure(self):
        wide = out("mobile_wide")
        self.assertEqual(
            [(issue["severity"], issue["finding"]) for issue in wide["issues"]],
            [("warning", "Found 1 fixed-width CSS declarations wider than common "
                         "mobile viewports.")])
        self.assertEqual(verdict("MB-100", wide), FAIL)

    def test_fixed_width_detection_excludes_responsive_max_widths(self):
        cases = [
            ('sizes="(max-width: 600px) 100vw, 600px"', []),
            ("max-width: 600px", []),
            ("max-width:600px", []),
            ("@media (max-width: 900px)", []),
            ("width: 1200px", [1200]),
            ("width:1200px", [1200]),
            ("min-width: 900px", [900]),
            ("  WIDTH : 1024px", [1024]),
            ("grid-template-columns: 300px", []),
        ]
        for fragment, expected in cases:
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    self._check_html(fragment)["fixed_width_values"], expected)

    def test_sticky_positioning_alone_stays_unable_to_decide(self):
        sticky = out("mobile_sticky")
        self.assertEqual([issue["severity"] for issue in sticky["issues"]], ["info"])
        self.assertEqual(verdict("MB-100", sticky), PASS)

    def test_a_missing_viewport_is_critical(self):
        bad = out("mobile_bad")
        self.assertIn("critical", [i["severity"] for i in bad["issues"]])
        self.assertEqual(verdict("MB-100", bad), FAIL)

    def test_render_is_no_longer_a_python_api_argument(self):
        import mobile_render_checker

        parameters = inspect.signature(
            mobile_render_checker.check_mobile_render).parameters
        self.assertNotIn("render", parameters)
        with self.assertRaises(TypeError):
            mobile_render_checker.check_mobile_render(GOOD.url, render=True)

    def test_render_is_no_longer_a_cli_option(self):
        script = os.path.join(SCRIPTS, "mobile_render_checker.py")
        help_result = harness.spawn(
            [sys.executable, script, "--help"], env=script_env(), timeout=30)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("--render", help_result.stdout)

        rejected = harness.spawn(
            [sys.executable, script, GOOD.url, "--render", "--json"],
            env=script_env(), timeout=30)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("unrecognized arguments: --render", rejected.stderr)


class Accessibility(unittest.TestCase):
    """TE-180 `score`, CN-036 `checks.inline_contrast_candidates`."""

    def test_a_page_with_landmarks_alt_text_and_labels_scores(self):
        self.assertEqual(verdict("TE-180", out("a11y")), PASS)

    def test_the_contrast_check_reads_inline_styles_only_and_says_so(self):
        """Deliberately narrow: computing the cascade would mean rendering the page,
        and this script does not. So it counts inline styles that set both a colour
        and a background — which means a site whose contrast problem lives in a
        stylesheet is not covered, and `rendered_audit.py` is the answer to that."""
        self.assertEqual(out("a11y")["checks"]["inline_contrast_candidates"], 0)
        self.assertEqual(verdict("CN-036", out("a11y")), PASS)
        self.assertEqual(out("a11y_bad")["checks"]["inline_contrast_candidates"], 1)
        self.assertEqual(verdict("CN-036", out("a11y_bad")), FAIL)


class JavascriptRender(unittest.TestCase):
    """TE-169 `raw.internal_link_count`, TE-177 `raw.title`, MB-105 `diffs`.

    CN-053 read `raw.word_count` here until 0.22 and does not any more. Its title is
    *Avoid Critical Content in iFrames* and it counted words — nothing in the item
    observed an iframe, and this script reports no iframe signal of any kind, so a
    café was told to stop hiding content in frames it does not have because one page
    ran to 293 words. It is an LLM item on the layout lens now: whether the content
    that matters is inside a frame is a judgement about what matters.

    `raw.word_count` is consequently asserted by nothing. It stays in the output —
    it is real, and the report shows it — and thin content is CN-039's question,
    measured against the crawl rather than one page.
    """

    def test_no_artifact_is_no_measurement_not_parity(self):
        """Removing the omission would turn missing evidence into an MB-105 PASS."""
        result = out("jsrender")
        self.assertNotIn("diffs", result)
        self.assertIsNone(result["rendered"])
        self.assertEqual(result["render_error"], "no rendered artifact provided")
        self.assertEqual(verdict("MB-105", result), NO_DATA)

    def test_a_rendered_field_difference_fails_mb_105(self):
        """Losing artifact parsing would hide a measured served/rendered mismatch."""
        result = out("jsrender_diff")
        self.assertEqual(result["diffs"], [
            {
                "field": "title",
                "raw": "Sourdough starter care: feeding, reviving and storing",
                "rendered": "A rendered-only title",
            },
            {
                "field": "word_count",
                "raw": 324,
                "rendered": 320,
            },
        ])
        self.assertEqual(verdict("MB-105", result), FAIL)

    def test_a_matching_rendered_document_passes_mb_105(self):
        """Dropping an empty measured diff would make proven parity NO_DATA."""
        result = out("jsrender_match")
        self.assertEqual(result["diffs"], [])
        self.assertEqual(verdict("MB-105", result), PASS)

    def test_served_html_items_ignore_the_optional_artifact(self):
        """Pointing TE-169 or TE-177 at rendered data would make them input-dependent."""
        without = out("jsrender")
        for label in ("jsrender_match", "jsrender_diff"):
            with self.subTest(label):
                with_artifact = out(label)
                for item_id in ("TE-169", "TE-177"):
                    self.assertEqual(verdict(item_id, with_artifact),
                                     verdict(item_id, without), item_id)

    def test_the_raw_html_carries_the_content(self):
        good = out("jsrender")
        self.assertGreaterEqual(good["raw"]["word_count"], 300)
        for item_id in ("TE-169", "TE-177"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_no_item_grades_a_site_on_this_script_s_word_count(self):
        """The regression guard for the removal, not a formality: `raw.word_count`
        is still emitted, so re-pointing an item at it is one line away, and the
        next person to do it should have to argue with this test first."""
        rules = json.dumps([(i.get("check") or {}).get("assert") for i in ITEMS.values()])
        self.assertNotIn("raw.word_count", rules)

    def test_a_twenty_word_page_is_no_longer_this_script_s_business(self):
        """What CN-053 used to fail here, recorded rather than deleted.

        The page is twenty words with a cross-domain canonical and two h1s, and this
        script's raw-document items both pass it — correctly. It serves a title
        without JavaScript (TE-177) and carries eight internal links (TE-169). Neither
        verdict is about the page being thin, which is CN-039's question against the
        crawl. Asserting them keeps the run in use: an unasserted run is a script
        nobody checked, hiding behind a green suite.

        MB-105 is deliberately not asserted here: no rendered artifact was supplied,
        so there is no rendered document to compare.
        """
        bad = out("jsrender_bad")
        self.assertLess(bad["raw"]["word_count"], 300)
        for item_id in ("TE-169", "TE-177"):
            self.assertEqual(verdict(item_id, bad), PASS, item_id)

    def test_parity_is_absent_exactly_when_no_artifact_was_supplied(self):
        """Both unassisted CLI runs must carry the same explicit absence contract."""
        for label in ("jsrender", "jsrender_bad"):
            with self.subTest(label):
                result = out(label)
                rendered = result["rendered"] is not None
                self.assertEqual("diffs" in result, rendered,
                                 "diffs must be present exactly when a render happened")
                self.assertEqual(verdict("MB-105", result) != NO_DATA, rendered,
                                 "MB-105 must be NO_DATA exactly when nothing rendered")
                if not rendered:
                    self.assertTrue(result["render_error"],
                                    "an absent render must say why")


class Hreflang(unittest.TestCase):
    """IN-121 `checks.x_default.passed`, IN-127 `checks.url_structure.passed`,
    IN-128 `checks.self_reference.passed`, IN-122 `summary.critical`."""

    def test_correct_hreflang_passes_each_named_check(self):
        good = out("hreflang")
        for item_id in ("IN-121", "IN-128", "IN-122"):
            self.assertEqual(verdict(item_id, good), PASS, item_id)

    def test_in_122_evidence_is_a_verified_and_valid_return_set(self):
        good = out("hreflang")
        self.assertIs(good["checks"]["return_tags"]["verified_and_valid"], True)
        self.assertEqual(ITEMS["IN-122"]["check"]["assert"]["path"],
                         "checks.return_tags.verified_and_valid")

    def test_the_fixture_carries_no_locale_in_its_urls_so_in_127_declines(self):
        """The fixture's alternates are `/intl.html` and `/de.html` — filenames on one
        host, with the locale in neither the host, the first path segment nor a
        parameter. There is no international URL structure there to grade, so IN-127
        answers NO_DATA rather than crediting the fixture with one. The graded
        structures are exercised in `test_translated_sites.py`, against tag sets rather
        than against a served page, because what decides the item is where each locale
        sits in its own URL.
        """
        good = out("hreflang")
        self.assertEqual(good["checks"]["url_structure"]["structure"], "unmarked")
        self.assertEqual(verdict("IN-127", good), NO_DATA)

    def test_a_missing_x_default_fails_the_item_that_reads_it(self):
        self.assertIs(out("hreflang_bad")["checks"]["x_default"]["passed"], False)
        self.assertEqual(verdict("IN-121", out("hreflang_bad")), FAIL)

    def test_a_monolingual_page_is_undecided_rather_than_failed(self):
        """The distinction the whole coverage metric rests on. A single-language site
        has nothing to get wrong, so the script returns early and the three `checks.*`
        keys are absent — which the runner reads as NO_DATA. Reporting FAIL would
        invent a defect; reporting PASS would claim a check nobody ran."""
        none = out("hreflang_none")
        self.assertNotIn("x_default", none["checks"])
        self.assertIn("hreflang_present", none["checks"])
        for item_id in ("IN-121", "IN-127", "IN-128"):
            self.assertEqual(verdict(item_id, none), NO_DATA, item_id)


class Ga4(unittest.TestCase):
    """GO-131 `measurement_ids`, GO-132 `duplicates`."""

    def test_a_page_with_no_analytics_reports_no_measurement_id(self):
        self.assertEqual(out("ga4")["measurement_ids"], [])
        self.assertEqual(verdict("GO-131", out("ga4")), FAIL)

    def test_one_id_loaded_twice_is_a_duplicate(self):
        """The verdict this could not produce. `duplicates` counted only
        `gtag('config', …)` calls, and the ordinary way GA4 ends up installed twice is
        two copies of the *loader* — a theme and a plugin, or a hand-added tag beside
        GTM. So GO-132 "Prevent GA4 Tag Duplication" passed the exact situation it
        exists to catch, while the script's own `issues` list said "gtag.js loaded 2x"
        one field away.
        """
        bad = out("ga4_bad")
        self.assertEqual(verdict("GO-131", bad), PASS)
        self.assertEqual([d["kind"] for d in bad["duplicates"]], ["gtag_loader"])
        self.assertEqual(verdict("GO-132", bad), FAIL)


class SocialMeta(unittest.TestCase):
    """MS-033 `score`."""

    def test_a_full_open_graph_and_twitter_card_scores(self):
        self.assertEqual(verdict("MS-033", out("social")), PASS)

    def test_a_page_with_no_social_tags_scores_zero(self):
        self.assertEqual(out("social_bad")["score"], 0)
        self.assertEqual(verdict("MS-033", out("social_bad")), FAIL)


class OneCrawlForEveryoneWhoNeedsTheWholeSite(unittest.TestCase):
    """`site_crawl.py`, and GO-137 which reads it through the orphan check.

    The inventory is the one artifact this tool produces for itself rather than being
    handed, so unlike the browser traces it can be verified by re-running the thing
    that wrote it — which is what these do.
    """

    def test_the_crawl_records_a_status_for_every_page_it_reached(self):
        crawl = out("crawl")
        self.assertGreater(crawl["summary"]["pages_fetched"], 3)
        for key, row in crawl["pages"].items():
            self.assertIsNotNone(row["status"], key)
            self.assertIn("links", row)

    def test_the_request_count_is_reported_because_it_is_the_point(self):
        """Six scripts used to crawl independently — ~275 fetches, measured at 181
        against a seven-page fixture. A shared crawl that does not say what it cost
        cannot be checked against the thing it replaced."""
        crawl = out("crawl")
        self.assertGreater(crawl["summary"]["requests"], 0)
        self.assertLess(crawl["summary"]["requests"],
                        crawl["summary"]["pages_fetched"] + 10,
                        "the crawl is making requests it does not account for")

    def test_a_broken_page_is_named_with_the_pages_that_link_to_it(self):
        """The thing the report could never give anyone: which URL is broken, and
        which page to edit. A verdict about the site is not an address."""
        broken = out("crawl_bad")["broken"]
        self.assertTrue(broken, "the broken fixture's dead internal link was missed")
        dead = next(row for row in broken if row["url"].endswith("/gone"))
        self.assertEqual(dead["status"], 404)
        self.assertTrue(dead["linked_from"])

    def test_a_page_only_the_sitemap_mentions_is_not_reachable(self):
        """The distinction GO-137 is made of. The shared crawl *fetches* sitemap URLs,
        so "we got a status for it" cannot be what reachable means, or seeding from
        the sitemap would satisfy the orphan check by construction."""
        crawl = out("crawl_bad")
        orphan = f"{BAD.base}/unlinked-a.html"
        self.assertIn(orphan, crawl["pages"], "the sitemap URL was never fetched")
        self.assertNotIn(orphan, crawl["reachable"])
        self.assertGreaterEqual(out("orphans_bad")["summary"]["orphan_pages"], 1)
        self.assertEqual(verdict("GO-137", out("orphans_bad")), WARN)

    def test_a_site_whose_sitemap_matches_its_links_has_no_orphans(self):
        self.assertEqual(verdict("GO-137", out("orphans")), PASS)


class CrawlKeysAreNotFetchTargets(unittest.TestCase):
    """A page key deduplicates spellings; it is not necessarily a served URL."""

    def setUp(self):
        import site_crawl
        self.crawl = site_crawl
        self.loopback = harness.allow_loopback()
        self.loopback.__enter__()

    def tearDown(self):
        self.loopback.__exit__(None, None, None)

    def test_a_sitemap_url_is_fetched_with_the_slash_it_declared(self):
        sitemap = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   '<url><loc>PLACEHOLDER/about/</loc></url></urlset>')
        routes = {
            "/": "<html><body>Home</body></html>",
            "/about/": "<html><body>About</body></html>",
            "/about": (301, {"Location": "PLACEHOLDER/about/"}, ""),
            "/robots.txt": (200, "User-agent: *\nAllow: /\n"),
            "/sitemap.xml": (200, {"Content-Type": "application/xml"}, sitemap),
        }
        with harness.served(routes).rewrite("PLACEHOLDER") as site:
            result = self.crawl.crawl(
                site.url, sitemap_urls=[site.base + "/sitemap.xml"], workers=1)
            key = site.base + "/about"
            self.assertEqual(set(result["pages"]), {site.url, key})
            self.assertEqual(result["pages"][key]["url"], site.base + "/about/")
            self.assertNotIn("/about", site.paths())
            self.assertEqual(result["redirected"], [])

    def test_two_link_spellings_still_count_as_one_page(self):
        home = ('<html><body><a href="/about/">slash</a>'
                '<a href="/about">no slash</a></body></html>')
        routes = {
            "/": home,
            "/about/": "<html><body>About</body></html>",
            "/about": (301, {"Location": "PLACEHOLDER/about/"}, ""),
            "/robots.txt": (200, "User-agent: *\nAllow: /\n"),
        }
        with harness.served(routes).rewrite("PLACEHOLDER") as site:
            result = self.crawl.crawl(site.url, use_sitemap=False, workers=1)
            key = site.base + "/about"
            self.assertEqual(self.crawl.page_key(site.url), site.url)
            self.assertEqual(set(result["pages"]), {site.url, key})
            self.assertEqual(result["pages"][key]["url"], site.base + "/about/")
            self.assertEqual(site.paths().count("/about/"), 1)
            self.assertNotIn("/about", site.paths())

    def test_crawler_never_fetches_its_dedup_key_for_a_discovered_directory_slash(self):
        """Fail if the crawler regresses to fetching its normalized page key."""
        import tempfile
        import requests

        with tempfile.TemporaryDirectory(prefix="crawl-slash-source-") as source:
            good = os.path.join(source, "good")
            directory = os.path.join(good, "en")
            os.makedirs(directory)
            with open(os.path.join(good, "index.html"), "w", encoding="utf-8") as fh:
                fh.write('<html><body><a href="/en/">English</a></body></html>')
            with open(os.path.join(directory, "index.html"), "w",
                      encoding="utf-8") as fh:
                fh.write("<html><body>English</body></html>")

            with harness.FixtureSite(source=source) as fixture:
                key = fixture.origin("good") + "/en"
                canonical = requests.get(key, allow_redirects=False, timeout=5)
                self.assertEqual(canonical.status_code, 301)
                self.assertEqual(canonical.headers["Location"], "/en/")

                result = self.crawl.crawl(fixture.good, use_sitemap=False, workers=1)

            # 0.40.0 separated deduplication from fetching: page keys may normalize
            # the slash, but the discovered href is the address that must be fetched.
            self.assertFalse(key.endswith("/"))
            self.assertIn(key, result["pages"])
            self.assertTrue(result["pages"][key]["final_url"].endswith("/"))
            self.assertEqual(result["redirected"], [])
            self.assertEqual(result["summary"]["pages_redirected"], 0)


class NothingIsUndecidedAboutASiteThatAnswered(unittest.TestCase):
    """The other direction, and it cost an item on every audit for a whole release.

    `NothingIsDecidedAboutASiteThatCannotBeRead` below made twelve scripts report
    "I read nothing" so the runner could turn that into NO_DATA. This asserts the
    converse: a script that *did* read a site must not say so. Get it backwards and
    the fix for a site scoring 61/100 while unreachable becomes an item that can
    never be decided about any site at all — which is what happened to AR-149.

    The reason 462 tests missed it is worth keeping in view: every other test in this
    file grades through `evaluate()`, which never looks at `fetch_error`. Only the
    runner's `grade()` reads it, so a spurious one is invisible to all of them. This
    test checks the field directly, over every run in `RUNS`, which is why it is four
    lines and covers 75 of them.
    """

    # No exemptions, deliberately. The first draft of this test excused the two
    # `sitemap_checker` runs against the broken fixture, on the assumption that a
    # site with no sitemap has nothing to read — and the exemption was wrong twice
    # over: a 404 *is* an answer, and `sitemap_checker` already distinguishes "no
    # sitemap here" from "no location responded". Both runs pass without it.
    #
    # The *scope* is narrowed, which is a different thing from an exemption and is
    # derived rather than listed: this asserts something about sites that answered,
    # so it covers the runs that address a site. Three `server_log_audit.py` runs
    # address a file chosen to be unreadable — no User-Agent field, not a log, not
    # there — and "I read nothing" is the correct and required answer for each. A
    # hand-written exemption list would have said the same thing while also excusing
    # whatever got added to it later.
    def test_no_script_reports_a_site_it_read_as_unread(self):
        from checklist_runner import unread_reason
        about_a_site = {key for key, _script, template in RUNS
                        if any("{good}" in a or "{bad}" in a for a in template)}
        self.assertGreater(len(about_a_site), 60,
                           "the scope filter matched almost nothing, so this test "
                           "would pass without checking anything")
        wrong = []
        for key, payload in OUT.items():
            if "__failed__" in payload or key not in about_a_site:
                continue
            reason = unread_reason(payload)
            if reason:
                wrong.append(f"{key} = {reason!r}")
        self.assertEqual(wrong, [],
                         "these runs read a served fixture and told the runner they "
                         "read nothing, so every item behind them is NO_DATA on "
                         "every site:\n" + "\n".join(f"  {w}" for w in wrong))

    def test_a_log_that_could_be_read_is_not_reported_as_unread(self):
        """The same guarantee for the runs the filter above excludes. Two of the
        seven log runs read their file fine, and those must reach the runner as
        evidence rather than as a refusal — otherwise CI-018 is NO_DATA whenever a
        log *is* supplied, which is the AR-149 failure in a new script."""
        from checklist_runner import unread_reason
        for key in ("log_good", "log_waste", "log_json", "log_gz"):
            self.assertEqual(unread_reason(out(key)), "", key)


class NothingIsDecidedAboutASiteThatCannotBeRead(unittest.TestCase):
    """The single most valuable test in this file, and the last one written.

    Every URL-taking script is pointed at a port where nothing is listening, and no
    item may come back PASS, FAIL or WARN. That covers a whole family at once rather
    than one script at a time, and the family is this tool's oldest and worst: a
    script that fetched nothing exits 0 with an empty result, and an empty result
    satisfies a surprising number of assertions. It is how a host that does not
    resolve was once scored 61/100.

    Writing it found three more instances, all in the scripts that talk to a third
    party — `None` pre-seeded into a field that `eq` and `truthy` read as a *failing
    value*, and an empty `issues` list that `none_severity` reads as "nothing wrong".
    Both are verdicts invented out of a service being unavailable, in opposite
    directions.

    **The script list comes from the registry, not from `RUNS`.** It came from `RUNS`
    for a release, and that is how it missed `orphan_pages_from_sitemap.py`: the one
    crawler with no entry in that hand-maintained table, and therefore the one script
    this sweep could not see. GO-137 reported "no orphan pages" about a host that
    refused every connection — `sitemap(∅) - reachable(∅)` is no orphans, and no
    orphans is a PASS. A sweep whose coverage is a list somebody maintains has the
    same blind spot as the thing it is checking.
    """

    DEAD = None

    @classmethod
    def url_taking_scripts(cls) -> set:
        """Every script the registry hands a URL as its first argument.

        Derived, so a script cannot be added to the registry and stay out of this
        sweep. Scripts whose first argument is an HTML file, a Search Console
        property or an artifact are excluded — they are not being asked about a
        host, so a dead host is not their subject.

        Scripts whose capability is `api` are left out too, and that is a constraint
        rather than a judgement: they ask a third party about the URL, so pointing
        them at a dead host makes this suite call `validator.w3.org` and a WHOIS
        server. The suite is offline — loopback only, no DNS, no keys — and staying
        offline outranks the extra coverage. Their "the third party did not answer"
        path is stubbed in test_evidence_apis.py, which is the part of it that can be
        tested without a network.
        """
        out = set()
        for item in ITEMS.values():
            check = item.get("check") or {}
            args = check.get("args") or []
            if not check.get("script") or not args or args[0] != "{url}":
                continue
            if check.get("requires") in ("api", "safe_browsing"):
                continue
            out.add(check["script"])
        return out

    @classmethod
    def setUpClass(cls):
        import socket
        # A port nobody is on: bound to find a free one, then released. The refusal
        # is instant, which is what makes running 40 scripts through this cheap.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        cls.DEAD = f"http://127.0.0.1:{port}/"

        env = script_env()
        scripts = sorted(cls.url_taking_scripts())

        def run(script):
            proc = harness.spawn(
                [sys.executable, os.path.join(SCRIPTS, script), cls.DEAD, "--json"],
                env=env, timeout=120)
            if proc.returncode != 0 or not proc.stdout.strip():
                # A non-zero exit is fine here — the runner turns it into NO_DATA with
                # the reason. What must not happen is a *verdict*.
                return script, None
            try:
                return script, json.loads(proc.stdout)
            except json.JSONDecodeError:
                return script, None

        cls.dead_output = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for script, payload in pool.map(run, scripts):
                cls.dead_output[script] = payload

    # Two scripts judge the URL *string* and fetch nothing to do it. A verdict from
    # them about an unreachable host is correct: whether `/shop?SESSIONID=1&sort=x` is
    # a clean URL does not depend on the server answering.
    URL_ONLY = {
        "url_quality.py": "judges the URL it was given, and does not fetch it",
        "faceted_nav_audit.py": "judges URL shape; the page fetch is --from-page only",
    }

    def graded_status(self, item, script, payload):
        """The item's status as the *runner* would report it.

        Through `grade()` rather than `evaluate()` alone, because the difference
        between them is the whole point: `evaluate` sees a dict of defaults and grades
        it, and `grade` is where a payload that says "I read nothing" has to become
        NO_DATA. Testing `evaluate` here would assert the bug.
        """
        from checklist_runner import grade
        key = (script, ())
        rows = grade([item], {key: [item["id"]]}, {key: payload}, {}, False)
        return rows[0]["status"]

    def test_no_item_gets_a_verdict_from_a_site_that_answered_nothing(self):
        decided = []
        for script, payload in self.dead_output.items():
            if payload is None or script in self.URL_ONLY:
                continue
            for item in ITEMS.values():
                if (item.get("check") or {}).get("script") != script:
                    continue
                got = self.graded_status(item, script, payload)
                if got in (PASS, FAIL, WARN):
                    decided.append(f"{item['id']} ({item['severity']}, {script}) "
                                   f"= {got}")
        self.assertEqual(decided, [],
                         "these items decided something about a site that refused "
                         "every connection:\n" + "\n".join(f"  {d}" for d in decided))

    def test_the_url_only_scripts_still_answer_and_that_is_correct(self):
        """The other side of the exemption, so it cannot quietly become a way to
        excuse a script that should have noticed."""
        for script, reason in self.URL_ONLY.items():
            payload = self.dead_output.get(script)
            self.assertIsNotNone(payload, f"{script} produced nothing: {reason}")
            items = [i for i in ITEMS.values()
                     if (i.get("check") or {}).get("script") == script]
            statuses = {self.graded_status(i, script, payload) for i in items}
            self.assertTrue(statuses & {PASS, FAIL, WARN},
                            f"{script} decided nothing, so the exemption is wrong: "
                            f"{reason}")

    def test_the_scripts_that_answered_said_why(self):
        """A script may legitimately return a result for an unreachable host — it just
        has to carry the reason, so the runner can report NO_DATA with something a
        reader can act on rather than a bare absence.

        `reason` joined the accepted keys in 0.20 for `tls_certificate.py`, which can
        decline to look without anything having gone wrong: an `http://` URL serves no
        certificate, so there is no error to report and still a why to carry. The rule
        being enforced is "say why", not "name an exception".
        """
        silent = [script for script, payload in self.dead_output.items()
                  if payload is not None and script not in self.URL_ONLY
                  and not any(str(payload.get(key) or "")
                              for key in ("error", "fetch_error", "fetch_errors",
                                          "reason"))]
        self.assertEqual(silent, [], f"nothing said why by: {silent}")


class IndexNow(unittest.TestCase):
    """GEO-007 `key_valid`.

    The last of the 55 evidence scripts to get a test, and the one that needed a
    secret to run at all — which is why the contract pair exempts it: an IndexNow key
    is a credential, not a fixture. A *fake* key is not a credential, though, and the
    protocol is entirely about whether the origin hosts `/{key}.txt`. That is
    servable, so there was no reason for this to stay uncovered.
    """

    KEY = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

    def test_a_hosted_key_file_validates(self):
        good = out("indexnow")
        self.assertIs(good["checks"]["key_file"]["passed"], True)
        self.assertEqual(verdict("GEO-007", good), PASS)

    def test_an_origin_that_does_not_host_the_key_file_fails(self):
        """Which is the point of the protocol: anyone could claim a key, so the
        origin has to prove it owns one by serving it."""
        bad = out("indexnow_bad")
        self.assertIs(bad["checks"]["key_file"]["passed"], False)
        self.assertEqual(verdict("GEO-007", bad), FAIL)


class AClaimOfNoneIsNotMadeOverAnInputThatWasCapped(unittest.TestCase):
    """Every cap in this tool bounds requests, and every one of them bounds the
    evidence that could have failed an item asserting `none of these`. The pages
    past `--crawl-max-pages`, the links past `--max-links`, the images past
    `--max-images`, the sitemap files past the twenty-fifth and the GSC rows past
    the five-thousandth are not a random sample of the site: they are precisely
    the part nobody looked at, so `0 broken`, `no duplicates` and `no issues` over
    them are claims about the part that fit.

    Graded through `grade()` and not `evaluate()`. `evaluate` answers about a dict
    and would answer the same before this release; the withholding lives one layer
    out, so a test against `evaluate` would pass on the defect.
    """

    # Every script that can say its input was capped, read from the scripts rather
    # than listed. The first draft of this was a hand-written set and it was already
    # wrong when the predicate widened: `redirect_checker.py` reports a cap and was
    # not in it, so `CI-014` — `high` — was outside a rule that covers it. A list
    # maintained by memory is the failure this whole release is about, one layer up.
    #
    # A script that can *set* the key, not one that mentions it. Mentioning was the
    # first version of this and it enrolled `checklist_runner.py`, which reads the
    # flag and writes it nowhere: the reader counted as a reporter.
    CAN_SET = re.compile(r'\["truncated"\]\s*=\s*(?!False\b)'
                         r'|"truncated"\s*:\s*(?!False\b)')

    @classmethod
    def _reporters(cls):
        found = set()
        for name in os.listdir(SCRIPTS):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as handle:
                if cls.CAN_SET.search(handle.read()):
                    found.add(name)
        return found

    @staticmethod
    def _graded(item, payload):
        from checklist_runner import grade
        key = (item["check"]["script"], ())
        return grade([item], {key: [item["id"]]}, {key: payload}, {}, False)[0]

    @staticmethod
    def _clean_payload(rule):
        """The smallest output that satisfies `rule` by finding nothing."""
        payload: dict = {}
        node = payload
        parts = rule["path"].split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = 0 if rule.get("eq") == 0 else []
        return payload

    def _covered(self):
        reporters = self._reporters()
        return [i for i in ITEMS.values()
                if (i.get("check") or {}).get("assert")
                and passes_by_absence(i["check"]["assert"])
                and i["check"]["script"] in reporters]

    def test_the_set_it_covers_is_the_one_recorded(self):
        """Twenty-two items — eleven `high`, ten `medium`, one `low`. The number is
        pinned because the ledger entry this closes said twelve and the command
        recorded beside it printed eleven, and neither counted the thing the entry
        was about. Twelve is right for that entry's own subject: the items handed
        the crawl inventory whose assertion is a clean verdict. The command asked
        for `requires: crawl` plus a literal `eq 0`, which drops CI-018 and AR-162
        — clean verdicts spelled `none_severity` — and adds BL-083, which never
        reads the inventory and caps its own link list instead. The other six
        arrived by asking the same question of every cap rather than of the crawl:
        external links, GSC rows, a sitemap index walk and a stylesheet list."""
        ids = sorted(i["id"] for i in self._covered())
        self.assertEqual(ids, [
            "AR-149", "AR-162", "AR-163", "BL-081", "BL-083", "CI-008", "CI-014", "CI-018",
            "CN-039", "CN-041", "GO-136", "GO-137", "GO-138", "KW-071", "MD-185",
            "MD-187", "MS-022", "MS-023", "MS-029", "TE-168", "TE-170", "TE-174",
        ], "the covered set moved; say which definition gives the new one")

    def test_every_way_this_registry_spells_nothing_is_covered(self):
        """The predicate's own blind spot, which is the same defect it exists to fix.

        It read `eq: 0`, `none_severity` and `none_matching` and a comment called
        those "the whole set in this registry". Twelve items say the same thing as
        `len_eq: 0`, `len_lte: 0` or `falsy` — four of them `critical` — and every
        one of them was outside a rule about verdicts a cap can fake. Asserted over
        the registry rather than over a list, so a seventh spelling arriving in an
        item is a failure here rather than a silent escape.
        """
        missed = []
        for item in ITEMS.values():
            rule = (item.get("check") or {}).get("assert")
            if not rule or passes_by_absence(rule):
                continue
            # A rule left out has to pass by finding *something*. These are the
            # operators that do, and anything else is a shape nobody has classified.
            if not ({"truthy", "gte", "gt", "len_gte", "matches", "contains",
                     "value_map", "between", "len_between", "ne", "count_matching_lte"}
                    & set(rule)) and not (
                        rule.get("eq") not in (0, None)
                        or rule.get("lte", 0) > 0
                        or rule.get("lt", 0) > 0
                        or rule.get("len_eq", 0) > 0
                        or rule.get("len_lte", 0) > 0):
                missed.append(f"{item['id']} ({item['severity']}): {rule}")
        self.assertEqual(missed, [],
                         "these assertions pass by finding nothing and the "
                         "predicate does not know it:\n"
                         + "\n".join(f"  {m}" for m in missed))

    def test_a_clean_answer_over_a_capped_input_is_withheld(self):
        decided = []
        for item in self._covered():
            payload = self._clean_payload(item["check"]["assert"])
            self.assertEqual(self._graded(item, dict(payload))["status"], PASS,
                             f"{item['id']}: the payload is not a clean one")
            payload["truncated"] = True
            row = self._graded(item, payload)
            if row["status"] != NO_DATA:
                decided.append(f"{item['id']} ({item['severity']}) = {row['status']}")
        self.assertEqual(decided, [],
                         "these items called a site clean from the part of it "
                         "that was read:\n"
                         + "\n".join(f"  {d}" for d in decided))

    def test_a_defect_found_in_the_part_that_was_read_still_fails(self):
        """The asymmetry, and the reason this needs no threshold. Withholding a
        FAIL would lose a true finding to a cap — the defect is in the site
        whether or not the rest of it was read."""
        item = ITEMS["CN-039"]
        # 6, not 3: CN-039 warns up to 5 thin pages, and a WARN is a verdict too.
        # Taking the number past the band makes the assertion about the withholding
        # rule rather than about which side of the band the payload happened to land.
        self.assertEqual(self._graded(
            item, {"summary": {"thin_pages": 6}, "truncated": True})["status"], FAIL)
        # And the band itself still decides, rather than being withheld as a
        # near-clean answer: only PASS is a claim the cap could have faked.
        self.assertEqual(self._graded(
            item, {"summary": {"thin_pages": 3}, "truncated": True})["status"], WARN)

    def test_a_failing_count_over_a_capped_input_is_named_as_a_floor(self):
        """The verdict stands; the number beside it does not mean what it says.

        Three thin pages read off three pages of seven is at least three, and a fix
        list sized from it is short by everything the cap left out. Said in the
        evidence and not in the measure — the measure is what the script returned.
        """
        row = self._graded(ITEMS["MS-029"],
                           {"summary": {"duplicate_description_groups": 1},
                            "truncated": True})
        self.assertEqual(row["status"], FAIL)
        self.assertIn("floor", row["evidence"])
        whole = self._graded(ITEMS["MS-029"],
                             {"summary": {"duplicate_description_groups": 1}})
        self.assertEqual(whole["status"], FAIL)
        self.assertNotIn("floor", whole["evidence"],
                         "a complete input must not be described as partial")

    def test_an_item_that_passes_by_presence_is_untouched(self):
        """LO-198 finds a LocalBusiness node on the pages it read. Reading more
        pages cannot take it away, so a cap cannot fake this one and withholding
        it would only lose an answer."""
        item = ITEMS["LO-198"]
        self.assertFalse(passes_by_absence(item["check"]["assert"]))
        payload = {"local_business_nodes": 2, "truncated": True}
        self.assertEqual(self._graded(item, payload)["status"], PASS)

    def test_the_flag_is_read_off_the_output_and_nothing_else(self):
        self.assertTrue(input_truncated({"truncated": True}))
        self.assertFalse(input_truncated({"truncated": False}))
        self.assertFalse(input_truncated({}), "an absent flag is not a cap")
        self.assertFalse(input_truncated(None))

    def test_every_reporter_can_actually_set_the_flag(self):
        """A rule that reads a key nothing writes is inert, and inert is how the
        first three of these went unread for as long as they did.

        The reporter set is now derived from the presence of the string, so asserting
        that a reporter contains the string would assert nothing. What is worth
        asserting is the next step: that in each of them the key can become true. A
        script that initialises `"truncated": False` and never assigns it again reads
        as a reporter to the derivation and reports nothing to the runner.
        """
        mentions = set()
        for name in os.listdir(SCRIPTS):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as handle:
                if '"truncated"' in handle.read():
                    mentions.add(name)
        # Carries the key and cannot set it. One script is allowed to: the runner
        # reads the flag and is its only consumer in this directory. Anything else
        # here would be a script initialising `"truncated": False` and never
        # assigning again — a reporter to a reader and silence to the rule.
        self.assertEqual(sorted(mentions - self._reporters()),
                         ["checklist_runner.py"],
                         "a script carries the truncation key and cannot set it")



class EveryCheckerHasSomethingThatJudgesIt(unittest.TestCase):
    """`openspec/specs/evidence/` EVD-7. Running is not the same as being right: a checker with
    no test and no settled declaration produces a verdict on every audit and nothing
    anywhere says the verdict is correct.

    This was computed by hand for that document's Appendix A.2, by looking for each
    script's filename inside test function bodies, and the answer — one checker short of
    clean — **was wrong**. `collection_page_checker.py` is judged in both directions by
    `class CollectionPage`, which reaches it through the RUNS keys `collection` and
    `collection_bad` and never types the script's name. A search finds only the spellings
    put into it.

    So the union is computed rather than searched, and the fixture-key indirection is
    resolved: a checker is judged if a test *body* names it, or names a RUNS key that
    runs it, or decides an item the oracle predicts with a word the audit can emit.
    Bodies are taken by AST, because the RUNS table is module-level and naming a script
    there is scheduling it, not judging it.
    """

    NOT_A_CHECKER = {"checklist_runner.py", "checklist_report.py", "site_crawl.py",
                     "detect_profile.py", "env_loader.py", "seo_common.py"}
    HERE = os.path.dirname(os.path.abspath(__file__))

    @classmethod
    def registry_scripts(cls):
        with open(REGISTRY, encoding="utf-8") as stream:
            items = json.load(stream)["items"]
        out = {}
        for item in items:
            script = (item.get("check") or {}).get("script")
            if script and script not in cls.NOT_A_CHECKER:
                out.setdefault(script, set()).add(item["id"])
        return out

    @classmethod
    def written_in_a_function(cls):
        """The executable body of every function in `tests/test_*.py`, with prose gone.

        Three exclusions, each of which was a false credit before it was made:

        * **module level** — the RUNS table names every script there, and scheduling a
          script is not judging it;
        * **files that are not `test_*.py`** — `known_issues.py` keeps a table of
          per-script caps, and a ledger's bookkeeping is not an assertion about an
          answer;
        * **docstrings and comments** — this class's own docstring names
          `collection_page_checker.py` while explaining it, which credited the checker
          for being discussed. `ast.unparse` drops comments; the walk below drops
          docstrings.
        """
        def strip_prose(node):
            for child in ast.walk(node):
                body = getattr(child, "body", None)
                if isinstance(body, list):
                    child.body = [s for s in body
                                  if not (isinstance(s, ast.Expr)
                                          and isinstance(s.value, ast.Constant)
                                          and isinstance(s.value.value, str))] or [
                        ast.Pass()]
            return node

        chunks = []
        for name in sorted(os.listdir(cls.HERE)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            with open(os.path.join(cls.HERE, name), encoding="utf-8") as stream:
                text = stream.read()
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    try:
                        chunks.append(ast.unparse(strip_prose(node)))
                    except Exception:
                        continue
        return chr(10).join(chunks)

    @staticmethod
    def mentions(script, bodies):
        """`"canonical_checker.py"` and `import canonical_checker as cc` are the same
        claim. Matching only the first is how the hand count lost four more.

        The word boundaries matter: without them `link_profile` would be found
        inside a longer name, and a checker would look judged because a
        differently named one is.
        """
        pattern = r"\b" + re.escape(script[:-3]) + r"\b"
        return script in bodies or bool(re.search(pattern, bodies))

    @staticmethod
    def settled_items():
        """Items the oracle predicts with a word the audit can emit. `INDETERMINATE` is
        skipped by the comparison, so it judges nothing — `openspec/specs/declarations/` DEC-2."""
        path = os.path.join(ROOT, "tests", "fixtures", "expectations.json")
        with open(path, encoding="utf-8") as stream:
            manifest = json.load(stream)
        settled = set()
        for value in manifest.values():
            if not isinstance(value, dict):
                continue
            for item_id, entry in value.items():
                if isinstance(entry, dict) and entry.get("expect") != "INDETERMINATE":
                    settled.add(item_id)
        return settled

    def coverage(self):
        scripts = self.registry_scripts()
        bodies = self.written_in_a_function()
        key_to_script = {key: script for key, script, _ in RUNS}
        named = {s for s in scripts if self.mentions(s, bodies)}
        through_a_key = {key_to_script[k] for k in key_to_script
                         if ('out("%s")' % k) in bodies or ("out('%s')" % k) in bodies}
        settled = self.settled_items()
        declared = {s for s, ids in scripts.items() if ids & settled}
        return scripts, named, through_a_key, declared

    def test_no_checker_runs_on_every_audit_with_nothing_judging_it(self):
        scripts, named, through_a_key, declared = self.coverage()
        self.assertGreater(len(scripts), 50, "the registry lost its checkers")
        self.assertEqual(sorted(set(scripts) - (named | through_a_key | declared)), [],
                         "these checkers decide items on every audit and nothing "
                         "asserts their answers are right")

    def test_the_fixture_key_indirection_is_load_bearing(self):
        """The correction, pinned as a property rather than as a sentence. At least one
        checker is judged *only* through a RUNS key, so a future reader that searched
        for script names would report it uncovered — which is the error the hand count
        made. If this set ever empties, the resolution can be dropped; until then,
        dropping it makes this reader lie in the flattering direction."""
        scripts, named, through_a_key, declared = self.coverage()
        key_only = set(scripts) - named - declared
        self.assertTrue(
            key_only & through_a_key,
            "no checker depends on resolving RUNS keys any more; re-read Appendix A.2 "
            "of openspec/specs/evidence/ before simplifying this reader")

if __name__ == "__main__":
    unittest.main()
