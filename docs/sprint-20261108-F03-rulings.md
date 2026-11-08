# F03 batches 4–5 — the owner's rulings, 2026-11-08

91 disputes from `docs/sprint-20261108-F03-4.md` and `docs/sprint-20261108-F03-5.md`. Each ruling was recommended with
the reason below; the owner accepted all of them ("Принимаю все"). The plan's record is in
`docs/sprint-20261023-F03-plan.md`. Rulings: **fix** (repair the code in F15), **measures** (the code stays; a `measures`
sentence states what the rule decides, or an existing sentence is corrected), **keep** (not a defect), **retire** (drop
the script assertion).

| item | batch | kind | ruling | reason |
|---|---|---|---|---|
| SE-114 | 4 | confirmed | fix | Look up every crawled URL, not only the entry. One Safe Browsing request takes up to 500 URLs. |
| SE-116 | 4 | confirmed | measures | Safe Browsing cannot see injected SEO spam. Say the rule decides 'no Safe Browsing threat on the crawled URLs'; it inherits SE-114's fix. |
| TE-171 | 4 | confirmed | measures | DNS blocklists such as Spamhaus DBL bar use by a public service like seo-web. State that the rule is Safe Browsing only. |
| TE-179 | 4 | confirmed | measures | Ownership and transfer history needs a paid WHOIS-history API. State 'domain age from the creation date'. |
| TE-178 | 4 | fact confirmed, owner's call | retire | The signal is never emitted, so the item is always NO_DATA. Drop the script assertion; leave the item agent-judged until a real neighbour source exists. |
| SE-120 | 4 | confirmed | fix | The title is about hardening. Read the values: flag CSP unsafe-inline/unsafe-eval, Permissions-Policy wildcards, Referrer-Policy unsafe-url. |
| TE-175 | 4 | confirmed | measures | The code reads static HTML attributes. Reword to 'the served HTML references no HTTP resource'. |
| CI-016 | 4 | confirmed | fix | Flag alt="" where the image carries meaning (the only content of a link, or a large in-content image). The 'unrelated alt' half goes in a measures sentence. |
| MD-186 | 4 | confirmed | fix | Same code as CI-016; one repair covers both. |
| CN-054 | 4 | confirmed | fix | Count data-srcset-only images too, and reword: the rule counts JS-deferred images with no native fallback. |
| MD-184 | 4 | fact confirmed, owner's call | fix | srcset and <picture> images are images. Missing them gives a false FAIL. |
| CN-057 | 4 | confirmed | fix | 'Show clearly' means visible. Require a byline in the page text; meta author and og:site_name only support it. |
| CN-068 | 4 | confirmed | fix | An authorship item must not pass with no author. Make an author required, then score the rest. |
| MB-105 | 4 | confirmed | fix | The title names directives. Compare meta robots between served and rendered HTML. |
| TE-169 | 4 | confirmed | fix | A prefix bug: compare hosts, so example.com.au is external. Small fix. |
| TE-177 | 4 | confirmed | fix | Take the <title> in <head>, not the first one anywhere (an inline SVG's). Also the root of MS-026. |
| GO-139 | 4 | confirmed | measures | The sentence says 'any of its pages'; the code tests the most-impressed group. Correct the sentence. |
| KW-070 | 4 | fact confirmed, owner's call | measures | Search Console averages positions, so 'average position at most 1.5 for the brand group' is the honest reading of '#1'. Write that into the sentence. |
| KW-071 | 4 | confirmed | measures | Write the 3.0 spread band, the brand filter and the 10-impression floor into the reading, and say that no page copy is read. |
| MS-023 | 4 | confirmed | fix | With no brand given, a guessed brand should not swallow a genuinely split query. Drop queries as branded only when the brand is supplied. |
| BL-083 | 4 | confirmed | measures | A soft 404 needs the target's content, and the export has status only. State 'final HTTP status of the target'. |
| BL-084 | 4 | fact confirmed, owner's call | fix | Take the largest share, not the first row. Trivial, and holds for any export order. |
| BL-086 | 4 | fact confirmed, owner's call | measures | The sentence says sites, the code sums link counts: correct the sentence. Separately, a missing sheet must give NO_DATA, not FAIL (goes to F15). |
| BL-087 | 4 | fact confirmed, owner's call | measures | One export cannot 'track'. State 'at least five linking root domains in the export'. |
| CI-010 | 4 | confirmed | fix | /page and /page/ are different URLs to Google. Compare them as sent, like P2's comparison. |
| IN-122 | 4 | confirmed | fix | Check language and region codes (jp is not a language). Also fix the empty pass on a set with no alternates. |
| AR-151 | 4 | confirmed | fix | Test the crawled paths, not only /, and flag an empty User-agent line. |
| CI-006 | 4 | confirmed | fix | An empty Sitemap: line is not a declaration. One-line fix. |
| AR-155 | 4 | confirmed | measures | Wording only: the sentence says URL, the code checks the path. |
| CI-012 | 4 | confirmed | measures | The score is a heuristic over flags and reads no words. State that. |
| MB-096 | 5 | confirmed | fix | A 3000 px image behind a format-only <source> is not responsive. Require width descriptors or sizes. |
| MB-097 | 5 | fact confirmed, owner's call | measures | Judging compression beyond a byte limit needs decoding every image. State 'at most 250 KB, modern format on large images'. |
| MB-098 | 5 | confirmed | measures | The code is right (density srcsets need no sizes). Correct the sentence. |
| MD-185 | 5 | confirmed | fix | The same image passes here and fails MB-097. Align the severities so one image cannot do both. |
| MD-187 | 5 | fact confirmed, owner's call | fix | A 204 or a JSON body is not an image. Require an image/* Content-Type. |
| MD-189 | 5 | fact confirmed, owner's call | fix | The title names modern formats and responsive images. Assert both halves. |
| GEO-008 | 5 | confirmed | fix | Only unscoped and Googlebot rules apply, as in P2's reader. bingbot: nosnippet must not fail. |
| MS-022 | 5 | confirmed | fix | Keep ?page=N distinct so paginated titles are judged. Dropping canonicalized pages is right; say so. |
| MS-026 | 5 | confirmed | fix | The text_hash gate drops exactly the pages this critical item is about. Check titles on every crawled HTML page. |
| MS-029 | 5 | confirmed | fix | The same gate hides duplicate descriptions. |
| CN-039 | 5 | confirmed | fix | A 0-word page is the thinnest page. Same gate. |
| CN-041 | 5 | confirmed | fix | Leave noindex copies out of duplicate groups, and let near-duplicates reach the assertion. |
| CI-009 | 5 | confirmed | fix | Request the canonical target and the URL variants. A canonical to a 404 must fail. Critical item. |
| CI-011 | 5 | confirmed | fix | Fetch the target: a canonical to a noindex page is a mixed signal. A cross-host canonical is legitimate; do not fail on host alone. |
| TE-176 | 5 | confirmed | fix | Build the inventory with P2's canonical reader: every canonical and the Link header. |
| CI-008 | 5 | confirmed | fix | Credit the entry URL only when something links to it, unless it is the home page. |
| AR-162 | 5 | fact confirmed, owner's call | fix | Count distinct targets and drop self-links. The threshold of 3 stays. |
| CI-014 | 5 | fact confirmed, owner's call | measures | Whether a 302 is meant as temporary cannot be known. State 'temporary codes are flagged for review'. |
| AR-150 | 5 | confirmed | fix | A→A and A→B→A are loops. Count them as loops and fail. |
| CI-013 | 5 | confirmed | fix | Follow @import from fetched stylesheets. |
| CI-019 | 5 | confirmed | fix | Failed probes must make the result truncated (NO_DATA), not an empty pass. |
| TE-181 | 5 | confirmed | fix | Put the doctype back (from document.doctype) before validation; check one site against Nu first. Today every site likely fails. |
| GO-131 | 5 | confirmed | fix | A gtag loader with an ID counts as installed, and GA4 through GTM must not fail. |
| GO-132 | 5 | confirmed | fix | Detect a hardcoded tag beside a GTM container: the case the docstring itself names. |
| CN-056 | 5 | confirmed | fix | 'Show' means visible. Require a date in the visible text and take the later <time> as updated. |
| MB-102 | 5 | confirmed | measures | Nothing mobile is measured. State 'VideoObject has its required properties'. |
| MD-190 | 5 | confirmed | fix | A page with a video and no VideoObject should fail, not be N/A. |
| MS-032 | 5 | confirmed | fix | A page whose only JSON-LD fails to parse must fail. Untabled types: a measures note. |
| GO-143 | 5 | fact confirmed, owner's call | fix | Count WebSite-node properties only, include alternateName, and match placeholders by host, not substring. |
| GO-144 | 5 | confirmed | fix | Require at least one question-and-answer or definition block. Lists and tables alone should not pass. |
| GEO-004 | 5 | confirmed | fix | Leave nav menus out, and let one direct answer be enough. |
| GO-136 | 5 | confirmed | fix | A <url> without <loc>, a wrong namespace or an empty sitemap is invalid. |
| GO-138 | 5 | confirmed | fix | Use seo_common.google_noindex(), P2's reader. |
| GO-145 | 5 | confirmed | fix | Require a citation or source; author plus canonical must not pass. |
| GEO-005 | 5 | confirmed | fix | Same as GO-145. |
| TE-172 | 5 | confirmed | fix | Check Google's required properties by value: an Article with no headline fails. |
| LO-198 | 5 | fact confirmed, owner's call | fix | Google accepts Microdata and RDFa LocalBusiness. Read them; today it is a false FAIL. |
| LO-200 | 5 | confirmed | fix | Strip whitespace and require street and locality values in the PostalAddress. |
| GEO-001 | 5 | fact confirmed, owner's call | measures | Wording only: '2xx except 204', not '200'. |
| GEO-002 | 5 | fact confirmed, owner's call | measures | llms.txt has no quality standard; the score is a structural convention. State what it counts. |
| AR-153 | 5 | confirmed | fix | Singleton clusters must not count as hubs. |
| MB-100 | 5 | confirmed | fix | Stop failing min-width media queries (a false FAIL), and state that static CSS cannot judge tap targets. |
| MB-104 | 5 | confirmed | fix | Apply the icon origin's robots.txt, not the page's. |
| TE-180 | 5 | confirmed | fix | Resolve aria-labelledby to text, treat empty labels as no name, and include image and button inputs. |
| TE-168 | 5 | fact confirmed, owner's call | keep | A redirect on someone else's site is not the site's broken link. Recording without counting is right. |
| TE-174 | 5 | confirmed | fix | Count failed fetches as truncated and read <style> @imports. The 2 KB floor is fine. |
| SP-109 | 5 | confirmed | fix | // URLs on another host are third-party; type=text/plain is not executed. |
| SP-110 | 5 | confirmed | measures | The sentence overstates. State 'parser-blocking scripts'. |
| TECH-002 | 5 | confirmed | fix | font-display: block blocks render for up to 3 s. Treat it like a missing value. |
| CI-018 | 5 | confirmed | measures | Threshold families cannot decide 'managed crawl budget'. State what is asserted. |
| GO-134 | 5 | confirmed | measures | The API exposes only submitted sitemaps' issues. State that. |
| GO-137 | 5 | confirmed | measures | Search Console has no indexed-pages list in its API. State 'pages with impressions in 28 days'. |
| GEO-007 | 5 | confirmed | fix | The key file must equal the key and be text, not merely contain it. |
| BL-081 | 5 | confirmed | fix | Flag low diversity and empty or generic anchors too. |
| MS-033 | 5 | confirmed | fix | Require og:image and twitter:card, the tags that draw a preview. |
| KW-076 | 5 | confirmed | fix | Count li, td and div text as body copy; an H1 alone is not body copy. |
| GEO-006 | 5 | confirmed | fix | Count the Wikidata and Knowledge Graph results, and fix the x.com substring match. |
| AR-149 | 5 | confirmed | fix | Fetch each linked spelling, so a 301 /about/ beside a 200 /about is counted. |
| AR-154 | 5 | fact confirmed, owner's call | measures | Presence counts cannot judge a category page's quality. State it; the home page read as a category goes to F15. |
| AR-163 | 5 | confirmed | fix | Do not flag paginated paths that are controlled; a self-canonical is not a control. |
| GEO-003 | 5 | fact confirmed, owner's call | keep | One training and one answer token make a policy explicit enough, and a *-only robots.txt is silent on AI bots. |
