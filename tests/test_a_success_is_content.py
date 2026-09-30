"""Release 0.131.0: a success that is not a plain 200 is still the site's content.

Google, *HTTP status codes, network and DNS errors* (last updated 2026-02-04): for a 2xx
"Google considers the content for processing"; 201 and 202 it waits for; only 204 has
nothing to process. For robots.txt: "2xx (success) ... Google processes the robots.txt
file as provided". 0.130.0 read a status that way once, in `seo_common.status_class`,
for the entry page. Everywhere else the tree read its own site as content only on
exactly 200.

**Measured 30.09** (`local/twoxx/`, outside git): the good tree served with every
textual file answering 203 — the same bytes — moved **30 verdicts** under `--sample 1`.
The crawler kept no page (`status != 200`), so fifteen site-wide items were NO_DATA
under "the shared crawl read nothing"; `canonical_checker` called the page unread;
`robots_checker`, `social_meta` and `llms_txt_checker` said "the site stopped
answering"; and three were **false FAILs**: GEO-003 read a robots.txt at 203 as absent
and graded the policy `silent`, GEO-002 scored llms.txt 0, GO-136 reported "No sitemap
found". An AST census found 46 comparisons with 200 in `scripts/`; the ones reading the
site's own answers become `seo_common.carries_content`, and the ones reading a
third-party service's answer stay, each argued in `SERVICE_ANSWERS` below.

Three readers. `CarriesContent` is the table. `EveryExactTwoHundredIsAService` is the
census by the operation — every `==`/`!=`/`in` test against 200 in `scripts/`, in both
directions. `ASiteAnswering203IsTheSameSite` serves the good tree at 203 and requires
the verdicts of the same tree at 200, except the one item whose title names 200.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from harness import offline_env, spawn, tree_served  # noqa: E402
import seo_common  # noqa: E402


class CarriesContent(unittest.TestCase):
    """`status_class` says which kind of answer; this says whether there is content."""

    def test_every_success_but_no_content_carries_content(self):
        expected = {200: True, 201: True, 202: True, 203: True, 206: True,
                    204: False, 301: False, 304: False, 404: False, 410: False,
                    500: False, 503: False, None: False, 99: False}
        got = {status: seo_common.carries_content(status) for status in expected}
        self.assertEqual(got, expected)

    def test_it_is_read_off_status_class(self):
        for status in (200, 203, 204, 302, 404, 503, None):
            with self.subTest(status=status):
                self.assertEqual(seo_common.carries_content(status),
                                 seo_common.status_class(status)
                                 in ("ok", "other_success"))


# (script, function) -> (how many exact-200 tests it holds, why each is about a
# third-party service rather than the audited site). A service's contract names its
# own success; the site's content is `carries_content`.
SERVICE_ANSWERS = {
    ("domain_safety_check.py", "check_safe_browsing"):
        (1, "Google Safe Browsing's lookup API answers 200 with a verdict"),
    ("html_validator.py", "validate"):
        (1, "the W3C Nu validator answers 200 with its JSON messages"),
    ("pagespeed.py", "get_pagespeed"):
        (1, "the PageSpeed Insights API answers 200 with a report"),
    ("indexnow_checker.py", "ping_indexnow"):
        (1, "the IndexNow protocol names 200 and 202 as an accepted submission"),
    ("seo_common.py", "status_class"):
        (1, "the one place 200 is named: the class `ok`, which CI-003 reads"),
}


def exact_two_hundreds() -> dict[tuple[str, str], int]:
    """Every `==`, `!=`, `in` or `not in` test with 200 on one side, by enclosing function.

    Ordering comparisons (`200 <= status < 300`) are a range over the class, not a test
    for exactly 200, and are left to `audit_thresholds.py`.
    """
    found: dict[tuple[str, str], int] = {}
    for folder, _dirs, files in os.walk(SCRIPTS):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, SCRIPTS).replace(os.sep, "/")
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            functions = [n for n in ast.walk(tree)
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn))
                           for op in node.ops):
                    continue
                sides = [node.left, *node.comparators]
                values = {s.value for s in sides if isinstance(s, ast.Constant)}
                for side in sides:
                    if isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                        values |= {e.value for e in side.elts
                                   if isinstance(e, ast.Constant)}
                if 200 not in values:
                    continue
                inside = [f for f in functions
                          if f.lineno <= node.lineno <= f.end_lineno]
                owner = max(inside, key=lambda f: f.lineno).name if inside else "<module>"
                key = (rel, owner)
                found[key] = found.get(key, 0) + 1
    return found


class EveryExactTwoHundredIsAService(unittest.TestCase):

    def test_no_script_reads_its_own_site_as_content_only_on_200(self):
        found = exact_two_hundreds()
        unargued = sorted(f"{s}:{f} ({n})" for (s, f), n in found.items()
                          if (s, f) not in SERVICE_ANSWERS)
        self.assertEqual(unargued, [],
                         "these read the audited site's answer as content only on "
                         "exactly 200; use seo_common.carries_content, or argue a "
                         "service's contract in SERVICE_ANSWERS")

    def test_every_argued_service_still_holds_exactly_its_tests(self):
        found = exact_two_hundreds()
        for key, (count, why) in SERVICE_ANSWERS.items():
            with self.subTest(site=key):
                self.assertTrue(why.strip())
                self.assertEqual(found.get(key, 0), count, why)


# Verdicts a site answering 203 may legitimately change, each with why. Everything else
# must answer exactly as the same bytes at 200 do.
TITLE_NAMES_200 = {
    "CI-003": ("PASS", "WARN", "Page Returns 200 (OK): a 203 met Google, not the title"),
}


class ASiteAnswering203IsTheSameSite(unittest.TestCase):
    """The derivation by the operation: the good tree at 200 and the same bytes, every
    textual file, at 203 — with `--sample 3`, so the sampler's inventory filter runs."""

    CTYPE = {".html": "text/html; charset=utf-8", ".xml": "application/xml",
             ".txt": "text/plain; charset=utf-8", ".css": "text/css",
             ".json": "application/json", ".md": "text/markdown", ".csv": "text/csv",
             ".js": "application/javascript"}
    RESULTS: dict = {}

    @classmethod
    def at(cls, status):
        if status is None:
            return None

        def answers(site_dir):
            out = {}
            for folder, _dirs, files in os.walk(site_dir):
                for name in files:
                    ext = os.path.splitext(name)[1]
                    if ext not in cls.CTYPE or name == "_answers.json":
                        continue
                    path = os.path.join(folder, name)
                    rel = "/" + os.path.relpath(path, site_dir).replace(os.sep, "/")
                    with open(path, encoding="utf-8") as f:
                        answer = {"status": status, "content_type": cls.CTYPE[ext],
                                  "body": f.read()}
                    out[rel] = answer
                    if name == "index.html":
                        out[rel[: -len("index.html")]] = answer
            return out
        return answers

    @classmethod
    def audit(cls, label, status):
        with tree_served("good", cls.at(status)) as site:
            arts = tree_served.artifacts(site, "good", os.path.join(cls.work, label))
            extra = []
            for flag, name in (("--rendered-json", "rendered.json"),
                               ("--cwv-json", "cwv.json"), ("--links-csv", "links"),
                               ("--server-log", "access.log")):
                extra += [flag, os.path.join(arts, name)]
            out = os.path.join(cls.work, f"{label}.json")
            proc = spawn([sys.executable, RUNNER, site.url, "--allow-private",
                          "--sample", "3", "--max-rps", "0", "--no-history",
                          "--no-prompt", "--quiet", "--timeout", "120",
                          "--keyword", "bread", "--json", out, *extra],
                         env=offline_env(), timeout=900)
        if proc.returncode != 0 or not os.path.exists(out):
            raise AssertionError(f"{label} exited {proc.returncode}\n"
                                 f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        with open(out, encoding="utf-8") as f:
            payload = json.load(f)
        return label, {r["id"]: (r["status"], r.get("evidence") or "")
                       for r in payload["items"]}

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="seo-203-")
        with ThreadPoolExecutor(max_workers=2) as pool:
            cls.RESULTS = dict(pool.map(lambda r: cls.audit(*r),
                                        (("at200", None), ("at203", 203))))

    def moved(self):
        base, other = self.RESULTS["at200"], self.RESULTS["at203"]
        return {i: (base[i][0], other[i][0], other[i][1][:100])
                for i in base if base[i][0] != other[i][0]}

    def test_the_same_bytes_at_203_get_the_same_verdicts(self):
        unexplained = {i: v for i, v in self.moved().items() if i not in TITLE_NAMES_200}
        self.assertEqual(unexplained, {},
                         "a readable site answering 203 moved these verdicts")

    def test_every_allowed_difference_happens_and_only_as_stated(self):
        moved = self.moved()
        for item_id, (before, after, why) in TITLE_NAMES_200.items():
            with self.subTest(item=item_id):
                self.assertIn(item_id, moved, f"{why}: no longer differs")
                self.assertEqual(moved[item_id][:2], (before, after), why)


if __name__ == "__main__":
    unittest.main()
