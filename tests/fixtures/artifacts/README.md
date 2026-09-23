# Supplied-by-the-operator inputs, for the fixture pair

Eighteen registry items are decided from a file rather than from a request:
`cwv_metrics.py` reads Core Web Vitals from a browser performance trace,
`rendered_audit.py` reads font size, link distinctness, overlays, tap targets,
horizontal overflow and clipped text from a rendered page, `server_log_audit.py`
reads a server access log, and
`gsc_links_csv.py` reads a Search Console Links export. The first two exist because
those numbers are *computed* values — a subprocess cannot obtain them, and a model
reading HTML has not measured them. The other two exist because their facts are in
the **past**: no request made now can discover what Googlebot crawled or which sites
linked last month.

Which means the contract audit could not exercise those items at all without the
corresponding artifacts. Without a file they report NO_DATA, correctly, on both
sites — so the good/broken comparison was measuring nothing. One
of the two `high` items is "Avoid Intrusive Interstitials", which is the check
most likely to matter to a real reader and was the least exercised.

**The browser numbers are written by hand, and every JSON file says so in its own
`source` field.** No browser runs in CI. That is a real limitation and it is not hidden:
`source` is printed by the script, carried into the results, and shown in the
report, so a file that came from a text editor rather than a trace announces it
everywhere it goes.

What the fixtures then verify is precise, and it is not "the site is fast":

- the thresholds face the right way — 5200 ms fails LCP and 820 ms passes it,
  which is exactly the direction the CrUX rating bug had backwards in 0.5.0;
- `mobile_overlays_covering_content` derives from the general overlay count when
  the viewport is a phone, and the derivation is exercised rather than assumed;
- ten assertions that had never once produced a verdict now produce two. Eight
  arrived with the artifacts themselves; `MB-107` and `MB-108` joined them in
  0.84.0, when the two mobile-layout measures owed since 0.62.0 were added to the
  contract.

Both files record a 390px viewport, because `rendered_audit.py` refuses to answer
its four mobile questions from a desktop render — a desktop fixture would leave
MB-094, MB-103, MB-107 and MB-108 NO_DATA and four of the ten unexercised. 390px is
also the width the deleted Playwright branch measured at, which is where MB-107's and
MB-108's definitions come from.

## links/

A Search Console Links export as people keep it once unzipped: a directory of sheets,
each with a non-numeric header row. `top-linking-sites.csv` has one linking domain per
row; the good fixture distributes 12 backlinks over five domains, with a 33.3%
top-domain share, and the broken fixture puts eight of ten links on one domain and has
only two linking domains. Those exercise total links, root-domain count and
concentration, and make no claim about link quality.

`top-linked-pages.csv`, added at 0.107.0, lists pages *of this site* that other sites
link to, and BL-083 requests each one. Its URLs carry the `127.0.0.1:8000` placeholder,
which is why `.csv` is in `harness.TEXTUAL`: the export has to name the port the origin
actually bound. The good sheet lists the home page and `/about.html`, both served. The
broken sheet lists `/old-offer.html`, which is not in the tree and which no page links
to, so the backlink lands on a 404 and moves nothing but BL-083.

## access.log

21 days of a plausible crawl, in Combined Log Format, and the two versions differ
on purpose rather than incidentally:

- **good** — every sitemap URL fetched, then revalidated with `304`s. Nothing
  wasted, no redirects, no 5xx. It produces zero issues, so CI-018 passes.
  `/private/secret.html` is in the sitemap and disallowed in this fixture's
  `robots.txt`, and it is **deliberately absent from the log**: a crawler obeying
  the rule never asks for it, and the audit must not count our own `Disallow` as a
  page nobody crawled. That subtraction is the one that shipped broken once
already, in the former sitemap-orphan reader before 0.4.0, and was written wrong a
  second time here before a real inventory caught it.
- **broken** — a crawl budget going nowhere: a deleted section still being
  requested, a permanent redirect, a 5xx served to Googlebot, and a `?sort=`
  parameter multiplying one page into dozens. Two `high` issues, so CI-018 fails.

The dates are fixed rather than relative to today, and the window is 21 days
because `server_log_audit.py` refuses to report never-crawled URLs from a log
covering less than a week — below that, "never crawled" and "not crawled yet" are
the same observation. A fixture generated relative to `now()` would have made that
refusal fire or not depending on the day.

Nothing in these files needs rewriting for the bound port: a log records paths,
not absolute URLs, and the script reads them as paths.

`http://127.0.0.1:8000` is a placeholder, rewritten by `tests/harness.py` to the
port each site actually bound, the same way the served fixtures are. It has to
be: the runner now refuses an artifact that describes a different page than the
one being audited, so an artifact pointing at the wrong port would be rejected
instead of read — which is itself asserted, in
`ArtifactsMustDescribeTheAuditedPage`.
