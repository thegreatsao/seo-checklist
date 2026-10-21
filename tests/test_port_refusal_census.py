"""HTTP-13 and HTTP-9: a request the web-ports switch refuses is `blocked`, on every path.

`SEO_STANDARD_PORTS_ONLY` refuses any port but 80 and 443 before the name is resolved.
Until 0.173.0 the guard classified that refusal as `blocked` and the scripts lost it on
the way to the runner: twenty-six reported it as a `fetch_error`, which the runner
records as `unread` ("the site stopped answering"); eight wrote `unread` into their own
`error_kind`; three recorded `crash`; and where the refused URL was a file the script
graded, the refusal became the site's defect (an IndexNow key "not found", a favicon
"unreachable") or a clean answer (robots.txt "allows it"). F14's census found them by
running every job the registry plans with the switch on, as these tests do.

Each test plans the jobs from the registry with the runner's own `build_plan`, runs each
job's script in this process through the runner's own `_timed` and grades the results
with `grade`, so what is asserted is what an audit would record. Resolution and the
transport are replaced: nothing leaves this machine, and every refusal the guard raises
is logged against the script that met it. A script that meets none is not read.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/seo-checklist/scripts"
REGISTRY = ROOT / "skills/seo-checklist/resources/config/checklist.json"
sys.path.insert(0, str(SCRIPTS))

import checklist_runner as cr  # noqa: E402
import seo_common  # noqa: E402
from lib import safe_http as sh  # noqa: E402

KEY = "abcd1234abcd1234abcd"
OFF = "https://site.example:8443"
VERDICTS = ("PASS", "FAIL", "WARN", "N/A")


def page(off: str) -> str:
    """A page naming each kind of further URL a script reads, every one under `off`."""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Site example page with a title of sensible length</title>
<meta name="description" content="A description of sensible length for the example page used by this census.">
<link rel="canonical" href="https://site.example/">
<link rel="alternate" hreflang="en" href="https://site.example/">
<link rel="alternate" hreflang="de" href="{off}/de/">
<link rel="alternate" hreflang="x-default" href="https://site.example/">
<link rel="icon" href="{off}/favicon.ico">
<link rel="stylesheet" href="{off}/style.css">
<link rel="preload" as="font" href="{off}/font.woff2" crossorigin>
<script src="{off}/app.js"></script>
<meta property="og:image" content="{off}/og.png">
<meta property="og:title" content="Example"><meta property="og:description" content="Example">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{off}/tw.png">
<meta name="indexnow" content="{KEY}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Organization","name":"Example","url":"https://site.example/","logo":"{off}/logo.png","sameAs":["{off}/profile"]}}</script>
</head><body><header><nav><a href="/about">About</a> <a href="{off}/x">X</a></nav></header>
<main><h1>Example heading</h1><p>{"Some words of text for the page. " * 40}</p>
<img src="{off}/hero.jpg" alt="A hero image" width="800" height="400">
<a href="{off}/outbound">outbound on another port</a></main></body></html>"""


def response(request, status, headers, body: bytes):
    made = sh.requests.Response()
    made.status_code = status
    made.url = request.url
    made.request = request
    made.headers = sh.CaseInsensitiveDict(headers)
    made._content = body
    made._content_consumed = True
    made.raw = io.BytesIO(body)
    return made


class Census:
    """One audit's jobs, run in this process with the switch on.

    `subject` is the page the scripts are asked about. Every request to site.example on
    443 other than its root redirects to the same path on 8443, which the switch
    refuses; the page names its further URLs on 8443 directly. Any other host answers
    404.
    """

    def __init__(self, subject: str, ctx_extra: dict | None = None):
        self.subject = subject
        self.refusals: dict[str, list[str]] = {}
        self.current = "-"
        self.html = page(OFF)
        self.ctx_extra = ctx_extra or {}

    def send(self, adapter, request, **kwargs):
        parsed = urlparse(request.url)
        if parsed.hostname == "site.example" and parsed.port in (None, 443):
            if parsed.path in ("", "/") and not parsed.query:
                return response(request, 200, {"Content-Type": "text/html; charset=utf-8"},
                                self.html.encode())
            target = OFF + parsed.path + (f"?{parsed.query}" if parsed.query else "")
            return response(request, 301, {"Location": target}, b"")
        return response(request, 404, {"Content-Type": "text/html"},
                        b"<html><body>not here</body></html>")

    def run_script(self, script: str, args: list, timeout: int = 120) -> dict:
        """`checklist_runner.run_script`, in this process: argv, `--json`, exit code."""
        self.current = script
        path = str(SCRIPTS / script)
        out, err, code = io.StringIO(), io.StringIO(), 0
        saved = sys.argv
        sys.argv = [path, *args, "--json"]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                runpy.run_path(path, run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except Exception as exc:  # noqa: BLE001 - what the runner reports as crash
            return {"error": f"[{script}] {type(exc).__name__}: {exc}", "error_kind": "crash"}
        finally:
            sys.argv = saved
        if code == 0 and out.getvalue().strip():
            return json.loads(out.getvalue())
        return {"error": f"[{script}] {err.getvalue().strip()[-300:] or f'exit code {code}'}",
                "error_kind": "crash"}

    def run(self) -> dict[str, list[dict]]:
        """Every graded row, by the script that fed it, for scripts that met a refusal."""
        validated = sh._validated_url

        def logging(url):
            try:
                return validated(url)
            except sh.NonStandardPort:
                self.refusals.setdefault(self.current, []).append(url)
                raise

        work = tempfile.mkdtemp(prefix="seo-census-")
        html_path = os.path.join(work, "entry.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(self.html)
        env = {"SEO_LOOPBACK_ONLY": "", "SEO_ALLOW_PRIVATE": "", "SEO_HTTP_CACHE": "",
               "SEO_STANDARD_PORTS_ONLY": "1", "SEO_MAX_RPS": "0",
               "SEO_RATE_LIMIT_DIR": os.path.join(work, "rate")}
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sh, "_validated_url", side_effect=logging), \
                mock.patch.object(sh.socket, "getaddrinfo", return_value=public), \
                mock.patch.object(sh._PinnedAdapter, "send",
                                  new=lambda adapter, request, **kw: self.send(adapter, request)), \
                mock.patch.object(socket, "create_connection",
                                  side_effect=ConnectionRefusedError("no sockets here")), \
                mock.patch.object(subprocess, "run",
                                  side_effect=FileNotFoundError("no programs here")), \
                mock.patch.object(cr, "run_script", side_effect=self.run_script):
            with open(REGISTRY, encoding="utf-8") as f:
                items = json.load(f)["items"]
            ctx = {"url": self.subject, "html": html_path, "indexnow_key": KEY,
                   "keyword": "example", **self.ctx_extra}
            plan, skipped = cr.build_plan(items, ctx, set(cr.MODE_CAPS["live"]), "live",
                                          rejected={"inventory_json": "not this census"})
            results = {key: cr._timed(key, 60) for key in plan}
            graded = cr.grade(items, plan, results, skipped, False)
        planned = {i for ids in plan.values() for i in ids}
        rows: dict[str, list[dict]] = {}
        for row in graded:
            if row["id"] in planned and row.get("script") in self.refusals:
                rows.setdefault(row["script"], []).append(row)
        return rows


def describe(row: dict) -> str:
    return (f"{row['id']} ({row['script']}): {row['status']}"
            f"/{row.get('error_kind')} — {(row.get('evidence') or '')[:140]}")


class ThePageItselfIsRefused(unittest.TestCase):
    """O1: the subject is on another port, so every same-site request is refused."""

    @classmethod
    def setUpClass(cls):
        cls.census = Census(OFF + "/")
        cls.rows = cls.census.run()

    def test_the_census_reached_the_scripts(self):
        # A census that refused nothing would pass every assertion below.
        self.assertGreaterEqual(len(self.rows), 35, sorted(self.rows))

    # The one script whose result is about several subjects: the page's uptime, which
    # the guard refuses here and TE-167 reads, and Safe Browsing, whois and the
    # neighbours' addresses, which are not the page (no key, no programs here). Its
    # other items are NO_DATA for those reasons, not for the refusal. Until F04 TE-167
    # was among them: the runner kept one kind per result (narrowed in F14's review).
    OTHER_SUBJECTS = {"SE-114", "SE-116", "TE-171", "TE-178", "TE-179"}

    def test_no_refused_page_is_graded_or_called_unread_or_a_crash(self):
        wrong = [describe(row) for rows in self.rows.values() for row in rows
                 if row["status"] in VERDICTS
                 or row.get("error_kind") not in (None, "blocked")]
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_every_row_a_refused_page_feeds_says_blocked(self):
        # O1 says `blocked`, and a row with no kind at all satisfied the test above.
        self.assertIn("TE-167", [row["id"] for row in
                                 self.rows.get("domain_safety_check.py", [])])
        wrong = [describe(row) for script, rows in self.rows.items()
                 for row in rows if row["id"] not in self.OTHER_SUBJECTS
                 if row.get("error_kind") != "blocked"]
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_a_script_that_failed_on_it_says_blocked(self):
        # Every script whose result names a failure names this one, in words.
        for _script, rows in sorted(self.rows.items()):
            failed = [row for row in rows if row.get("error_kind")]
            for row in failed:
                with self.subTest(item=row["id"]):
                    self.assertTrue(row["evidence"].startswith(cr.kind_label("blocked")),
                                    describe(row))
        self.assertFalse(cr.kind_label("blocked").startswith("unlabelled"))


class AFurtherURLIsRefused(unittest.TestCase):
    """O2: the page answers; a file it names, or a same-site file that redirects to
    another port, is refused. The item that URL decides is not decided by the refusal.
    """

    # Verdicts a refused URL does not decide, each read off what the page itself says.
    INDEPENDENT = {
        "IN-121": "hreflang x-default, from the page's own tags",
        "IN-127": "hreflang URL structure, from the page's own tags",
        "IN-128": "hreflang self-reference, from the page's own tags",
        "MB-098": "srcset without sizes, from the markup",
        "CI-003": "the page's own status, which was read",
        "GEO-008": "snippet controls, from the page that was read",
        "GEO-006": "sameAs platforms named in the markup; the HEAD check is an Info line",
        "AR-163": "facet URLs among the page's links, read from the markup",
    }

    @classmethod
    def setUpClass(cls):
        cls.census = Census("https://site.example/")
        cls.rows = cls.census.run()

    def test_the_census_reached_the_scripts(self):
        for script in ("indexnow_checker.py", "favicon_check.py", "css_minify_check.py",
                       "font_audit.py", "indexability_matrix.py", "robots_checker.py"):
            self.assertIn(script, self.rows)

    def test_no_item_is_decided_by_the_refusal(self):
        wrong = [describe(row) for rows in self.rows.values() for row in rows
                 if row["id"] not in self.INDEPENDENT
                 and (row["status"] in VERDICTS
                      or row.get("error_kind") not in (None, "blocked"))]
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_the_files_a_script_grades_are_blocked_not_the_sites_defect(self):
        rows = {row["id"]: row for rows in self.rows.values() for row in rows}
        for item in ("GEO-007", "MB-104", "TE-174", "CI-006", "AR-151", "AR-152",
                     "GEO-001", "GEO-002", "GEO-003", "GO-136", "GO-138", "CI-019"):
            with self.subTest(item=item):
                self.assertEqual((rows[item]["status"], rows[item].get("error_kind")),
                                 ("NO_DATA", "blocked"), describe(rows[item]))

    def test_an_unread_robots_txt_does_not_allow(self):
        rows = {row["id"]: row for rows in self.rows.values() for row in rows}
        for item in ("CI-005", "CI-001"):
            with self.subTest(item=item):
                self.assertEqual(rows[item]["status"], "NO_DATA", describe(rows[item]))

    def test_a_refused_stylesheet_withholds_the_clean_font_verdict(self):
        # Fonts can be declared inline too, so one stylesheet refused is a part of
        # the input unread, as a cap is: the clean answer is withheld, with the cause.
        rows = {row["id"]: row for rows in self.rows.values() for row in rows}
        self.assertEqual(rows["TECH-002"]["status"], "NO_DATA", describe(rows["TECH-002"]))
        self.assertIn("refused by this audit's guard", rows["TECH-002"]["evidence"])


class TheRunnersOwnRequests(unittest.TestCase):
    """The entry and `--sample`'s fallback are requested by the runner itself."""

    def test_a_refused_entry_is_recorded_as_blocked_in_the_artifact(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from harness import run_audit
        env = dict(os.environ, SEO_STANDARD_PORTS_ONLY="1")
        out = run_audit("https://site.example:8443/", env=env)
        self.assertIn("port 8443", out["entry_error"])
        self.assertEqual(out["entry_error_kind"], "blocked")

    def test_the_sample_fallback_names_what_it_was_refused(self):
        site = "https://site.example/"

        def get(url, **_kwargs):
            raise sh.NonStandardPort(f"Blocked: port 8443 of site.example ({url})")

        stderr = io.StringIO()
        with mock.patch.object(sh, "safe_get", get), \
                mock.patch.object(sh, "robots_allows", return_value=(True, 0.0)), \
                contextlib.redirect_stderr(stderr):
            found = cr.discover_urls(site, 5)
        self.assertEqual(found, [site.rstrip("/")])
        self.assertIn(f"{site}sitemap.xml not requested: Blocked: port 8443",
                      stderr.getvalue())


def refused_fetch(url: str) -> dict:
    """`seo_common.fetch_url`'s result for a URL the switch refused."""
    return {"url": url, "status": None, "headers": {}, "text": "", "bytes": 0,
            "redirect_chain": [], "error": f"Blocked: port 8443 ({url})",
            "error_kind": "blocked", "robots_blocked": False}


class PartsTheCensusDoesNotReach(unittest.TestCase):
    """Branches the census page cannot show, because there every further URL is
    refused at once: one file refused among several read, a robots.txt refused in
    front of a file that answers, a flag the runner does not pass."""

    def test_a_refused_robots_txt_withholds_the_favicon_grade(self):
        import favicon_check
        html = '<html><head><link rel="icon" href="/favicon.ico"></head></html>'
        icon = (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
                + (96).to_bytes(4, "big") * 2 + b"\x08\x06\x00\x00\x00" + b"\x00" * 64)

        def get(url, **_kwargs):
            body = html.encode() if url.endswith("/") else icon
            ctype = "text/html" if url.endswith("/") else "image/png"
            return mock.Mock(status_code=200, url=url, text=html, content=body,
                             headers={"Content-Type": ctype})

        robots = {"url": "https://site.example/robots.txt", "parsed": None,
                  "fetch": refused_fetch("https://site.example/robots.txt")}
        with mock.patch.object(favicon_check, "safe_get", get), \
                mock.patch.object(favicon_check, "fetch_robots", return_value=robots):
            out = favicon_check.check("https://site.example/")
        # Graded, and withheld: the runner reads the `fetch_error` before the grade.
        self.assertEqual(out["fetch_error_kind"], "blocked")
        self.assertNotEqual(out["favicon"]["grade"], "fails")

    def test_one_stylesheet_refused_among_several_withholds_only_the_clean_answer(self):
        import css_minify_check
        html = ('<link rel="stylesheet" href="/a.css">'
                '<link rel="stylesheet" href="https://site.example:8443/b.css">')

        def get(url, **_kwargs):
            if ":8443" in url:
                raise sh.NonStandardPort("Blocked: port 8443 of site.example")
            return mock.Mock(status_code=200, text=html if url.endswith("/") else "a{b:c}")

        with mock.patch.object(css_minify_check, "safe_get", get):
            out = css_minify_check.check("https://site.example/")
        self.assertEqual(out["checked"], 1)
        self.assertTrue(out["truncated"])
        self.assertIn("refused by this audit's guard", out["truncated_reason"])
        self.assertIsNone(out["fetch_error"])

    def test_a_refused_sitemap_beside_one_that_loads_is_unread_not_broken(self):
        import sitemap_checker
        own, refused = "https://site.example/a.xml", "https://site.example/b.xml"
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        good = f'<urlset xmlns="{ns}"><url><loc>https://site.example/p</loc></url></urlset>'

        def fetch(url, **_kwargs):
            if url == refused:
                return refused_fetch(url)
            return {"url": url, "status": 200, "headers": {"content-type": "application/xml"},
                    "text": good, "bytes": len(good), "redirect_chain": [], "error": None,
                    "error_kind": None}

        robots = {"url": "https://site.example/robots.txt",
                  "fetch": {"status": 200, "url": "https://site.example/robots.txt"},
                  "parsed": None}
        with mock.patch.object(sitemap_checker, "fetch_url", fetch), \
                mock.patch.object(sitemap_checker, "fetch_robots", return_value=robots):
            out = sitemap_checker.check_sitemaps("https://site.example/", [own, refused])
        self.assertEqual([i for i in out["issues"] if "HTTP" in i["message"]], [])
        self.assertTrue(out["truncated"])
        self.assertIn(refused, out["truncated_reason"])

    def favicon(self, href: str, robots_status: int = 404) -> dict:
        """`favicon_check.check` on a page declaring `href`, its robots.txt answering
        `robots_status`, the switch refusing any port but 443."""
        import favicon_check
        html = f'<html><head><link rel="icon" href="{href}"></head></html>'

        def get(url, **_kwargs):
            sh.normalize_url(url)          # an invalid scheme refuses as the guard does
            if ":8443" in url:
                raise sh.NonStandardPort("Blocked: port 8443 of site.example")
            if "10.0.0.1" in url:
                raise sh.SafeHTTPError("Blocked: URL resolves to private/internal IP")
            return mock.Mock(status_code=200, url=url, text=html, content=html.encode(),
                             headers={"Content-Type": "text/html"})

        robots = {"url": "https://site.example/robots.txt", "parsed": None,
                  "fetch": {"status": robots_status, "error": None, "error_kind": None}}
        with mock.patch.object(favicon_check, "safe_get", get), \
                mock.patch.object(favicon_check, "fetch_robots", return_value=robots):
            return favicon_check.check("https://site.example/")

    def test_a_favicon_on_another_port_is_unread_not_unreachable(self):
        out = self.favicon("https://site.example:8443/favicon.ico")
        self.assertEqual(out["fetch_error_kind"], "blocked")
        self.assertNotEqual(out["favicon"].get("grade"), "fails")

    def test_a_favicon_google_cannot_fetch_either_still_fails(self):
        # A private address or a `data:` href is the site's to fix: Googlebot cannot
        # fetch it either, so only the port refusal is excused.
        for href in ("data:image/png;base64,AAAA", "http://10.0.0.1/favicon.ico"):
            with self.subTest(href=href):
                out = self.favicon(href)
                self.assertEqual(out["favicon"]["grade"], "fails")
                self.assertNotIn("fetch_error_kind", out)


def port_refusal(url: str = "https://site.example:8443/"):
    return sh.NonStandardPort(f"Blocked: port 8443 of site.example ({url})")


class FoundByTheReviewOf0173(unittest.TestCase):
    """The `gpt-6.1-sol` review of 0.173.0's first build: paths the census page could
    not show, because there every further URL is refused at once — a GET read and its
    HEAD refused, a robots.txt read and the paths behind it refused, a crawl with one
    page refused — and two it showed and the tests let through."""

    def test_a_refused_head_withholds_the_clean_header_answer(self):
        import cache_compression_checker as cc
        html = "<html><head><title>t</title></head><body>x</body></html>"
        fetched = {"url": "https://site.example/", "status": 200, "error": None,
                   "error_kind": None}
        with mock.patch.object(cc, "load_source", return_value=(html, fetched["url"], fetched)), \
                mock.patch.object(cc, "safe_request", side_effect=port_refusal()):
            out = cc.audit("https://site.example/")
        self.assertTrue(out["truncated"])
        self.assertIn("refused by this audit's guard", out["truncated_reason"])

    def test_a_refused_facet_url_withholds_the_clean_facet_answer(self):
        import faceted_nav_audit as fn
        page = '<html><body><a href="/?filter=red&color=blue">red</a></body></html>'

        def fetch(url, **_kwargs):
            if url == "https://site.example/":
                return {"url": url, "status": 200, "text": page, "error": None,
                        "error_kind": None}
            return refused_fetch(url)

        stdout = io.StringIO()
        with mock.patch.object(fn, "fetch_url", fetch), \
                mock.patch.object(fn, "robots_allows", return_value=(True, 0.0)), \
                mock.patch.object(sys, "argv", ["faceted_nav_audit.py", "https://site.example/",
                                                "--from-page", "--fetch", "--json"]), \
                contextlib.redirect_stdout(stdout):
            fn.main()
        out = json.loads(stdout.getvalue())
        self.assertGreater(out["faceted_count"], 0)
        self.assertTrue(out["truncated"])
        self.assertIn("refused by this audit's guard", out["truncated_reason"])

    def test_paths_refused_behind_a_robots_txt_that_was_read_are_not_a_clean_answer(self):
        import robots_path_tester as rpt
        robots = {"url": "https://site.example/robots.txt",
                  "fetch": {"status": 200, "error": None, "error_kind": None},
                  "parsed": seo_common.parse_robots_txt("User-agent: *\nAllow: /\n")}
        with mock.patch.object(rpt, "fetch_robots", return_value=robots), \
                mock.patch.object(rpt, "safe_get", side_effect=port_refusal()):
            out = rpt.test_paths("https://site.example/", ["/cart", "/login"],
                                 ["Googlebot"], probe=True)
        self.assertEqual(out["indexable_urls"], [])
        self.assertTrue(out["truncated"])
        self.assertIn("refused by this audit's guard", out["truncated_reason"])

    def test_a_refused_font_head_withholds_the_clean_font_answer(self):
        import font_audit
        html = ("<html><head><style>@font-face{font-family:X;font-display:swap;"
                "src:url(https://site.example:8443/f.woff2)}</style></head></html>")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as handle:
            handle.write(html)
        self.addCleanup(os.unlink, handle.name)
        with mock.patch.object(font_audit, "fetch_url",
                               side_effect=lambda url, **k: refused_fetch(url)):
            out = font_audit.audit(handle.name, fetch_fonts=True)
        self.assertTrue(out["truncated"])

    def crawl(self, routes: dict) -> dict:
        """`site_crawl.crawl` of site.example with the switch on; `routes` maps a path
        on 443 to (status, headers, body); anything else answers 404."""
        import site_crawl

        def send(adapter, request, **_kwargs):
            parsed = urlparse(request.url)
            status, headers, body = routes.get(parsed.path, (404, {"Content-Type": "text/html"}, b""))
            return response(request, status, headers, body)

        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        work = tempfile.mkdtemp(prefix="seo-census-crawl-")
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "", "SEO_HTTP_CACHE": "",
                                          "SEO_STANDARD_PORTS_ONLY": "1", "SEO_MAX_RPS": "0",
                                          "SEO_RATE_LIMIT_DIR": work}), \
                mock.patch.object(sh.socket, "getaddrinfo", return_value=public), \
                mock.patch.object(sh._PinnedAdapter, "send",
                                  new=lambda adapter, request, **kw: send(adapter, request)):
            return site_crawl.crawl("https://site.example/", use_sitemap=False, workers=1)

    def test_a_crawled_page_the_guard_refused_leaves_the_crawl_incomplete(self):
        html = b'<html><head><title>Home</title></head><body><a href="/p">p</a></body></html>'
        out = self.crawl({"/": (200, {"Content-Type": "text/html"}, html),
                          "/p": (301, {"Location": "https://site.example:8443/p"}, b"")})
        self.assertEqual(out["summary"]["refused_pages"], 1)
        self.assertTrue(out["summary"]["truncated"])

    def test_a_crawl_refused_whole_says_so_to_every_reader(self):
        import site_crawl
        with mock.patch.dict(os.environ, {"SEO_STANDARD_PORTS_ONLY": "1"}):
            inventory = site_crawl.crawl("https://site.example:8443/", use_sitemap=False,
                                         workers=1)
        self.assertEqual(inventory["fetch_error_kind"], "blocked")
        path = os.path.join(tempfile.mkdtemp(prefix="seo-census-inv-"), "crawl.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(inventory, handle)
        with open(REGISTRY, encoding="utf-8") as f:
            items = json.load(f)["items"]
        ctx = {"url": "https://site.example:8443/", "inventory_json": path}
        plan, skipped = cr.build_plan([i for i in items if i["id"] in
                                       ("AR-149", "MS-022", "TE-168", "CI-015", "BL-081",
                                        "CI-008", "TE-176", "MD-187", "LO-198")],
                                      ctx, set(cr.MODE_CAPS["live"]), "live")
        results = {key: cr._timed(key, 120) for key in plan}
        rows = cr.grade([i for i in items if any(i["id"] in ids for ids in plan.values())],
                        plan, results, skipped, False)
        self.assertEqual(len(rows), 9, [row["id"] for row in rows])
        wrong = [describe(row) for row in rows if row.get("error_kind") != "blocked"]
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_the_timing_request_refused_after_the_page_was_read_is_blocked(self):
        import lcp_subparts
        html = "<html><body><img src='/a.jpg'></body></html>"
        fetched = {"url": "https://site.example/", "status": 200, "error": None,
                   "error_kind": None}
        with mock.patch.object(lcp_subparts, "load_source",
                               return_value=(html, fetched["url"], fetched)), \
                mock.patch.object(lcp_subparts, "safe_request", side_effect=port_refusal()):
            out = lcp_subparts.analyze_source("https://site.example/")
        self.assertEqual(out["error_kind"], "blocked")

    def test_broken_links_says_its_own_page_was_refused(self):
        import broken_links
        with mock.patch.object(broken_links, "safe_get", side_effect=port_refusal()):
            out = broken_links.check_broken_links("https://site.example:8443/")
        self.assertEqual(out["error_kind"], "blocked")

    def test_an_indexnow_key_file_behind_a_private_address_is_still_missing(self):
        import indexnow_checker as ic
        for failure, passed in ((sh.SafeHTTPError("Blocked: private/internal IP"), False),
                                (port_refusal(), None)):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(ic, "safe_get", side_effect=failure):
                self.assertIs(ic.check_key_file("https://site.example/", KEY)["passed"],
                              passed)

    def test_the_http_variant_refused_carries_its_kind(self):
        import security_headers
        with mock.patch.object(security_headers, "safe_get", side_effect=port_refusal()):
            out = security_headers.walk_http_to_https("http://site.example/")
        self.assertEqual(out["error_kind"], "blocked")


    # The second pass of the same review, over the fixes.

    def test_a_favicon_defect_fails_even_when_robots_txt_was_refused(self):
        import favicon_check
        html = '<html><head><link rel="icon" href="data:image/png;base64,AAAA"></head></html>'

        def get(url, **_kwargs):
            sh.normalize_url(url)
            return mock.Mock(status_code=200, url=url, text=html, content=html.encode(),
                             headers={"Content-Type": "text/html"})

        robots = {"url": "https://site.example/robots.txt", "parsed": None,
                  "fetch": refused_fetch("https://site.example/robots.txt")}
        with mock.patch.object(favicon_check, "safe_get", get), \
                mock.patch.object(favicon_check, "fetch_robots", return_value=robots):
            out = favicon_check.check("https://site.example/")
        self.assertEqual(out["favicon"]["grade"], "fails")
        self.assertNotIn("fetch_error_kind", out)

    def test_a_timing_response_cut_short_is_unread_not_a_crash(self):
        import lcp_subparts
        fetched = {"url": "https://site.example/", "status": 200, "error": None,
                   "error_kind": None}
        cut = sh.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        with mock.patch.object(lcp_subparts, "load_source",
                               return_value=("<html>ok</html>", fetched["url"], fetched)), \
                mock.patch.object(lcp_subparts, "safe_request", side_effect=cut):
            out = lcp_subparts.analyze_source("https://site.example/")
        self.assertEqual(out["error_kind"], "unread")

    def test_a_refused_url_in_a_matrix_batch_is_unknown_not_unindexable(self):
        import indexability_matrix as ix
        off = "https://site.example:8443/refused"

        def fetch(url, **_kwargs):
            if url == off:
                return refused_fetch(url)
            return {"url": url, "status": 200, "headers": {}, "text": "",
                    "redirect_chain": [], "error": None, "error_kind": None}

        absent = {"url": "https://site.example/robots.txt", "parsed": None,
                  "fetch": {"status": 404, "error": None, "error_kind": None}}
        with mock.patch.object(ix, "fetch_robots", return_value=absent), \
                mock.patch.object(ix, "fetch_url", fetch), \
                mock.patch.object(ix, "discover_sitemap_urls", return_value=[]):
            out = ix.evaluate([off, "https://site.example/ok"], "https://site.example/")
        row = out["rows"][0]
        self.assertEqual((row["blockers"], row["verdict"], row["status_class"]),
                         ([], None, None))
        self.assertEqual(out["rows"][1]["verdict"], "indexable")

    def test_the_matrix_carries_an_unanswered_robots_txt_into_membership(self):
        # Through `evaluate`: the helper's own test passed with `evaluate` no longer
        # handing it the robots.txt it read (second review pass).
        import indexability_matrix as ix
        robots = {"url": "https://site.example/robots.txt", "parsed": None,
                  "fetch": refused_fetch("https://site.example/robots.txt")}
        page = {"url": "https://site.example/page", "status": 200,
                "headers": {"content-type": "text/html"}, "text": "<html></html>",
                "redirect_chain": [], "error": None, "error_kind": None}

        def fetch(url, **_kwargs):
            return page if url.endswith("/page") else dict(page, url=url, status=404,
                                                            text="")

        with mock.patch.object(ix, "fetch_robots", return_value=robots), \
                mock.patch.object(ix, "fetch_url", fetch), \
                mock.patch.object(ix, "discover_sitemap_urls",
                                  side_effect=lambda *a, **k: [] if k.get("robots") is None
                                  else ["https://site.example/sitemap.xml"]):
            out = ix.evaluate(["https://site.example/page"], "https://site.example/")
        self.assertIsNone(out["rows"][0]["in_sitemap"])
        self.assertIn("robots.txt gave no answer", out["sitemap_membership_unknown"])


def graded_row(item_id: str, script: str, output: dict) -> dict:
    """The row `checklist_runner.grade` writes for one item over one script result."""
    with open(REGISTRY, encoding="utf-8") as f:
        item = next(i for i in json.load(f)["items"] if i["id"] == item_id)
    key = (script, ("https://site.example/",))
    return cr.grade([item], {key: [item_id]}, {key: output}, {}, False)[0]


class OneKindPerField(unittest.TestCase):
    """HTTP-13 (F04): a script whose result is about several subjects withholds the
    field whose request the guard refused, and the item reading that field was
    `NO_DATA` with no kind at all — the runner kept one kind per result. The
    requirement says the item it decides is `NO_DATA` with the kind `blocked`. A
    script now names the kind of a field it withheld (`withheld`), and the runner
    reads it for the item asserting on that field, only when the field is absent.
    """

    def test_se_117_with_its_http_variant_refused_says_blocked(self):
        import security_headers
        page = mock.Mock(status_code=200, url="https://site.example/",
                         headers={"Content-Type": "text/html; charset=utf-8"},
                         text="<html><head><title>t</title></head><body>x</body></html>")

        def get(url, **_kwargs):
            if url.startswith("http://"):
                raise port_refusal(url)
            return page

        with mock.patch.object(security_headers, "safe_get", side_effect=get):
            out = security_headers.check_security_headers("https://site.example/")
        self.assertNotIn("http_to_https", out)
        row = graded_row("SE-117", "security_headers.py", out)
        self.assertEqual((row["status"], row.get("error_kind")), ("NO_DATA", "blocked"),
                         describe(dict(row, script="security_headers.py")))
        self.assertTrue(row["evidence"].startswith(cr.kind_label("blocked")), row["evidence"])

    def test_te_167_with_its_uptime_request_refused_says_blocked(self):
        import domain_safety_check as dsc
        with mock.patch.object(dsc, "is_private_host", return_value=True), \
                mock.patch.object(dsc, "safe_get", side_effect=port_refusal()):
            out = dsc.check("https://site.example/")
        self.assertNotIn("reachable", out["uptime"])
        row = graded_row("TE-167", "domain_safety_check.py", out)
        self.assertEqual((row["status"], row.get("error_kind")), ("NO_DATA", "blocked"),
                         describe(dict(row, script="domain_safety_check.py")))

    def test_a_named_kind_does_not_reach_an_item_whose_field_was_read(self):
        # The kind is read only for an absent field: a script naming one for a field
        # it did write cannot turn that field's verdict into a refusal.
        out = {"url": "https://site.example/", "http_to_https": "permanent",
               "withheld": {"http_to_https": "blocked"}}
        row = graded_row("SE-117", "security_headers.py", out)
        self.assertEqual((row["status"], row.get("error_kind")), ("PASS", None))
        # Written and undecidable is the script's own answer, not the guard's.
        out["http_to_https"] = "sideways"
        row = graded_row("SE-117", "security_headers.py", out)
        self.assertEqual((row["status"], row.get("error_kind")), ("NO_DATA", None))

    def test_a_field_absent_for_another_reason_carries_no_kind(self):
        # The http variant timed out: withheld, and not by the guard.
        import security_headers
        page = mock.Mock(status_code=200, url="https://site.example/",
                         headers={"Content-Type": "text/html"}, text="<html></html>")

        def get(url, **_kwargs):
            if url.startswith("http://"):
                raise sh.requests.exceptions.ReadTimeout("read timed out")
            return page

        with mock.patch.object(security_headers, "safe_get", side_effect=get):
            out = security_headers.check_security_headers("https://site.example/")
        row = graded_row("SE-117", "security_headers.py", out)
        self.assertEqual(row["status"], "NO_DATA")
        self.assertNotEqual(row.get("error_kind"), "blocked")


if __name__ == "__main__":
    unittest.main()
