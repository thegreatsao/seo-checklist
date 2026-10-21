"""EVD-1: a checker exits 0 and hands back its defined shape when it has nothing to work with.

The runner classifies a non-zero exit as a crash — a defect report about the checker —
so a checker that exits non-zero to mean "the site was down" files a maintenance ticket
where the run should have said `NO_DATA`. Until F04 the empty case was asserted only for
the handful of checkers whose tests construct it and inherited for the rest. Here every
job the registry plans is run the way the runner runs it — its own process, through
`checklist_runner.run_script` — in two situations that give it nothing: a site that
refuses every connection, and a site that answers every request with an empty 200. Every
operator input is handed over as an empty file, which is nothing to parse.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from harness import SCRIPTS, closed_port, offline_env, served

sys.path.insert(0, SCRIPTS)
import checklist_runner as cr  # noqa: E402

REGISTRY = os.path.join(SCRIPTS, os.pardir, "resources", "config", "checklist.json")
# What the runner calls a checker that broke rather than one that said why it could not
# answer (`run_script`): its exit, its stdout, or the signal that ended it.
BROKE = ("crash", "bad_output", "signal")


def empty_inputs() -> dict:
    """Every operator input the registry can ask for, as an empty file."""
    work = tempfile.mkdtemp(prefix="seo-empty-inputs-")
    paths = {}
    for name in ("html", "inventory_json", "rendered_json", "cwv_json", "links_csv",
                 "server_log", "gsc_credentials"):
        path = os.path.join(work, name)
        open(path, "w").close()
        paths[name] = path
    return paths


def run_every_job(url: str, only: set | None = None,
                  env: dict | None = None) -> tuple[dict, dict]:
    with open(REGISTRY, encoding="utf-8") as f:
        items = json.load(f)["items"]
    ctx = {"url": url, "keyword": "nothing", "indexnow_key": "abcd1234abcd1234abcd",
           "gsc_property": "sc-domain:example.com", **empty_inputs()}
    plan, _ = cr.build_plan(items, ctx, set(cr.MODE_CAPS["live"]), "live", has_gsc=True)
    plan = {key: ids for key, ids in plan.items() if only is None or key[0] in only}
    with mock.patch.dict(os.environ, env or offline_env()):
        results = {key: cr._timed(key, 120) for key in plan}
    return plan, results


def broken(results: dict) -> list[str]:
    return [f"{key[0]} {' '.join(map(str, key[1]))[:80]}: "
            f"{data.get('__error_kind__')} — {str(data.get('__error__'))[:200]}"
            for key, data in results.items()
            if data.get("__error_kind__") in BROKE]


# The Search Console family needs the optional `gsc` extra, which neither this suite nor
# CI installs. Until F04 `gsc_checker.build_service` answered its absence with
# `sys.exit(1)` and an unusable key file with a traceback, and the runner read both as
# a broken script: an operator who passed a key without installing the extra, or passed
# the wrong file, was sent to open four scripts that had nothing wrong with them.
GSC_FAMILY = {"gsc_checker.py", "gsc_cannibalization.py", "gsc_sitemap_reconcile.py",
              "gsc_url_inspection.py"}

# The extra, stood in for where it is absent: the key reader parses the file the way
# `google.oauth2.service_account` does and refuses one that is not a service-account
# key; nothing past it is reached with such a file.
EXTRA_STUB = {
    "google/__init__.py": "",
    "google/oauth2/__init__.py": "",
    "google/oauth2/service_account.py": (
        "import json\n"
        "class Credentials:\n"
        "    @classmethod\n"
        "    def from_service_account_file(cls, filename, **kwargs):\n"
        "        with open(filename, encoding='utf-8') as f:\n"
        "            info = json.load(f)\n"
        "        missing = {'client_email', 'token_uri'} - set(info)\n"
        "        if missing:\n"
        "            raise ValueError('Service account info was not in the expected '\n"
        "                             'format, missing fields ' + ', '.join(sorted(missing)))\n"
        "        return cls()\n"),
    "googleapiclient/__init__.py": "",
    "googleapiclient/discovery.py": (
        "def build(*args, **kwargs):\n"
        "    raise AssertionError('not reached with an unusable key')\n"),
}


def stub_extra() -> str:
    root = tempfile.mkdtemp(prefix="seo-gsc-extra-")
    for rel, text in EXTRA_STUB.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


class NothingToReach(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.plan, cls.results = run_every_job(f"http://127.0.0.1:{closed_port()}/")

    def test_every_job_the_registry_plans_was_run(self):
        # A census that planned nothing would pass the test below.
        scripts = {key[0] for key in self.plan}
        self.assertGreaterEqual(len(scripts), 50, sorted(scripts))

    def test_no_checker_breaks_when_the_site_refuses_every_connection(self):
        wrong = broken(self.results)
        self.assertEqual(wrong, [], "\n".join(wrong))


class NothingToParse(unittest.TestCase):

    def test_no_checker_breaks_when_every_answer_is_an_empty_page(self):
        with served({"/": "", "/robots.txt": (200, ""), "/sitemap.xml": (200, "")}) as site:
            _, results = run_every_job(site.url)
        wrong = broken(results)
        self.assertEqual(wrong, [], "\n".join(wrong))


class SearchConsoleWithoutAUsableKey(unittest.TestCase):
    """Both causes are the operator's, and both are said as `input` with the remedy."""

    def kinds(self, env: dict) -> dict:
        plan, results = run_every_job(f"http://127.0.0.1:{closed_port()}/",
                                      only=GSC_FAMILY, env=env)
        self.assertEqual({key[0] for key in plan}, GSC_FAMILY)
        return {key[0]: (data.get("__error_kind__"), str(data.get("__error__")))
                for key, data in results.items()}

    def test_the_extra_absent_is_said_as_an_input(self):
        # The checkers run on this interpreter, so what it can import is what they can.
        if importlib.util.find_spec("googleapiclient") is not None:
            self.skipTest("the gsc extra is installed here")
        for script, (kind, error) in self.kinds(offline_env()).items():
            with self.subTest(script=script):
                self.assertEqual(kind, "input", error)
                self.assertIn("pip install", error)

    def test_a_key_file_that_is_not_a_key_is_said_as_an_input(self):
        stub = stub_extra()
        env = offline_env()
        env["PYTHONPATH"] = os.pathsep.join([stub, env["PYTHONPATH"]])
        for script, (kind, error) in self.kinds(env).items():
            with self.subTest(script=script):
                self.assertEqual(kind, "input", error)
                self.assertIn("not a service-account key", error)


class NotOneDocument(unittest.TestCase):
    """The third scenario: output that is not one JSON document breaks the contract
    whatever the exit code says, and the runner calls it `bad_output`."""

    def returns(self, stdout: str) -> dict:
        import subprocess

        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(subprocess, "run", return_value=done):
            return cr.run_script("detect_profile.py", ["--html", __file__])

    def test_two_documents_are_unusable_output(self):
        self.assertEqual(self.returns('{"a": 1}\n{"b": 2}\n').get("error_kind"),
                         "bad_output")

    def test_prose_after_a_document_is_unusable_output(self):
        self.assertEqual(self.returns('{"a": 1}\ndone.\n').get("error_kind"),
                         "bad_output")

    def test_one_document_is_read(self):
        self.assertEqual(self.returns('{"a": 1}\n'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
