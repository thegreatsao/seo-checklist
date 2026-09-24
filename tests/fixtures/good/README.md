# The fixture site

Six pages, a sitemap, a robots.txt and two assets — enough for the live path to
have something to crawl, sample, follow and refuse.

It exists because the SSRF guard used to have no escape hatch, so the only way to
exercise `checklist_runner.py` in `live` mode was to point it at somebody else's
website. Every test in this suite passed while a slot-file bug crashed 36 of 56
evidence scripts in a real run, and nothing offline could have caught it: a single
process writing to a fresh pacing file never appends twice. `--allow-private` and
this directory are what make that reproducible.

Serve it and audit it:

```bash
python3 -m http.server 8000 --directory tests/fixtures/good &
python3 skills/seo-checklist/scripts/checklist_runner.py http://127.0.0.1:8000/ \
    --allow-private --sample 3 --max-rps 50 --no-history --no-prompt
```

This is the half of the pair that has to be able to pass, and the failure paths live
in `../broken/`. What it still fails, it fails for a reason written down in one
place: `ACCUSED_ON_PURPOSE` in `tests/test_contract.py`, which refuses a failure it
does not list and a listed reason that no longer fails. Most are what `http.server`
over plain HTTP cannot do — HSTS, security headers, a secure page, a redirect from
`http://` — and the rest are a breadcrumb trail it deliberately lacks and `sameAs`
links that would take the suite online.

The table of planted defects that used to stand here described a site that had
moved: the orphan and the shared description went to `../broken/` long ago, the
second blog post is in the sitemap, and the about page's title is a sentence. Its
last true row went at 0.123.0 — `/private/secret.html` is still disallowed in
`robots.txt` but no longer listed in `sitemap.xml`, so the sitemap items can pass
here. The refusal it exercised is a unit test now.

One planted defect was removed in 0.9.0: `/blog/first-post.html` used to link to
`/gone.html` so `broken_links.py` had a 404 to find. That predates the good/broken
pair, and it was invisible while TE-168 checked only the entry page's links. One
shared crawl made the check site-wide, it found the dead link immediately, and the
fixture the pair calls *good* started warning about broken links — which weakens
every claim the pair makes. Planted defects belong in `../broken/`, which has its own
dead link. This side has to be able to pass.

The URLs inside `sitemap.xml` and the canonicals are hard-coded to
`http://127.0.0.1:8000`, so serve it on that port or the canonical and sitemap
checks will report a real mismatch — a correct verdict about a wrongly served
fixture, which is a confusing way to spend an afternoon.
