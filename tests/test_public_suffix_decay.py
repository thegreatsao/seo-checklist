"""INP-10: a stale public suffix list is announced only when it decided something.

The bundled list decides one thing in an audit: the Search Console property, built from
the audited host's registrable domain when the operator names none. A snapshot past
`PSL_STALE_DAYS` lacks the suffixes registered since, and the only symptom is a property
that answers nothing, so the run says so — and says nothing when the list was not
consulted for a property, because a warning on runs it did not affect is how a warning
stops being read.

No test could reach the branch until F04: every fixture is an address, an address has no
registrable domain, and the property is never derived. `named_host_runner.py` runs the
real runner with a served fixture resolved under a name (see its docstring). Each case is
a run of it, read where its reader sees it: stderr, the results file, both reports.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from harness import SCRIPTS, offline_env, served, spawn, with_tripwire

sys.path.insert(0, SCRIPTS)
from checklist_report import render_html, render_markdown  # noqa: E402


def today() -> date:
    # The list's date and its age are UTC (`refresh_public_suffix_list.py`,
    # `psl_staleness`); a local date is a day ahead between local and UTC midnight.
    return datetime.now(timezone.utc).date()


HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(SCRIPTS, os.pardir, "resources", "config", "public_suffix_list.dat")
NAME = "shop.example.co.uk"
PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>A shop "
        "with a title of sensible length</title></head><body><h1>A shop</h1><p>"
        + "Words of body text for the page. " * 30 + "</p></body></html>")


def snapshot(header: str) -> str:
    """The bundled list with its date line replaced by `header`."""
    with open(BUNDLED, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    out = [header if line.startswith("// snapshot taken ") else line for line in lines]
    assert out != lines, "the bundled list carries no date line to replace"
    path = os.path.join(tempfile.mkdtemp(prefix="seo-psl-"), "psl.dat")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    return path


def audit(psl: str, *extra: str, credentials: bool = True) -> dict:
    work = tempfile.mkdtemp(prefix="seo-psl-run-")
    target = os.path.join(work, "results.json")
    key = os.path.join(work, "sa.json")
    with open(key, "w", encoding="utf-8") as f:
        json.dump({"type": "service_account", "note": "not a key; never sent"}, f)
    with served({"/": PAGE}) as site:
        port = urlparse(site.base).port
        args = [sys.executable, os.path.join(HERE, "named_host_runner.py"),
                f"http://{NAME}:{port}/", "--max-rps", "0", "--no-history",
                "--no-prompt", "--timeout", "60", "--only", "local",
                "--json", target, *extra]
        if credentials:
            args += ["--gsc-credentials", key]
        env = with_tripwire(offline_env(SEO_TEST_NAME=NAME, SEO_TEST_PSL=psl))
        child = spawn(args, env=env, timeout=300)
    if child.returncode != 0:
        raise AssertionError(f"exit {child.returncode}\n{child.stdout[-1500:]}\n"
                             f"{child.stderr[-1500:]}")
    with open(target, encoding="utf-8") as f:
        payload = json.load(f)
    payload["_stderr"] = child.stderr
    return payload


class ADerivedPropertyOverAStaleList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = audit(snapshot("// snapshot taken 2020-01-01\n"))

    def test_the_property_was_derived_from_the_list(self):
        # The case this module exists for: a name, so the list decided the property.
        self.assertIn("GSC property: sc-domain:example.co.uk", self.result["_stderr"])

    def test_the_run_says_the_list_is_old_and_how_old(self):
        age = (today() - date(2020, 1, 1)).days
        self.assertIn(f"public suffix list snapshot is {age} days old (2020-01-01)",
                      self.result["_stderr"])
        self.assertEqual(self.result["public_suffix_stale"],
                         {"taken": "2020-01-01", "age_days": age})

    def test_both_reports_say_it(self):
        for output in (render_markdown(self.result), render_html(self.result)):
            self.assertIn("public suffix list", output)
            self.assertIn("2020-01-01", output)


class AListThatDecidedNothing(unittest.TestCase):

    def test_a_property_the_operator_named_is_not_warned_about(self):
        run = audit(snapshot("// snapshot taken 2020-01-01\n"),
                    "--gsc-property", "sc-domain:example.co.uk")
        self.assertIn("GSC property: sc-domain:example.co.uk", run["_stderr"])
        self.assertNotIn("public suffix list", run["_stderr"])
        self.assertIsNone(run["public_suffix_stale"])
        for output in (render_markdown(run), render_html(run)):
            self.assertNotIn("public suffix list", output)

    def test_no_search_console_means_no_property_and_no_warning(self):
        run = audit(snapshot("// snapshot taken 2020-01-01\n"), credentials=False)
        self.assertNotIn("GSC property", run["_stderr"])
        self.assertNotIn("public suffix list", run["_stderr"])
        self.assertIsNone(run["public_suffix_stale"])

    def test_a_fresh_list_that_decided_the_property_is_not_warned_about(self):
        run = audit(snapshot(f"// snapshot taken {today().isoformat()}\n"))
        self.assertIn("GSC property: sc-domain:example.co.uk", run["_stderr"])
        self.assertNotIn("public suffix list", run["_stderr"])
        self.assertIsNone(run["public_suffix_stale"])


class AListThatCannotSayWhenItWasTaken(unittest.TestCase):
    """The age is reported as unknown, never read as fresh: until F04 an unreadable
    date was age -1, under any threshold, and the run said nothing."""

    def test_an_undated_list_that_decided_the_property_says_its_age_is_unknown(self):
        run = audit(snapshot("// snapshot taken last Tuesday\n"))
        self.assertIn("GSC property: sc-domain:example.co.uk", run["_stderr"])
        self.assertIn("public suffix list snapshot carries no readable date",
                      run["_stderr"])
        self.assertEqual(run["public_suffix_stale"], {"taken": None, "age_days": None})
        for output in (render_markdown(run), render_html(run)):
            self.assertIn("no readable date", output)


if __name__ == "__main__":
    unittest.main()
