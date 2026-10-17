"""A URL may carry a credential, and the run must not write it down.

`openspec/specs/inputs/` INP-7. `http://user:password@host/` is how a staging site behind
Basic authentication is audited, and it works: measured at 0.134.0, an origin that answers
401 to everybody else was audited in full under such a URL. It is also a secret value the
operator typed, and until this file nothing read where it went. Measured the same day, on
the good fixture under `http://auditor:<password>@127.0.0.1:<port>/`
(`local/userinfo/measure.py`):

    the history folder's name          .seo-runs/auditor_<password>@127.0.0.1_<port>/
    the stored run and the results     domain, url, sampled_urls, 102 item URLs,
                                       96 evidence strings, every run-log key
    the evidence file                  484 occurrences
    the crawl inventory                58
    the Markdown report                122
    the HTML report                    133
    each of the five LLM queues        1
    stderr                             the banner and every sampled page
    stdout                             the `History:` line, through the folder name

and two things that were not about writing at all: a link the site writes to itself
*without* the credential went out unauthenticated and was refused, and a run under
`user:password@host` kept a history apart from the same site's runs under `host`.

So the tests below are about one run, read from every side: nothing it writes or prints
carries the credential; the record names the site and says that a credential was used; the
credential still reaches the site, all of the site, and nothing else; and the history is
the site's, whatever was typed in front of the host.
"""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
import http.server
import importlib.util
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import unquote, urlparse, urlunparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from harness import spawn  # noqa: E402

import checklist_runner as runner  # noqa: E402

RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")
REPORT = os.path.join(SCRIPTS, "checklist_report.py")

# Unlike anything a fixture page says, so a hit is the credential and nothing else.
USER, PASSWORD = "auditor7x", "S3cr3tPw0rd9q"
USERINFO = f"{USER}:{PASSWORD}"
BASIC = base64.b64encode(USERINFO.encode()).decode()
# What must appear nowhere: the password, the name it was given with, and the form the
# pair takes on the wire. The name is in the list because a URL may carry a token alone
# (`https://<token>@host/`), so nothing in front of the `@` can be assumed public.
NEEDLES = {"the password": PASSWORD, "the user name": USER, "the Basic token": BASIC}

WORDS = "Words enough that the thin-entry guard has nothing to say about this page. " * 12


def html(title: str, links: str = "") -> str:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<meta name='description' content='A staging site that asks who is there.'>"
            f"</head><body><h1>{title}</h1><p>{WORDS}</p>{links}</body></html>")


class _Origin:
    """A loopback origin that remembers whether each request carried a credential.

    `harness.served` records the method and the path, which is what every other test
    needs; the question here is the one header it does not keep. `protected` answers 401
    to a request without the right Basic credential, as a staging site does.
    """

    def __init__(self, routes, protected: bool):
        seen = self.seen = []         # (path, carried Authorization, it was the right one)
        expect = "Basic " + BASIC

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _answer(self, body_too):
                given = self.headers.get("Authorization")
                # A local port probe is answered and not counted, as in the harness
                # (`harness.is_stranger`): it carries no credential and is not the audit.
                if not harness.is_stranger(self.headers.get("User-Agent")):
                    seen.append((self.path, given is not None, given == expect))
                status, headers, body = 404, {}, "not found"
                if protected and given != expect:
                    status, headers, body = (
                        401, {"WWW-Authenticate": 'Basic realm="staging"'}, "who is there")
                elif self.path.split("?", 1)[0] in routes:
                    status, headers, body = routes[self.path.split("?", 1)[0]]
                raw = body.encode("utf-8")
                self.send_response(status)
                if "Content-Type" not in headers:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if body_too:
                    self.wfile.write(raw)

            def do_GET(self):
                self._answer(True)

            def do_HEAD(self):
                self._answer(False)

            def log_message(self, *args):
                pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.base = f"http://{self.host}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        harness._Site.stop(self)
        # Its credential spelling must not keep an answer after this origin stopped.
        harness.forget_robots(self.base.replace("://", f"://{USERINFO}@", 1))


RUN = {}
LEGACY_RUN, LEGACY_STARTED = "20260101T000000000Z.json", "2026-01-01T00:00:00+00:00"


def written_by_these_runs():
    """`(directory, folders, files)` under the working directory, the older folder left
    out: it is the operator's, it was there before, and its name is the defect."""
    for base, dirs, files in os.walk(RUN["work"]):
        dirs[:] = [d for d in dirs if os.path.join(base, d) != RUN["legacy"]]
        yield base, dirs, files


def setUpModule():
    """One staging site, audited once under a URL that carries the credential, then once
    under the bare host. Every test below reads those two runs."""
    other_routes, routes = {}, {}
    other = RUN["other"] = _Origin(other_routes, protected=False)
    site = RUN["site"] = _Origin(routes, protected=True)
    other_routes.update({
        "/landing.html": (200, {}, html("Where the redirect lands")),
        "/elsewhere.html": (200, {}, html("Somebody else's page")),
        # An entry that sends the audit to the protected site with the credential written
        # into the `Location`: nobody typed it, and it is in the URL the run ends on.
        "/hop": (302, {"Location": f"http://{USERINFO}@{site.host}/"}, ""),
        "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nAllow: /\n"),
    })
    links = (
        "<a href='/about.html'>About</a> "
        # Written by the site in full, and without the credential: the same site.
        f"<a href='{site.base}/contact.html'>Contact</a> "
        # A template that baked the credential into a link. The site's doing, and still
        # the operator's secret once it is in a file somebody is sent.
        f"<a href='http://{USERINFO}@{site.host}/about.html'>About, as pasted</a> "
        "<a href='/moved'>Moved</a> "
        # A page that echoes the request it was asked with: the pair as it went over
        # the wire. The typed form is not in it, so only the token's own entry in the
        # secret set can take it out of what the run writes.
        f"<a href='/about.html?asked-with={BASIC}'>What you sent</a> "
        f"<a href='{other.base}/elsewhere.html'>Elsewhere</a>")
    routes.update({
        "/": (200, {}, html("A site behind a password", links)),
        "/about.html": (200, {}, html("About the site behind a password")),
        "/contact.html": (200, {}, html("How to reach the site behind a password")),
        "/moved": (302, {"Location": f"{other.base}/landing.html"}, ""),
        "/robots.txt": (200, {"Content-Type": "text/plain"},
                        f"User-agent: *\nAllow: /\nSitemap: {site.base}/sitemap.xml\n"),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"},
                         "<?xml version='1.0' encoding='UTF-8'?>"
                         "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                         + "".join(f"<url><loc>{site.base}{p}</loc></url>"
                                   for p in ("/", "/about.html", "/contact.html"))
                         + "</urlset>"),
    })

    work = RUN["work"] = tempfile.mkdtemp(prefix="seo-url-credentials-")
    # What a release up to 0.134.0 left on this operator's disk: an earlier audit of the
    # same site, filed under the whole netloc. Nothing below may write, move or print it.
    legacy = RUN["legacy"] = os.path.join(
        work, ".seo-runs", f"{USER}_{PASSWORD}@{runner.history_folder(site.host)}")
    os.makedirs(legacy)
    with open(os.path.join(legacy, LEGACY_RUN), "w", encoding="utf-8") as stream:
        json.dump({"started_at": LEGACY_STARTED, "domain": f"{USERINFO}@{site.host}",
                   "url": f"http://{USERINFO}@{site.host}/", "items": [],
                   "scores": {"seo_score": 50}}, stream)
    with open(os.path.join(legacy, LEGACY_RUN), "rb") as stream:
        RUN["legacy_bytes"] = stream.read()
    home = os.getcwd()
    # History is written under the working directory and `harness.spawn` takes no `cwd`
    # (see its docstring), so the directory moved is this process's own.
    os.chdir(work)
    try:
        with_credential = f"http://{USERINFO}@{site.host}/"
        common = ["--allow-private", "--max-rps", "0", "--no-prompt", "--timeout", "120"]
        first = spawn([sys.executable, RUNNER, with_credential, *common, "--sample", "3",
                       "--json", os.path.join(work, "results.json"),
                       "--evidence-json", os.path.join(work, "evidence.json")],
                      timeout=900)
        RUN["first"] = first
        RUN["site_seen"] = list(site.seen)
        RUN["other_seen"] = list(other.seen)
        if first.returncode == 0:
            RUN["report"] = spawn(
                [sys.executable, REPORT, os.path.join(work, "results.json"),
                 "--markdown", os.path.join(work, "report.md"),
                 "--html", os.path.join(work, "report.html"),
                 "--llm-queue", os.path.join(work, "queue.md")], timeout=300)
        # The bare run inherits an environment that already names the credential, as
        # a shell would after somebody exported it or a wrapper leaked it. The carrier
        # is the runner's to set and to clear: only the URL says who is asking.
        stale = harness.offline_env(
            SEO_URL_CREDENTIALS=f"http://{USERINFO}@{site.host}")
        RUN["second"] = spawn([sys.executable, RUNNER, site.base + "/", *common,
                               "--only", "speed",
                               "--json", os.path.join(work, "bare.json")],
                              env=stale, timeout=600)
        RUN["bare_seen"] = site.seen[len(RUN["site_seen"]):]
        if RUN["second"].returncode == 0:
            RUN["bare_report"] = spawn(
                [sys.executable, REPORT, os.path.join(work, "bare.json"),
                 "--markdown", os.path.join(work, "bare.md"),
                 "--html", os.path.join(work, "bare.html"),
                 "--llm-queue", os.path.join(work, "bare-queue.md")], timeout=300)
        # `--quiet` asks for nothing but warnings on stderr, and the line about the
        # credential is not one.
        RUN["quiet"] = spawn([sys.executable, RUNNER, with_credential, *common, "--quiet",
                              "--only", "speed", "--no-history",
                              "--json", os.path.join(work, "quiet.json")], timeout=600)
        # Its own working directory: this run is filed under the site as well, and the
        # history tests below count what the first two runs left there.
        hop_work = RUN["hop_work"] = tempfile.mkdtemp(prefix="seo-url-credentials-hop-")
        os.chdir(hop_work)
        RUN["hop"] = spawn([sys.executable, RUNNER, other.base + "/hop", *common,
                            "--only", "speed",
                            "--json", os.path.join(hop_work, "hop.json")], timeout=600)
    finally:
        os.chdir(home)


def tearDownModule():
    for name in ("site", "other"):
        if name in RUN:
            RUN[name].stop()
    shutil.rmtree(RUN.get("work", ""), ignore_errors=True)
    shutil.rmtree(RUN.get("hop_work", ""), ignore_errors=True)


def payload(name: str) -> dict:
    with open(os.path.join(RUN["work"], name), encoding="utf-8") as stream:
        return json.load(stream)


class TheRunsThatEverythingBelowReads(unittest.TestCase):
    """Guards the guards. A run that died, a site nobody reached or a report nobody wrote
    would let every `assertNotIn` below pass over nothing."""

    def test_the_audit_under_the_credential_finished_and_read_the_site(self):
        first = RUN["first"]
        self.assertEqual(first.returncode, 0, first.stderr[-3000:].replace(PASSWORD, "…"))
        record = payload("results.json")
        self.assertTrue(record["entry_reachable"], record.get("entry_error"))
        self.assertGreaterEqual(len(record["sampled_urls"]), 2, record["sampled_urls"])

    def test_every_artifact_the_sweep_expects_was_written(self):
        self.assertEqual(RUN["report"].returncode, 0, RUN["report"].stderr[-2000:])
        for name in ("results.json", "evidence.json", "results-crawl.json", "report.md",
                     "report.html", "queue.md", ".seo-runs"):
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(os.path.join(RUN["work"], name)))

    def test_the_bare_run_finished_too(self):
        self.assertEqual(RUN["second"].returncode, 0, RUN["second"].stderr[-2000:])


class NothingTheRunWritesCarriesTheCredential(unittest.TestCase):
    """INP-7, *a credential typed into the URL*: everything in the working directory —
    the results, the stored run, the evidence, the crawl inventory, both reports and the
    queues — and both streams of both programs."""

    def test_no_file_carries_it(self):
        walked = 0
        for base, _dirs, files in written_by_these_runs():
            for name in files:
                walked += 1
                path = os.path.join(base, name)
                with open(path, "rb") as stream:
                    data = stream.read()
                shown = os.path.relpath(path, RUN["work"]).replace(PASSWORD, "<password>")
                for what, needle in NEEDLES.items():
                    with self.subTest(file=shown, carries=what):
                        self.assertEqual(data.count(needle.encode()), 0,
                                         f"{shown} carries {what}")
        self.assertGreaterEqual(walked, 8, "the sweep walked almost nothing")

    def test_no_path_carries_it(self):
        for _base, dirs, files in written_by_these_runs():
            for name in dirs + files:
                for what, needle in NEEDLES.items():
                    with self.subTest(carries=what,
                                      name=name.replace(PASSWORD, "<password>")):
                        self.assertNotIn(needle, name)

    def test_neither_stream_prints_it(self):
        for label in ("first", "report", "second", "quiet", "hop"):
            proc = RUN.get(label)
            self.assertIsNotNone(proc, f"the {label} program was never started")
            for stream in ("stdout", "stderr"):
                for what, needle in NEEDLES.items():
                    with self.subTest(program=label, stream=stream, carries=what):
                        self.assertNotIn(needle, getattr(proc, stream))


class TheRecordNamesTheSiteAndSaysACredentialWasUsed(unittest.TestCase):
    """INP-7, *the path stays readable*, for a credential that has no path: the record
    cannot say which credential answered without being it, so it says that one did. A
    reader comparing this run with one that met a 401 needs exactly that."""

    def test_the_site_is_the_host_and_port(self):
        record, site = payload("results.json"), RUN["site"]
        self.assertEqual(record["domain"], site.host)
        self.assertEqual(record["url"], site.base + "/")
        for url in record["sampled_urls"]:
            with self.subTest(url=url.replace(PASSWORD, "<password>")):
                self.assertTrue(url.startswith(site.base), "a sampled page is not on "
                                                           "the site the record names")

    def test_the_record_says_a_credential_came_with_the_url(self):
        self.assertIs(payload("results.json").get("url_credentials"), True)

    def test_a_run_without_one_says_so_as_well(self):
        self.assertIs(payload("bare.json").get("url_credentials"), False)

    def test_both_reports_say_so_too(self):
        """The reader this sentence is for holds a report, not the JSON. Until 0.153.0
        the fact was in the record and on neither surface."""
        from checklist_report import Lang, provenance_warnings
        for name in ("report.md", "report.html"):
            with self.subTest(report=name):
                with open(os.path.join(RUN["work"], name), encoding="utf-8") as stream:
                    self.assertEqual(stream.read().count("credential typed into the URL"), 1)
        self.assertIn("credential typed into the URL", RUN["report"].stdout)
        # Both surfaces take the sentence from one list, and so does the translation.
        russian = provenance_warnings(payload("results.json"), Lang("ru"))
        self.assertEqual(sum("учётными данными из URL" in line for line in russian), 1)

    def test_a_report_of_a_run_without_one_does_not(self):
        self.assertEqual(RUN["bare_report"].returncode, 0, RUN["bare_report"].stderr[-2000:])
        for name in ("bare.md", "bare.html"):
            with self.subTest(report=name):
                with open(os.path.join(RUN["work"], name), encoding="utf-8") as stream:
                    self.assertNotIn("credential typed into the URL", stream.read())
        self.assertNotIn("credential typed into the URL", RUN["bare_report"].stdout)

    def test_the_run_that_was_refused_still_says_where_the_host_is(self):
        """The audit without the credential met the site's 401, on a host only this
        machine reaches. Until 0.153.0 an entry that failed was not asked where it
        resolves: the record said the host was not private, and the report of the 401
        page said "the host it audited was public, so the verdicts stand"."""
        bare = payload("bare.json")
        self.assertIs(bare["entry_reachable"], False, "the bare run was let in")
        self.assertIs(bare["entry_private"], True)
        with open(os.path.join(RUN["work"], "bare.md"), encoding="utf-8") as stream:
            report = stream.read()
        self.assertIn("only reachable from the machine", report)
        self.assertNotIn("was public", report)

    def test_the_operator_is_told_what_became_of_it(self):
        self.assertIn("credential from the URL", RUN["first"].stderr)
        self.assertNotIn("credential from the URL", RUN["second"].stderr)

    def test_a_quiet_run_is_not_told(self):
        quiet = RUN["quiet"]
        self.assertEqual(quiet.returncode, 0, quiet.stderr[-2000:].replace(PASSWORD, "…"))
        self.assertIs(payload("quiet.json").get("url_credentials"), True,
                      "the quiet run carried no credential, so its silence says nothing")
        self.assertNotIn("credential from the URL", quiet.stderr)


class ACredentialTheSiteWritesIntoARedirect(unittest.TestCase):
    """The split at the entrance takes out what the operator typed. A `Location` header
    can put a credential into the URL the run *ends* on, and that URL is the one the
    record, the history folder and every script are then given — so it is split again
    where it comes in, and what was in front of the `@` is dropped."""

    def record(self) -> dict:
        with open(os.path.join(RUN["hop_work"], "hop.json"), encoding="utf-8") as stream:
            return json.load(stream)

    def test_the_run_followed_the_redirect_to_the_site(self):
        hop = RUN["hop"]
        self.assertEqual(hop.returncode, 0, hop.stderr[-2000:].replace(PASSWORD, "…"))
        self.assertTrue(self.record()["entry_reachable"], self.record().get("entry_error"))

    def test_the_site_is_named_by_host_and_port(self):
        self.assertEqual(self.record()["domain"], RUN["site"].host)

    def test_nothing_it_wrote_carries_it(self):
        walked = 0
        for base, dirs, files in os.walk(RUN["hop_work"]):
            for name in dirs + files:
                for what, needle in NEEDLES.items():
                    with self.subTest(name=name.replace(PASSWORD, "<password>"),
                                      carries=what):
                        self.assertNotIn(needle, name)
            for name in files:
                walked += 1
                with open(os.path.join(base, name), "rb") as stream:
                    data = stream.read()
                for what, needle in NEEDLES.items():
                    with self.subTest(file=name.replace(PASSWORD, "<password>"),
                                      carries=what):
                        self.assertEqual(data.count(needle.encode()), 0)
        self.assertGreaterEqual(walked, 2, "the sweep walked almost nothing")


class TheCredentialReachesTheSiteAndNothingElse(unittest.TestCase):
    """Taking the credential out of the URL must not take it off the wire, and must not
    put it on any other one."""

    def test_no_request_to_the_site_went_out_without_it(self):
        seen = RUN["site_seen"]
        self.assertGreater(len(seen), 10, "the audit hardly asked the site anything")
        refused = sorted({path for path, _carried, right in seen if not right})
        self.assertEqual(refused, [], "requests the site refused for want of the "
                                      "credential the operator gave")

    def test_a_link_the_site_writes_in_full_is_asked_with_it(self):
        """The site's own absolute link carries no userinfo. While the credential lived
        in the URL, such a link was another host by name and went out bare: refused, and
        reported as the site's broken link."""
        asked = [right for path, _carried, right in RUN["site_seen"]
                 if path == "/contact.html"]
        self.assertTrue(asked, "nothing asked for /contact.html, so this proves nothing")
        self.assertTrue(all(asked), "the site's own page was asked for without the "
                                    "credential")

    def test_a_run_whose_url_carries_none_sends_none(self):
        """Whatever the environment it was started in says."""
        seen = RUN["bare_seen"]
        self.assertTrue(seen, "the bare run asked the site nothing")
        self.assertEqual(sorted({path for path, carried, _right in seen if carried}), [])
        self.assertFalse(payload("bare.json")["entry_reachable"])

    def test_another_origin_is_never_handed_it(self):
        """Another port on the same address is another origin: reached by a redirect from
        the site and by a link on it, and owed nothing."""
        seen = RUN["other_seen"]
        self.assertTrue(seen, "nothing reached the other origin, so this proves nothing")
        self.assertEqual(sorted({path for path, carried, _right in seen if carried}), [])


class EveryWayARequestLeavesCarriesIt(unittest.TestCase):
    """`_paced_request` sends a request from three places: through an address the guard
    pinned, without a pin when the resolver found none, and once more after a
    `Retry-After`. Every origin a test serves resolves, so the audits above only ever
    leave by the first — and a probe that took the credential off either of the other
    two left all of them green. Each is asked here by itself."""

    def setUp(self):
        self.http = harness.safe_http()
        self.origin = _Origin({"/": (200, {}, html("A quiet page")),
                               "/busy": (429, {"Retry-After": "1"}, "slow down")},
                              protected=True)
        self.env = mock.patch.dict(os.environ, {
            "SEO_ALLOW_PRIVATE": "1", "SEO_MAX_RPS": "0",
            "SEO_URL_CREDENTIALS": f"http://{USERINFO}@{self.origin.host}"})
        self.env.start()
        self.session = self.http.requests.Session()

    def tearDown(self):
        self.session.close()
        self.env.stop()
        self.origin.stop()

    def test_a_request_with_no_pinned_address(self):
        answer = self.http._paced_request(self.session, "GET", self.origin.base + "/",
                                          {}, 10, {}, ())
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.origin.seen, [("/", True, True)])

    def test_a_port_probe_is_answered_and_is_not_one_of_them(self):
        """This origin counts every request, so a probe of its port is one more. On the
        Mac the push gate runs on, the probe's User-Agent was not the one name the
        harness knew, and the test below read four requests where two were made."""
        for agent in ("Workbench",
                      "Workbench%20Native/1.4.2 CFNetwork/3896.100.1.1.1 Darwin/27.0.0"):
            connection = http.client.HTTPConnection("127.0.0.1", self.origin.port,
                                                    timeout=10)
            try:
                connection.request("GET", "/", headers={"User-Agent": agent})
                self.assertEqual(connection.getresponse().status, 401)
            finally:
                connection.close()
        self.assertEqual(self.origin.seen, [])

    def test_the_request_made_again_after_a_retry_after(self):
        answer = self.http._paced_request(self.session, "GET", self.origin.base + "/busy",
                                          {}, 10, {}, ("127.0.0.1",))
        self.assertEqual(answer.status_code, 429)
        self.assertEqual(self.origin.seen, [("/busy", True, True), ("/busy", True, True)],
                         "the site asked for a pause and the request that came back "
                         "after it was not the one that had been sent")


class OneSiteOneHistory(unittest.TestCase):
    """`openspec/specs/history/`: a run is filed under the site it describes. What was
    typed in front of the host is how the operator got in, not which site it is."""

    def test_both_runs_are_filed_under_the_host_and_port(self):
        root = os.path.join(RUN["work"], ".seo-runs")
        folder = runner.history_folder(RUN["site"].host)
        self.assertEqual(sorted(os.listdir(root)),
                         sorted([folder, os.path.basename(RUN["legacy"])]))
        self.assertEqual(len(os.listdir(os.path.join(root, folder))), 2)

    def test_the_run_under_the_credential_is_compared_with_the_older_folders_run(self):
        """Through `main`, not through the lookup alone: the site named to the lookup has
        to be the one the stored run is matched against."""
        first = payload("results.json")
        self.assertIsNotNone(first["compared_with"], "the run an earlier release filed "
                                                     "under the whole netloc was not read")
        self.assertEqual(first["compared_with"]["started_at"], LEGACY_STARTED)
        self.assertEqual([row["started_at"] for row in first["history"]][0], LEGACY_STARTED)

    def test_the_older_folder_is_left_exactly_as_it_was(self):
        self.assertEqual(os.listdir(RUN["legacy"]), [LEGACY_RUN])
        with open(os.path.join(RUN["legacy"], LEGACY_RUN), "rb") as stream:
            self.assertEqual(stream.read(), RUN["legacy_bytes"])

    def test_the_operator_is_told_the_older_folder_is_there_without_being_shown_it(self):
        """A password in a directory name is still on the disk after this release, and
        `.seo-runs/` is a folder people zip and send. Said once, with the credential
        masked: the streams are swept for it like every file."""
        folder = runner.history_folder(RUN["site"].host)
        self.assertIn(f"***@{folder}", RUN["first"].stderr)

    def test_the_bare_run_is_compared_with_the_one_under_the_credential(self):
        first, second = payload("results.json"), payload("bare.json")
        self.assertIsNotNone(second["compared_with"],
                             "the same site, audited a minute later, had no previous run")
        self.assertEqual(second["compared_with"]["started_at"], first["started_at"])


class RunsAlreadyFiledUnderANameCarryingUserinfo(unittest.TestCase):
    """Every release up to this one filed such a run under the whole netloc: verbatim
    before 0.134.0 (`user:pw@host`, where a colon is legal), sanitised at 0.134.0
    (`user_pw@host`). Those folders are on operators' disks. They are read — the arc of a
    site does not restart because the tool learned to leave a password out of a name — and
    they are neither written to nor moved."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir, ignore_errors=True)

    def stored(self, folder, name, started, points, domain=None):
        os.makedirs(os.path.join(".seo-runs", folder), exist_ok=True)
        record = {"started_at": started, "scores": {"seo_score": points}}
        if domain is not None:
            record["domain"] = domain
        with open(os.path.join(".seo-runs", folder, name), "w", encoding="utf-8") as f:
            json.dump(record, f)

    def test_the_sanitised_folder_is_read(self):
        self.stored(f"{USER}_{PASSWORD}@alpha.example", "20260803T090000000Z.json",
                    "2026-08-03T09:00:00+00:00", 41, f"{USERINFO}@alpha.example")
        self.assertEqual(runner.previous_run("alpha.example", "")["scores"]["seo_score"], 41)
        new = runner.history_path("alpha.example", "20260901T090000000Z")
        self.assertEqual(os.path.basename(os.path.dirname(new)), "alpha.example")
        with open(new, "w", encoding="utf-8") as f:
            json.dump({"started_at": "2026-09-01T09:00:00+00:00", "domain": "alpha.example",
                       "scores": {"seo_score": 92}}, f)
        self.assertEqual([r["seo_score"] for r in runner.run_series("alpha.example", "")],
                         [41, 92])
        self.assertEqual(runner.previous_run("alpha.example", new)["scores"]["seo_score"], 41)

    def test_a_ported_host_is_read_the_same_way(self):
        self.stored("u_p@localhost_3000", "20260803T090000000Z.json",
                    "2026-08-03T09:00:00+00:00", 41, "u:p@localhost:3000")
        self.assertEqual(runner.previous_run("localhost:3000", "")["scores"]["seo_score"], 41)
        # The folder name is not reversible: a host called `localhost_3000` shares it,
        # and the stored run says which of the two it was.
        self.assertIsNone(runner.previous_run("localhost_3000", ""))

    def test_a_token_with_no_password_and_several_credentials_over_time(self):
        self.stored("tok3n@alpha.example", "20260701T090000000Z.json",
                    "2026-07-01T09:00:00+00:00", 11, "tok3n@alpha.example")
        self.stored("u_old@alpha.example", "20260801T090000000Z.json",
                    "2026-08-01T09:00:00+00:00", 22, "u:old@alpha.example")
        self.stored("alpha.example", "20260901T090000000Z.json",
                    "2026-09-01T09:00:00+00:00", 33, "alpha.example")
        self.assertEqual([r["seo_score"] for r in runner.run_series("alpha.example", "")],
                         [11, 22, 33])

    def test_a_stored_run_from_before_the_record_named_its_site_is_read(self):
        self.stored("u_p@alpha.example", "20260803T090000000Z.json",
                    "2026-08-03T09:00:00+00:00", 41)
        self.assertEqual(runner.previous_run("alpha.example", "")["scores"]["seo_score"], 41)

    @unittest.skipIf(os.name == "nt", "a folder named user:pw@host cannot exist on Windows")
    def test_the_verbatim_folder_is_read(self):
        self.stored("u:p@alpha.example", "20260803T090000000Z.json",
                    "2026-08-03T09:00:00+00:00", 41, "u:p@alpha.example")
        self.assertEqual(runner.previous_run("alpha.example", "")["scores"]["seo_score"], 41)

    def test_another_sites_folder_is_not(self):
        self.stored("u_p@beta.example", "20260803T090000000Z.json",
                    "2026-08-03T09:00:00+00:00", 5, "u:p@beta.example")
        # Ends with the right name and holds another site's run.
        self.stored("x@alpha.example", "20260803T100000000Z.json",
                    "2026-08-03T10:00:00+00:00", 6, "x@gamma.example")
        # Ends with the name without the `@` that makes it userinfo.
        self.stored("notalpha.example", "20260803T110000000Z.json",
                    "2026-08-03T11:00:00+00:00", 7, "notalpha.example")
        # Filed under this site's older name, and holding a run of a site whose own
        # name merely ends the same way: the stored name is compared whole.
        self.stored("y@alpha.example", "20260803T120000000Z.json",
                    "2026-08-03T12:00:00+00:00", 8, "notalpha.example")
        self.stored("z@alpha.example", "20260803T130000000Z.json",
                    "2026-08-03T13:00:00+00:00", 9, "z@notalpha.example")
        self.assertIsNone(runner.previous_run("alpha.example", ""))
        self.assertEqual(runner.run_series("alpha.example", ""), [])

    def test_the_older_folder_is_read_and_left_as_it_was(self):
        folder = f"{USER}_{PASSWORD}@alpha.example"
        self.stored(folder, "20260803T090000000Z.json", "2026-08-03T09:00:00+00:00", 41,
                    f"{USERINFO}@alpha.example")
        with open(os.path.join(".seo-runs", folder, "20260803T090000000Z.json"), "rb") as f:
            before = f.read()
        self.assertEqual(runner.previous_run("alpha.example", "")["scores"]["seo_score"], 41)
        new = runner.history_path("alpha.example", "20260901T090000000Z")
        with open(new, "w", encoding="utf-8") as f:
            json.dump({"started_at": "2026-09-01T09:00:00+00:00"}, f)
        runner.run_series("alpha.example", new)
        self.assertEqual(sorted(os.listdir(".seo-runs")), sorted([folder, "alpha.example"]))
        self.assertEqual(os.listdir(os.path.join(".seo-runs", folder)),
                         ["20260803T090000000Z.json"])
        with open(os.path.join(".seo-runs", folder, "20260803T090000000Z.json"), "rb") as f:
            self.assertEqual(f.read(), before)


class TheUrlIsSplitWhereItComesIn(unittest.TestCase):
    """`split_userinfo(url)` gives the URL every later step sees and the userinfo, exactly
    as typed. The URL is otherwise untouched: this is not a normaliser."""

    CASES = (
        ("http://u:p@host.example/", "http://host.example/", "u:p"),
        ("http://u:\tp@host.example/", "http://host.example/", "u:p"),
        ("http://u:p@ho\tst.example/", "http://ho\tst.example/", "u:p"),
        ("http:\t//u:p@host.example/", "http:\t//host.example/", "u:p"),
        ("http://u:p@host.example/a\r\nb", "http://host.example/a\r\nb", "u:p"),
        ("https://u:p@host.example:8443/a/b?q=1#f", "https://host.example:8443/a/b?q=1#f",
         "u:p"),
        ("https://tok3n@host.example/", "https://host.example/", "tok3n"),
        ("http://u:@host.example/", "http://host.example/", "u:"),
        ("http://@host.example/", "http://host.example/", ""),
        # Percent-encoded as typed, and kept that way: decoding is for the wire.
        ("http://u:p%40ss@host.example/", "http://host.example/", "u:p%40ss"),
        # A raw `@` in the password: the host starts after the last one.
        ("http://u:p@ss@host.example/", "http://host.example/", "u:p@ss"),
        ("http://u:p@[::1]:8080/", "http://[::1]:8080/", "u:p"),
        ("http://u:p@HOST.Example/Path", "http://HOST.Example/Path", "u:p"),
        # No userinfo: the same string back, whatever else it holds.
        ("https://host.example/?q=a@b", "https://host.example/?q=a@b", ""),
        ("https://host.example/a@b", "https://host.example/a@b", ""),
        ("https://host.example", "https://host.example", ""),
        ("host.example/page", "host.example/page", ""),
    )

    def test_each_shape(self):
        from lib.typed_credential import split_userinfo
        for typed, clean, userinfo in self.CASES:
            with self.subTest(typed=typed):
                self.assertEqual(split_userinfo(typed), (clean, userinfo))

    def test_the_runner_and_the_scripts_split_with_one_function(self):
        from lib import typed_credential
        self.assertIs(runner.split_userinfo, typed_credential.split_userinfo)


class WhatAScriptStartedByHandWasTyped(unittest.TestCase):
    """`typed_credential.credentials_beside_argv` is the runner's entrance for a script started by hand:
    every argument holding an http(s) URL with userinfo is split where it stands, and
    the userinfo goes beside it in the environment. One that holds none changes nothing,
    and that is every argument a script is given by the runner."""

    def test_an_argument_is_split_where_it_stands(self):
        from lib import typed_credential
        argv = ["p.py", "https://u:p%40ss@host.example:8443/a?q=1", "--site=HTTPS://u:p%40ss@host.example:8443/",
                "-uhttps://u:p%40ss@host.example:8443/b", "plain", "https://other.example/?x=a@b",
                "host.example/a@b"]
        with mock.patch.dict(os.environ):
            os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
            typed_credential.credentials_beside_argv(argv)
            self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                             "https://u:p%40ss@host.example:8443")
        self.assertEqual(argv, ["p.py", "https://host.example:8443/a?q=1",
                                "--site=HTTPS://host.example:8443/",
                                "-uhttps://host.example:8443/b", "plain",
                                "https://other.example/?x=a@b", "host.example/a@b"])

    def test_a_url_typed_without_a_scheme_is_split_where_it_stands(self):
        """With the scheme every program gives it, `https://`. Only `name@host` with
        nothing after the host is left as typed: it is an e-mail address as much as a
        URL, and only where a scheme is put in front of it is it read as the URL."""
        from lib import typed_credential
        argv = ["p.py", "u:p%40ss@host.example:8443/a?q=1", "--site=u:p%40ss@host.example:8443/",
                "-uu:p%40ss@host.example:8443/b", "tok@host.example", "--entity=tok@host.example"]
        with mock.patch.dict(os.environ), \
                mock.patch.object(typed_credential, "_maybe_text", set(), create=True):
            os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
            typed_credential.credentials_beside_argv(argv)
            self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                             "https://u:p%40ss@host.example:8443")
            self.assertEqual(argv, ["p.py", "https://host.example:8443/a?q=1",
                                    "--site=https://host.example:8443/",
                                    "-uhttps://host.example:8443/b", "tok@host.example",
                                    "--entity=tok@host.example"])
        for typed in ("tok@host.example/", "tok@host.example:8443", "tok@host.example?x=1"):
            argv = ["p.py", typed]
            with self.subTest(typed=typed), mock.patch.dict(os.environ):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                typed_credential.credentials_beside_argv(argv)
                self.assertEqual(argv[1], "https://" + typed.replace("tok@", ""))
                self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                                 "https://tok@" + typed[4:].split("/")[0].split("?")[0])

    def test_an_address_kept_as_typed_is_a_credential_where_it_is_read_as_a_url(self):
        import seo_common
        from lib import safe_http, typed_credential
        for normalise, read in ((safe_http.normalize_url, "https://host.example/"),
                                (seo_common.normalize_url, "https://host.example/")):
            with self.subTest(normalise=normalise.__module__), mock.patch.dict(os.environ), \
                    mock.patch.object(typed_credential, "_maybe_text", set(), create=True):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                typed_credential.credentials_beside_argv(["p.py", "tok@host.example",
                                                          "--entity", "me@example.com"])
                self.assertNotIn(typed_credential.URL_CREDENTIALS_VAR, os.environ)
                self.assertEqual(normalise("tok@host.example"), read)
                self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                                 "https://tok@host.example")
                # The other address was typed too, and a second credential is refused.
                with self.assertRaises(SystemExit):
                    normalise("me@example.com")

    def test_nothing_typed_leaves_the_runners_credential_where_it_is(self):
        from lib import typed_credential
        argv = ["p.py", "https://host.example/", "--json"]
        with mock.patch.dict(os.environ, {typed_credential.URL_CREDENTIALS_VAR: "https://u:p@host.example"}):
            typed_credential.credentials_beside_argv(argv)
            self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                             "https://u:p@host.example")
        with mock.patch.dict(os.environ):
            os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
            typed_credential.credentials_beside_argv(argv)
            self.assertNotIn(typed_credential.URL_CREDENTIALS_VAR, os.environ)
        self.assertEqual(argv, ["p.py", "https://host.example/", "--json"])

    def test_two_credentials_are_refused_before_anything_is_asked(self):
        from lib import typed_credential
        for second in ("https://v:q@host.example/", "http://u:p@host.example/",
                       "https://u:p@other.example/"):
            with self.subTest(second=second), mock.patch.dict(os.environ):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                with self.assertRaises(SystemExit) as refused:
                    typed_credential.credentials_beside_argv(
                        ["p.py", "https://u:p@host.example/", second])
                self.assertNotIn(":p@", str(refused.exception))
                self.assertNotIn(typed_credential.URL_CREDENTIALS_VAR, os.environ)
        argv = ["p.py", "https://u:p@host.example/", "https://u:p@host.example/b"]
        with mock.patch.dict(os.environ):
            typed_credential.credentials_beside_argv(argv)
            self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR], "https://u:p@host.example")

    def test_a_url_file_naming_another_credential_is_refused_as_the_command_line_is(self):
        """`read_urls` splits a file of URLs after the command line has been split. A
        file naming another credential used to replace the command line's silently,
        and the site typed there was asked without its own."""
        import seo_common
        from lib import typed_credential
        folder = tempfile.mkdtemp(prefix="seo-urlfile-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        for listed, refused in (("https://v:q@host.example/a", True),
                                ("https://u:p@other.example/a", True),
                                ("https://u:p@host.example/a", False),
                                ("https://host.example/a", False)):
            url_file = os.path.join(folder, "urls.txt")
            with open(url_file, "w", encoding="utf-8") as f:
                f.write(listed + "\n")
            with self.subTest(listed=listed), mock.patch.dict(os.environ):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                argv = ["p.py", "https://u:p@host.example/"]
                typed_credential.credentials_beside_argv(argv)
                if refused:
                    with self.assertRaises(SystemExit) as said:
                        seo_common.read_urls(argv[1:], url_file)
                    self.assertNotIn(":p@", str(said.exception))
                    self.assertNotIn(":q@", str(said.exception))
                else:
                    self.assertEqual(seo_common.read_urls(argv[1:], url_file),
                                     ["https://host.example/", "https://host.example/a"])
                self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                                 "https://u:p@host.example")


class WhatIsNotASchemelessCredentialIsReadAsBefore(unittest.TestCase):
    """A URL typed with its scheme, one without userinfo, and an e-mail address are read
    exactly as at 0.163.0 (756a427) by both normalisers, by `is_url`, and by the
    entrance, which leaves the arguments and the environment as they were. The values
    below were taken at 0.163.0 on 3.14 and 3.10.20; the one the standard library
    writes differently from one patch release to another is computed as 0.163.0
    computed it. A normaliser handed a string nobody typed reads it as it
    did, credential-shaped or not: a page's link is not the operator's credential."""

    AT_0163 = (
        # typed, safe_http.normalize_url, seo_common.normalize_url, is_url
        ("staging.example", "https://staging.example/", "https://staging.example/", True),
        ("staging.example/", "https://staging.example/", "https://staging.example/", False),
        ("staging.example:8443/a", "Invalid URL scheme: staging.example",
         "staging.example:8443/a", False),
        ("localhost:8000", "Invalid URL scheme: localhost", "localhost:8000", False),
        ("Staging.Example/a?q=1#f", "https://Staging.Example/a?q=1#f",
         "https://Staging.Example/a?q=1", False),
        ("https://u:p@staging.example/", "https://u:p@staging.example/",
         "https://u:p@staging.example/", True),
        ("http://tok@staging.example:8080/x", "http://tok@staging.example:8080/x",
         "http://tok@staging.example:8080/x", True),
        ("https://staging.example/?next=a@b", "https://staging.example/?next=a@b",
         "https://staging.example/?next=a@b", True),
        ("staging.example/a@b", "https://staging.example/a@b", "https://staging.example/a@b",
         False),
        ("me@example.com", "https://me@example.com/", "https://me@example.com/", True),
        ("mailto:me@example.com", "Invalid URL scheme: mailto", "mailto:me@example.com", True),
        # 0.163.0 put `https:` in front and wrote the parse back with `urlunparse`, which
        # keeps the empty authority on 3.10.20 and 3.14 and drops it on 3.10.11, which was
        # CI's Windows leg then: patch releases of one Python differ here, so the value
        # is what that expression gives on this interpreter.
        ("//staging.example/x", "URL must include a hostname",
         urlunparse(urlparse("https:////staging.example/x")), False),
        ("user:pw@staging.example/", "Invalid URL scheme: user", "user:pw@staging.example/",
         False),
        ("tok@staging.example", "https://tok@staging.example/", "https://tok@staging.example/",
         True),
    )

    def test_the_normalisers_read_what_nobody_typed_as_they_did(self):
        import seo_common
        from lib import safe_http, typed_credential
        for typed, strict, lenient, url in self.AT_0163:
            with self.subTest(typed=typed), mock.patch.dict(os.environ), \
                    mock.patch.object(typed_credential, "_maybe_text", set(), create=True):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                try:
                    self.assertEqual(safe_http.normalize_url(typed), strict)
                except safe_http.SafeHTTPError as refused:
                    self.assertEqual(str(refused), strict)
                self.assertEqual(seo_common.normalize_url(typed), lenient)
                self.assertIs(seo_common.is_url(typed), url)
                self.assertNotIn(typed_credential.URL_CREDENTIALS_VAR, os.environ)

    def test_the_entrance_leaves_them_as_typed(self):
        from lib import typed_credential
        for typed, *_ in self.AT_0163:
            if "://" in typed and "@" in typed.split("/")[2] or typed.startswith("user:"):
                continue                # split at 0.163.0 already, or meant to be now
            argv = ["p.py", typed, f"--entity={typed}", "--keyword", typed]
            with self.subTest(typed=typed), mock.patch.dict(os.environ):
                os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
                typed_credential.credentials_beside_argv(argv)
                self.assertEqual(argv, ["p.py", typed, f"--entity={typed}", "--keyword", typed])
                self.assertNotIn(typed_credential.URL_CREDENTIALS_VAR, os.environ)

    def test_a_url_typed_with_its_scheme_is_split_as_it_was(self):
        from lib import typed_credential
        argv = ["p.py", "https://u:p@staging.example/", "--entity=http://tok@staging.example:8080/x"]
        with mock.patch.dict(os.environ):
            os.environ.pop(typed_credential.URL_CREDENTIALS_VAR, None)
            with self.assertRaises(SystemExit):
                typed_credential.credentials_beside_argv(list(argv))
            typed_credential.credentials_beside_argv(argv[:2])
            self.assertEqual(os.environ[typed_credential.URL_CREDENTIALS_VAR],
                             "https://u:p@staging.example")


class WhatIsAddedToTheSecretSet(unittest.TestCase):
    """The split takes the credential out of every URL the run builds. What the *site*
    hands back is another route — a link with the credential baked in, a page that echoes
    the request — and redaction is what stands there. The forms are the specific ones: the
    bare password is not among them, because a password of one letter would then be
    replaced in every word of the record."""

    @staticmethod
    def written(userinfo: str, text: str) -> str:
        """`text` as the run would write it after a URL carrying `userinfo`."""
        return runner.redact(text, runner.url_credential_secrets(userinfo))

    def test_the_forms(self):
        token = base64.b64encode(b"u:p@ss").decode()
        for said, kept in (("http://u:p%40ss@host/x", "http://<redacted>host/x"),
                           ("signed in as u:p@ss@host", "signed in as <redacted>host"),
                           (f"/about?asked-with={token}", "/about?asked-with=<redacted>"),
                           (f"Authorization: Basic {token}", "Authorization: Basic <redacted>")):
            with self.subTest(said=said):
                self.assertEqual(self.written("u:p%40ss", said), kept)

    def test_a_token_alone(self):
        token = base64.b64encode(b"tok3n:").decode()
        self.assertEqual(self.written("tok3n", "https://tok3n@host/"),
                         "https://<redacted>host/")
        self.assertEqual(self.written("tok3n", f"sent {token}."), "sent <redacted>.")

    def test_a_form_is_the_whole_of_what_stood_before_the_at(self):
        """Until 0.153.0 a form was replaced wherever its letters stood. A URL typed as
        `http://a@host/` turned `anna@example.com` into `ann<redacted>example.com` in
        every page the audit read, and its four-letter token was cut out of the middle
        of any longer run of base64. A form begins where a name can begin, and the token
        is a whole run."""
        for said in ("anna@example.com", "data@host", "write to j.a@example.com",
                     "user:a@host", "xYTo=y", "aGVsbG8YTo="):
            with self.subTest(left_alone=said):
                self.assertEqual(self.written("a", said), said)
        for said, kept in (("http://a@host/", "http://<redacted>host/"),
                           ("mail a@example.com", "mail <redacted>example.com"),
                           ("Basic YTo=", "Basic <redacted>"),
                           ("token=YTo=&next", "token=<redacted>&next")):
            with self.subTest(said=said):
                self.assertEqual(self.written("a", said), kept)
        self.assertEqual(self.written("admin", "sysadmin@example.com"),
                         "sysadmin@example.com")
        self.assertEqual(self.written("admin", "admin@example.com"),
                         "<redacted>example.com")
        # The other end of a run: `u:p@ss` encodes with no padding, so a longer value
        # can begin with its token, and that value is not the credential either.
        longer = base64.b64encode(b"u:p@ssextra").decode()
        self.assertTrue(longer.startswith(base64.b64encode(b"u:p@ss").decode()))
        self.assertEqual(self.written("u:p%40ss", longer), longer)

    def test_nothing_typed_nothing_added(self):
        self.assertEqual(tuple(runner.url_credential_secrets("")), ())


class TheResponseCacheHoldsWhatTheSiteSaidAndNothingTheRunWasGiven(unittest.TestCase):
    """The response cache is a directory of files, written during the run and removed at
    its end. It exists so that every script reads the same bytes, and those bytes are the
    site's: a page that writes the credential into its own links is stored as it answered,
    for the life of the run, and is not this requirement's to rewrite.

    What the run was *given* is another matter. The credential must not become part of a
    cache key, of the request the entry records, or of anything else the cache writes for
    a site that never said it — found by the executor of 0.136.0's first spec, which
    stopped on it. The origin here answers a page that does not mention the credential,
    so every hit in the cache directory is the run's doing."""

    def setUp(self):
        self.http = harness.safe_http()
        self.origin = _Origin({"/": (200, {}, html("A quiet page")),
                               "/moved": (301, {"Location": "/"}, "")}, protected=True)
        self.cache = tempfile.mkdtemp(prefix="seo-cred-cache-")
        self.env = mock.patch.dict(os.environ, {
            "SEO_ALLOW_PRIVATE": "1", "SEO_MAX_RPS": "0",
            self.http.CACHE_DIR_VAR: self.cache,
            "SEO_URL_CREDENTIALS": f"http://{USERINFO}@{self.origin.host}"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.origin.stop()
        shutil.rmtree(self.cache, ignore_errors=True)

    def stored(self) -> dict:
        found = {}
        for folder, _dirs, files in os.walk(self.cache):
            for name in files:
                path = os.path.join(folder, name)
                with open(path, "rb") as stream:
                    found[path] = stream.read().decode("utf-8", "replace")
        return found

    def test_the_request_was_authenticated_stored_and_answered_again_from_the_store(self):
        first = self.http.safe_get(self.origin.base + "/")
        self.assertEqual(first.status_code, 200)
        again = self.http.safe_get(self.origin.base + "/")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.text, first.text)
        self.assertEqual([path for path, _carried, _right in self.origin.seen
                          if path == "/"], ["/"], "the second read went out again")
        self.assertTrue(self.stored(), "nothing was stored, so the sweep below reads nothing")

    def test_nothing_in_the_cache_directory_carries_the_credential(self):
        self.assertEqual(self.http.safe_get(self.origin.base + "/").status_code, 200)
        self.assertEqual(self.http.safe_get(self.origin.base + "/moved").status_code, 200)
        self.assertEqual(self.http.safe_head(self.origin.base + "/").status_code, 200)
        stored = self.stored()
        self.assertTrue(stored)
        for path, content in stored.items():
            for what, needle in NEEDLES.items():
                with self.subTest(file=os.path.basename(path), needle=what):
                    self.assertNotIn(needle, path)
                    self.assertNotIn(needle, content)


class AStoppedCredentialedOriginLeavesNoRobotsAnswer(unittest.TestCase):
    def test_a_later_test_reusing_the_port_reads_its_own_robots(self):
        http = harness.safe_http()
        with harness.allow_loopback(), harness.own_rate_limit_dir():
            first = _Origin({"/robots.txt": (200, {}, "User-agent: *\nDisallow: /\n")},
                            protected=True)
            url = first.base.replace("://", f"://{USERINFO}@", 1) + "/page"
            try:
                self.assertFalse(http.robots_allows(url)[0])
                self.assertTrue(os.path.exists(http._robots_cache_path(url.rsplit("/", 1)[0])))
                port = first.port
            finally:
                first.stop()

            bind = socketserver.ThreadingTCPServer.server_bind

            def reuse_port(server):
                server.server_address = ("127.0.0.1", port)
                bind(server)

            with mock.patch.object(socketserver.ThreadingTCPServer, "server_bind", reuse_port):
                second = _Origin({"/robots.txt": (200, {}, "User-agent: *\nAllow: /\n")},
                                 protected=True)
            try:
                self.assertEqual(second.port, port)
                self.assertTrue(http.robots_allows(url)[0],
                                "the next test inherited the stopped origin's Disallow")
                self.assertEqual(second.seen, [("/robots.txt", True, True)])
            finally:
                second.stop()


class WhichRequestsCarryTheCredential(unittest.TestCase):
    """`safe_http.url_credentials(url)`: the pair for a request to the origin the operator
    typed, nothing for any other. The evidence scripts are separate processes, so the
    origin and the credential travel in the environment, as the response cache and
    `--allow-private` do."""

    @classmethod
    def setUpClass(cls):
        cls.http = harness.safe_http()

    def test_the_name_it_travels_under(self):
        self.assertEqual(self.http.URL_CREDENTIALS_VAR, "SEO_URL_CREDENTIALS")

    def asked(self, typed, url):
        with mock.patch.dict(os.environ, {self.http.URL_CREDENTIALS_VAR: typed}):
            return self.http.url_credentials(url)

    def test_the_origin_that_was_typed(self):
        typed = "https://u:p%40ss@host.example:8443"
        for url in ("https://host.example:8443/", "https://host.example:8443/a?b=c",
                    "https://HOST.example:8443/robots.txt"):
            with self.subTest(url=url):
                self.assertEqual(self.asked(typed, url), ("u", "p@ss"))

    def test_a_token_alone_is_a_user_with_an_empty_password(self):
        self.assertEqual(self.asked("https://tok3n@host.example", "https://host.example/"),
                         ("tok3n", ""))

    def test_no_other_origin(self):
        typed = "https://u:p@host.example:8443"
        for url in ("https://host.example/", "https://host.example:9443/",
                    "https://other.example:8443/", "https://sub.host.example:8443/",
                    "https://host.example.evil.example:8443/"):
            with self.subTest(url=url):
                self.assertIsNone(self.asked(typed, url))

    def test_an_upgrade_keeps_it_and_a_downgrade_does_not(self):
        """Typed as `http://`, redirected to `https://` on the same host: the same site,
        better carried. Typed as `https://` and asked over `http://` — which is what the
        HTTPS-redirect check does on purpose — would put on a plain wire a password the
        operator only ever gave to an encrypted one."""
        self.assertEqual(self.asked("http://u:p@host.example", "https://host.example/"),
                         ("u", "p"))
        self.assertIsNone(self.asked("https://u:p@host.example", "http://host.example/"))

    def test_a_url_with_its_own_userinfo_is_left_to_say_who_it_is(self):
        self.assertIsNone(self.asked("https://u:p@host.example",
                                     "https://someone:else@host.example/"))

    def test_nothing_typed_nothing_sent(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(self.http.URL_CREDENTIALS_VAR, None)
            self.assertIsNone(self.http.url_credentials("https://host.example/"))
        self.assertIsNone(self.asked("", "https://host.example/"))


class AScriptStartedByHandTakesTheHostAndNothingElse(unittest.TestCase):
    """Three scripts took the host out of a URL by cutting at a colon: the user name of
    `https://user:pw@host/`, and `[` of `http://[::1]:8080/`. One sent what it found to a
    registry's whois server and to the resolver; another carried the credential into the
    plain-http form of the address it then asked. Measured at 0.152.0, when a script
    started by hand was handed what was typed. From 0.163.0 it is not: its entrance splits
    the credential off as the runner's does (`EveryProgramStartedByHandGivesTheCredential
    ToItsSiteAlone`). These still hold the reading of the host itself, which no longer
    depends on the entrance to be right."""

    HOSTS = {"https://example.com/": "example.com",
             "https://example.com:8443/": "example.com",
             "https://user:pw@example.com/": "example.com",
             "https://tok3n@example.com:8443/": "example.com",
             "http://[::1]:8080/page": "::1",
             "https://[2001:db8::1]/": "2001:db8::1",
             "http://203.0.113.5:8080/": "203.0.113.5"}

    def asked_by_domain_safety(self, url: str) -> dict:
        import domain_safety_check as safety
        asked = {"whois": [], "resolver": []}

        def whois(argv, **_kwargs):
            asked["whois"].append(argv[1:])
            return mock.Mock(stdout="", returncode=0)

        def resolve(name):
            asked["resolver"].append(name)
            raise OSError("not asked")

        reachable = {"reachable": True, "status": 200, "response_ms": 1, "error": None}
        with mock.patch.dict(os.environ), \
                mock.patch.object(safety.subprocess, "run", whois), \
                mock.patch.object(safety.shutil, "which", lambda name: "whois"), \
                mock.patch.object(safety.socket, "gethostbyname", resolve), \
                mock.patch.object(safety, "check_uptime", lambda *a: reachable), \
                mock.patch.object(safety, "check_safe_browsing",
                                  lambda *a: {"checked": False}):
            # whois is not started at all in a loopback-only process; this test is
            # about what it would be asked, and the recorder above is what it reaches.
            os.environ.pop("SEO_LOOPBACK_ONLY", None)
            asked["domain"] = safety.check(url)["domain"]
        return asked

    def test_whois_and_the_resolver_are_asked_about_the_host(self):
        for url, host in self.HOSTS.items():
            with self.subTest(url=url):
                asked = self.asked_by_domain_safety(url)
                self.assertEqual(asked["domain"], host)
                self.assertEqual(asked["resolver"], [host])
                # An address has no registration of its own: the registry is not asked.
                named = not host[0].isdigit() and ":" not in host
                self.assertEqual(asked["whois"], [[host]] if named else [])

    def test_a_locale_is_looked_for_in_the_host(self):
        import hreflang_checker
        for url, where in (("https://example.de/", "ccTLD"),
                           ("https://de.example.com/", "subdomain"),
                           ("https://user:pw@example.de/", "ccTLD"),
                           ("https://de:pw@example.com/", ""),
                           ("https://user:pw@de.example.com:8443/", "subdomain"),
                           ("https://[2001:db8::de]/", "")):
            with self.subTest(url=url):
                self.assertEqual(hreflang_checker.locale_lives_in("de", url), where)

    def test_the_plain_http_form_carries_no_credential(self):
        """INP-7, *the credential is sent nowhere else*: typed for `https://`, it is not
        given to the same host over `http://`. `safe_http` asks a URL that carries
        userinfo of its own as written, so the form itself must not carry it."""
        import security_headers
        for url, plain in (("https://user:pw@example.com/a#f", "http://example.com/a"),
                           ("https://tok3n@example.com:8443/", "http://example.com:8443/"),
                           ("https://user:pw@[::1]:8443/", "http://[::1]:8443/")):
            with self.subTest(url=url):
                self.assertEqual(security_headers.http_form(url), plain)


# The parser of a program, read without running the program: `parse_args` answers with
# the parser's own description of what it takes and the program ends there.
SLOTS = r"""
import argparse, json, os, runpy, sys
program, answer = sys.argv[1], sys.argv[2]
FLAGS = (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction,
         argparse._CountAction, argparse._AppendConstAction, argparse._HelpAction,
         argparse._VersionAction)
def described(parser, *args, **kwargs):
    with open(answer, "w", encoding="utf-8") as f:
        json.dump([dict(options=action.option_strings, dest=action.dest,
                        takes_text=not isinstance(action, FLAGS) and not action.choices
                                   and getattr(action.type, "__name__", "str") == "str",
                        flag=isinstance(action, FLAGS[:5]),
                        required=(action.required if action.option_strings
                                  else action.nargs not in ("?", "*")))
                   for action in parser._actions], f)
    raise SystemExit(0)
argparse.ArgumentParser.parse_args = described
argparse.ArgumentParser.parse_known_args = described
sys.argv = [program]
sys.path.insert(0, os.path.dirname(program))
runpy.run_path(program, run_name="__main__")
"""

# The control: the same program, the same argv, the same observer, and the entrance
# taken out. It is started through `runpy` because that is the one place it can be
# taken out from outside the program.
WITHOUT_ENTRANCE = r"""
import os, runpy, sys
program = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(program))
from lib import typed_credential
typed_credential.credentials_beside_argv = lambda argv=None: None
runpy.run_path(program, run_name="__main__")
"""

CAPTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_capture")
# Loaded by path and under another name: as `sitecustomize` it is what a child loads.
_spec = importlib.util.spec_from_file_location("hand_capture",
                                               os.path.join(CAPTURE, "sitecustomize.py"))
hand_capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hand_capture)


class EveryProgramStartedByHandGivesTheCredentialToItsSiteAlone(unittest.TestCase):
    """INP-7, *a script started by hand*. Under the runner a script is handed the URL
    without its credential and the credential beside it, and `url_credentials` gives it
    to the site alone. Started by hand, every program was handed what was typed, and
    measured on 11 October 2026 at 0.162.0 (`local/urlhand/`) four gave it to somebody
    else's server: PageSpeed, Safe Browsing, the W3C validator and IndexNow — and a token
    alone never reached the site, because Requests reads no credential out of
    `tok@host`.

    Every program with a `__main__` guard in `scripts/` is started here as an operator
    starts it, `python <program> <arguments>`, with a credentialed URL in its required
    arguments and then in each argument that takes text, one at a time; an argument
    whose name says it is a file gets a file holding the URL. Nothing names a program:
    one added tomorrow is in the set the day it is added. `tests/hand_capture/` sees
    every request the program makes and answers it on this machine. It cannot run under
    `SEO_LOOPBACK_ONLY`, which would refuse the other origins before a request was
    built — a request never attempted is not a request made clean — so the capture is
    the fence instead, and a child that gets past it ends with its exit code.
    """

    USER, PASSWORD = "handuser5k", "Hp-9wQ%2Fz"   # `%2F`: the password is `Hp-9wQ/z`
    TOKEN = "H4ndTok3nOnly"
    SITE = "https://staging.example"
    maxDiff = None

    @classmethod
    def forms(cls, userinfo: str) -> tuple[str, ...]:
        user, _, password = userinfo.partition(":")
        basic = base64.b64encode(f"{unquote(user)}:{unquote(password)}".encode()).decode()
        return tuple(f for f in {user, password, unquote(password), userinfo, basic} if f)

    @staticmethod
    def found(text: str, forms) -> list[str]:
        # Percent-encoded once or twice is the same secret: a URL put in a query is.
        # Lowercased too: Google's autocomplete lowercases what it is asked.
        readings = [r.lower() for r in (text, unquote(text), unquote(unquote(text)))]
        return sorted({f for f in forms for reading in readings if f.lower() in reading})

    @staticmethod
    def programs() -> list[str]:
        found = []
        for entry in sorted(os.listdir(SCRIPTS)):
            if not entry.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS, entry), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            if any(isinstance(node, ast.If) and "__name__" in ast.unparse(node.test)
                   for node in tree.body):
                found.append(entry)
        return found

    @classmethod
    def slots(cls, program: str) -> list[dict]:
        answer = os.path.join(cls.folder, program + ".slots.json")
        env = dict(harness.offline_env(), HOME=cls.folder, USERPROFILE=cls.folder)
        subprocess.run([sys.executable, "-c", SLOTS, os.path.join(SCRIPTS, program), answer],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, close_fds=False, timeout=180,
                       env=dict(env, PYTHONIOENCODING="utf-8"))
        if not os.path.exists(answer):
            return []
        with open(answer, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def argvs(slots: list[dict], url: str, url_file: str) -> list[list[str]]:
        """The required arguments with the URL, then each argument that takes text."""
        base = []
        for slot in slots:
            if slot["required"] and slot["takes_text"]:
                base += [url] if not slot["options"] else [slot["options"][0], url]
        runs = [base]
        for slot in slots:
            if slot["required"] or not slot["takes_text"]:
                continue
            value = url_file if "file" in slot["dest"] else url
            runs.append(base + slot["options"][:1] + [value])
        return runs

    @classmethod
    def started(cls, job) -> dict:
        program, argv, userinfo, control, required, *files = job
        work = tempfile.mkdtemp(prefix="run-", dir=cls.folder)
        for name, text in (files[0] if files else {}).items():   # files the start reads
            with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                f.write(text)
        log = tempfile.mkdtemp(prefix="capture-", dir=cls.folder)
        user, _, password = userinfo.partition(":")
        basic = base64.b64encode(f"{unquote(user)}:{unquote(password)}".encode()).decode()
        env = dict(harness.offline_env(), PYTHONPATH=CAPTURE, PYTHONDONTWRITEBYTECODE="1",
                   HOME=work, USERPROFILE=work,
                   PATH=cls.bin + os.pathsep + os.environ.get("PATH", ""),
                   SEO_CAPTURE_LOG=log, SEO_CAPTURE_SITE=cls.SITE,
                   SEO_CAPTURE_AUTH=f"Basic {basic}", SEO_CAPTURE_CWD=work,
                   SEO_CAPTURE_ROOT=os.path.join(harness.FIXTURES, "good"),
                   SEO_RATE_LIMIT_DIR=os.path.join(work, "rate"),
                   GOOGLE_API_KEY="k-google", PAGESPEED_API_KEY="k-psi",
                   GOOGLE_SAFE_BROWSING_KEY="k-sb", SAFE_BROWSING_API_KEY="k-sb",
                   GOOGLE_KG_API_KEY="k-kg", INDEXNOW_KEY="k-indexnow")
        for name in ("SEO_LOOPBACK_ONLY", "SEO_ALLOW_PRIVATE", "SEO_HTTP_CACHE",
                     "SEO_URL_CREDENTIALS"):
            env.pop(name, None)
        path = os.path.join(SCRIPTS, program)
        command = ([sys.executable, "-c", control, path] if control
                   else [sys.executable, path])
        try:
            done = subprocess.run(command + argv, stdin=subprocess.DEVNULL,
                                  capture_output=True, close_fds=False, timeout=300,
                                  encoding="utf-8", errors="replace",
                                  env=dict(env, PYTHONIOENCODING="utf-8"))
            code, printed = done.returncode, done.stdout + done.stderr
        except subprocess.TimeoutExpired as e:
            code, printed = "timeout", f"{e.stdout or ''}{e.stderr or ''}"
        # A program that ended has waited for what it started: both that start one
        # (`domain_safety_check`, the runner) wait in `subprocess.run`. One killed
        # at the timeout may leave its children writing, so its log is not read.
        requests_seen, unfinished = ([], ["timed out"]) if code == "timeout" \
            else hand_capture.read(log)
        written = []
        for folder, dirs, files in os.walk(work):
            for name in dirs + files:
                where = os.path.join(folder, name)
                written.append(os.path.relpath(where, work))
                if name in files:
                    with open(where, encoding="utf-8", errors="replace") as f:
                        written.append(f.read())
        results = os.path.join(work, "checklist-results.json")
        if os.path.isfile(results):          # the runner's record
            with open(results, encoding="utf-8") as f:
                results = json.load(f)
        return dict(program=program, argv=argv, userinfo=userinfo, exit=code,
                    requests=requests_seen, unfinished=unfinished, printed=printed, written="\n".join(written),
                    carried=code != "timeout" and hand_capture.carried(log),
                    required=required, record=results if isinstance(results, dict) else None)

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="seo-urlhand-")
        cls.addClassCleanup(shutil.rmtree, cls.folder, ignore_errors=True)
        # `whois` is a program the capture cannot see into; this one writes down what
        # it was asked, and is found on `PATH` before any real one.
        cls.bin = os.path.join(cls.folder, "bin")
        os.makedirs(cls.bin)
        recorder = os.path.join(cls.bin, "whois_recorder.py")
        with open(recorder, "w", encoding="utf-8") as f:
            # The capture is this process's `sitecustomize` too: its own file.
            f.write("import sys, sitecustomize\n"
                    "sitecustomize.record('whois', origin='whois',"
                    " target=' '.join(sys.argv[1:]))\n")
        if os.name == "nt":
            with open(os.path.join(cls.bin, "whois.cmd"), "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "{recorder}" %*\n')
        else:
            whois = os.path.join(cls.bin, "whois")
            with open(whois, "w", encoding="utf-8") as f:
                f.write(f"#!{sys.executable}\nimport runpy\n"
                        f"runpy.run_path({recorder!r}, run_name='__main__')\n")
            os.chmod(whois, 0o755)
        cls.every = cls.programs()
        with ThreadPoolExecutor(max_workers=8) as pool:
            cls.slots_of = dict(zip(cls.every, pool.map(cls.slots, cls.every), strict=True))
        jobs, controls = cls.jobs()
        with ThreadPoolExecutor(max_workers=8) as pool:
            cls.runs = list(pool.map(cls.started, jobs))
            cls.controls = list(pool.map(cls.started, controls))

    @classmethod
    def url_file(cls, url: str) -> str:
        path = tempfile.mkstemp(prefix="urls-", suffix=".txt", dir=cls.folder)
        os.close(path[0])
        with open(path[1], "w", encoding="utf-8") as f:
            f.write(url + "\n")
        return path[1]

    @classmethod
    def jobs(cls) -> tuple[list, list]:
        """`(program, argv, userinfo, control, required)` for every start, and the
        controls: `control` is the code the program is started through, or False."""
        jobs, controls = [], []
        for userinfo in (f"{cls.USER}:{cls.PASSWORD}", cls.TOKEN):
            url = f"https://{userinfo}@staging.example/"
            url_file = cls.url_file(url)
            for program in cls.every:
                # Which argument a URL arrives in is asked with the pair; the token,
                # and the control, as the URL to work on — where it is typed.
                required, *optional = cls.argvs(cls.slots_of[program], url, url_file)
                jobs.append((program, required, userinfo, False, True))
                if userinfo == cls.TOKEN:
                    continue
                controls.append((program, required, userinfo, WITHOUT_ENTRANCE, True))
                jobs += [(program, argv, userinfo, False, False) for argv in optional]
        return jobs, controls

    def to_the_site(self, request) -> bool:
        """The site is the scheme, host and port that were typed. `http://` of the same
        host is not it: a URL typed as `https://` keeps its credential off plain http."""
        return (request["kind"] == "http" and request["scheme"] == "https"
                and request["origin"] == "staging.example")

    def leaks(self, runs) -> list[str]:
        said = []
        for run in runs:
            forms = self.forms(run["userinfo"])
            for request in run["requests"]:
                if self.to_the_site(request):
                    continue
                text = " ".join((request.get("origin", ""), request.get("target", ""),
                                 json.dumps(request.get("headers", {})),
                                 request.get("body", "")))
                if self.found(text, forms):
                    said.append(f"{run['program']} {' '.join(run['argv'])} -> "
                                f"{request['kind']} {request.get('origin')}")
        return sorted(set(said))

    def test_the_whole_set_was_started_and_nothing_got_past_the_capture(self):
        self.assertGreater(len(self.every), 50, "the scan found almost no program")
        escaped = [f"{run['program']} {run['argv']}" for run in self.runs + self.controls
                   if run["exit"] == 97
                   or any(r["kind"] == "escaped" for r in run["requests"])]
        self.assertEqual(escaped, [])
        unfinished = [f"{run['program']} {run['argv']}: {run['unfinished']}"
                      for run in self.runs + self.controls if run["unfinished"]]
        self.assertEqual(unfinished, [], "a log read before every process of its start "
                                         "had finished writing it")

    def test_no_request_to_another_origin_carries_the_credential(self):
        self.assertEqual(self.leaks(self.runs), [],
                         "call `credentials_beside_argv()` first under "
                         '`if __name__ == "__main__":`, after `utf8_streams()`')

    def test_the_site_is_given_it_on_every_request(self):
        asked, refused = set(), []
        for run in self.runs:
            user, _, password = run["userinfo"].partition(":")
            basic = base64.b64encode(f"{unquote(user)}:{unquote(password)}".encode()).decode()
            for request in run["requests"]:
                if self.to_the_site(request):
                    asked.add(run["program"])
                    if request["headers"].get("authorization") != f"Basic {basic}":
                        refused.append(f"{run['program']} {' '.join(run['argv'])} -> "
                                       f"{request['target']}")
        self.assertGreater(len(asked), 30, "almost no program asked the site at all")
        self.assertEqual(sorted(set(refused)), [])

    def test_nothing_it_prints_or_writes_carries_the_credential(self):
        """Not part of the requirement, which is about requests, and held because the
        entrance makes it so at no cost: handed the URL to work on, a program never
        holds the credential in anything it was handed. Only that URL: the runner,
        which splits its own, echoes a URL typed where it takes a path or a category
        (`--history-dir`, `--only`), and that is named in INP-7 as not held."""
        said = [f"{run['program']} {' '.join(run['argv'])}: {where}"
                for run in self.runs if run["required"]
                for where in ("printed", "written")
                if self.found(run[where], self.forms(run["userinfo"]))]
        self.assertEqual(said, [])

    def test_the_control_sees_the_credential_leave_without_the_entrance(self):
        """Without this the tests above could pass because the observer is blind."""
        self.assertNotEqual(self.leaks(self.controls), [])


# The control of the class below: the same program, and the recognition of a URL typed
# without a scheme taken out, so that the entrances are what they were at 0.163.0.
WITHOUT_SCHEMELESS = r"""
import os, runpy, sys
program = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(program))
from lib import typed_credential
typed_credential.schemeless = lambda typed: None
runpy.run_path(program, run_name="__main__")
"""

# The control of the bare-token starts below: `tok@host` is still read as a URL where
# the program reads it — the credential is split off and goes beside it — but what
# the program is handed back is what was typed, as at 0.164.0, where the reading came
# after the program had shown it.
WITHOUT_REPAIR = r"""
import os, runpy, sys
program = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(program))
from lib import typed_credential
read = typed_credential.read_as_url
def read_and_dropped(typed, scheme="https"):
    read(typed, scheme)
    return typed
def scheme_added(url, scheme="https"):
    return read(url, scheme) if url in typed_credential._maybe_text else f"{scheme}://{url}"
typed_credential.read_as_url = read_and_dropped
typed_credential.scheme_added = scheme_added
runpy.run_path(program, run_name="__main__")
"""


class EveryProgramStartedByHandGivesASchemelessCredentialToItsSiteAlone(
        EveryProgramStartedByHandGivesTheCredentialToItsSiteAlone):
    """INP-7, *a URL typed without a scheme*. The class above, with the credential typed
    as an operator often types an address: `user:password@host/`, `tok@host/`, and
    `tok@host` with nothing after the host. Measured on 14 October 2026 at 0.163.0
    (`local/schemeless/`), neither entrance split them: `pagespeed.py`,
    `domain_safety_check.py`, `html_validator.py` and `indexnow_checker.py --ping` gave
    them to Google, Safe Browsing, the W3C and Bing; the runner gave the pair to Safe
    Browsing and wrote both forms into its results and its history; and the site was
    never given either, because a scheme was put in front of the URL after the entrance.

    Every test of the class above runs again on these starts. `me@example.com` is the
    counter-case: typed where text is asked for, it is an e-mail address, and it stays
    one — it is sent as the text it is and sets no credential.

    `tok@host` is started once more in each argument that takes text, one at a time,
    and once with each flag after the first of those. Measured on 15 October 2026 at
    0.164.0 (`local/printtok/`), where a program read it as a URL it went on showing
    what was typed: in a heading, a JSON field, the `source` of a result — and some
    went on using it, so that `internal_links.py` named no domain and
    `robots_path_tester.py --discover-assets` tested paths without their site. Where it
    was typed into an argument that takes a file or text, it is a file name or text.
    Which of the two a start was is read off the process: one that read it as a URL
    ends carrying the credential, and one that did not, does not.
    """

    EMAIL = "me@example.com"
    # A saved page, with nothing in it that a program would go and fetch.
    PAGE = ("<!doctype html><html lang=en><head><title>A saved page</title></head>"
            "<body><h1>A saved page</h1><p>Words on a page saved to disk.</p></body></html>")

    @classmethod
    def jobs(cls) -> tuple[list, list]:
        jobs, controls = [], []
        pair = f"{cls.USER}:{cls.PASSWORD}"
        url = f"{pair}@staging.example/"
        url_file = cls.url_file(url)
        for program in cls.every:
            slots = cls.slots_of[program]
            required, *optional = cls.argvs(slots, url, url_file)
            jobs.append((program, required, pair, False, True))
            jobs += [(program, argv, pair, False, False) for argv in optional]
            controls.append((program, required, pair, WITHOUT_SCHEMELESS, True))
            # `tok@host/` is split at the entrance, and nothing the program prints or
            # writes holds it. `tok@host` here is typed into every required argument,
            # `indexnow_checker.py --key` among them, where it is text and is printed as
            # typed; what a program shows of it is read below, one argument at a time.
            for typed, whole in ((f"{cls.TOKEN}@staging.example/", True),
                                 (f"{cls.TOKEN}@staging.example", False)):
                jobs.append((program, cls.argvs(slots, typed, url_file)[0], cls.TOKEN,
                             False, whole))
        cls.texts = []
        for program in cls.every:
            slots = cls.slots_of[program]
            base = cls.argvs(slots, f"{cls.SITE}/", "")[0]
            cls.texts += [(program, base + slot["options"][:1] + [cls.EMAIL], "", False, False)
                          for slot in slots if not slot["required"] and slot["takes_text"]
                          and "file" not in slot["dest"]]
        cls.bare, cls.bare_controls, cls.saved = [], [], []
        typed = f"{cls.TOKEN}@staging.example"
        for program in cls.every:
            slots = cls.slots_of[program]
            texts = [slot for slot in slots if slot["takes_text"]]
            starts = [cls.typed_in(slots, slot, typed) for slot in texts]
            if starts:
                starts += [starts[0] + slot["options"][:1] for slot in slots
                           if slot["flag"] and slot["options"]]
                cls.bare_controls.append((program, starts[0], cls.TOKEN, WITHOUT_REPAIR, False))
            cls.bare += [(program, argv, cls.TOKEN, False, False) for argv in starts]
            # The first argument that takes text, naming a saved page that is there:
            # once as `saved.html`, and once named `tok@host`.
            cls.saved += [(program, cls.typed_in(slots, texts[0], name), cls.TOKEN, False,
                           False, {name: cls.PAGE}) for name in ("saved.html", typed)
                          if texts]
        return jobs, controls

    @classmethod
    def typed_in(cls, slots: list[dict], slot: dict, typed: str,
                 given: tuple[list[dict], str] | None = None) -> list[str]:
        """`typed` in `slot`, and the site, with no credential, in every other required
        argument that takes text: so what the start shows of `typed` is that slot's.
        `given`, arguments and a value, puts that value in each of them instead."""
        argv = []
        for other in slots:
            if given and any(other is one for one in given[0]):
                value = given[1]
            elif other is slot or (other["required"] and other["takes_text"]):
                value = typed if other is slot else f"{cls.SITE}/"
            else:
                continue
            argv += [value] if not other["options"] else [other["options"][0], value]
        return argv

    @classmethod
    def inputs(cls) -> dict[str, str]:
        """What programs read from a file, one of each: nothing at all, a crawl
        inventory of another site, a saved page that links to its own site, an access
        log, the sheet of a links export that names pages on the site. Each reaches a
        path an empty name or a missing file does not, and some of those show the URL
        a program was given."""
        import site_crawl
        return {
            "empty.txt": "",
            "inventory.json": json.dumps({"inventory_version": site_crawl.INVENTORY_VERSION,
                                          "site": "https://elsewhere.example/",
                                          "pages": {}, "summary": {}}),
            "page.html": cls.PAGE.replace("<p>", '<a href="/about">About</a><p>'),
            "access.log": '203.0.113.9 - - [14/Oct/2026:10:00:00 +0000] "GET / HTTP/1.1" '
                          '200 512 "-" "Mozilla/5.0"\n',
            # Search Console's links export names its sheets; this is the one of the
            # pages linked to, which a program checks on the site it was given.
            "linked-pages.csv": "Top linked pages,Incoming links\n"
                                "https://staging.example/,3\nhttps://staging.example/about,1\n",
        }

    @classmethod
    def with_files(cls) -> list:
        """`tok@host` in an argument, and the other arguments that take text given a
        file in the run directory: an argument that reads a file reads it, one that
        writes a file writes over it, and `written` reads what is there after.

        For each argument a program read `tok@host` in as a URL, each other argument
        is given each input, one at a time. And for every argument that takes text,
        read or not, all the others are given one input at once: a program may read
        what was typed only after it has read a file it was given — a log, an export,
        a page — so which arguments it reads as a URL cannot be told from the start
        without one. Each start once as it is and once with every flag the program
        has, `--json` among them: a program that shows what it was given on such a path
        may show it only in its JSON."""
        typed = f"{cls.TOKEN}@staging.example"
        read = {(run["program"], tuple(run["argv"])) for run in cls.bare_runs if run["carried"]}
        jobs, seen = [], set()
        for program in cls.every:
            slots = cls.slots_of[program]
            texts = [slot for slot in slots if slot["takes_text"]]
            flags = [slot["options"][0] for slot in slots if slot["flag"] and slot["options"]]
            for slot in texts:
                others = [other for other in texts if other is not slot]
                if not others:
                    continue
                groups = [others]
                if (program, tuple(cls.typed_in(slots, slot, typed))) in read:
                    groups += [[other] for other in others]
                for group in groups:
                    for name, text in cls.inputs().items():
                        for with_flags in ([], flags):
                            argv = cls.typed_in(slots, slot, typed, (group, name)) + with_flags
                            if (program, tuple(argv)) not in seen:
                                seen.add((program, tuple(argv)))
                                jobs.append((program, argv, cls.TOKEN, False, False,
                                             {name: text}))
        return jobs

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with ThreadPoolExecutor(max_workers=8) as pool:
            cls.text_runs = list(pool.map(cls.started, cls.texts))
            cls.bare_runs = list(pool.map(cls.started, cls.bare))
            cls.bare_controls = list(pool.map(cls.started, cls.bare_controls))
            cls.saved_runs = list(pool.map(cls.started, cls.saved))
            cls.file_runs = list(pool.map(cls.started, cls.with_files()))
        cls.bare_runs += cls.file_runs

    def test_the_runner_records_that_a_credential_was_used(self):
        """The record says so and names the site by host, as it does for a URL typed
        with its scheme; at 0.163.0 it said no credential was used, and named the pair's
        site `unknown`."""
        records = [(run["argv"][0], run["record"] and {
                        key: run["record"].get(key) for key in ("url", "domain", "url_credentials")})
                   for run in self.runs if run["program"] == "checklist_runner.py"
                   and len(run["argv"]) == 1]
        self.assertEqual(len(records), 3)
        for typed, record in records:
            with self.subTest(typed=typed):
                self.assertEqual(record, {"url": "https://" + typed.rpartition("@")[2],
                                          "domain": "staging.example", "url_credentials": True})

    def test_an_email_address_typed_as_text_stays_text(self):
        """Typed where text is asked for, it goes out as the text it was, and the run
        that sent it so presents no credential anywhere. Typed where a URL is asked for
        (`urls`, `--site`, `--fetch`), it is the URL of `example.com` with `me` as a
        token, and that token is presented to `example.com` and to nobody else."""
        self.assertGreater(len(self.text_runs), 50)
        self.assertEqual([f"{run['program']} {run['argv']}" for run in self.text_runs
                          if run["exit"] == 97 or run["unfinished"]], [])

        def sent_as_text(run):
            return {request["origin"] for request in run["requests"]
                    if self.EMAIL in unquote(request.get("target", ""))
                    or self.EMAIL in request.get("body", "")}

        def presented(run):
            return {request["origin"] for request in run["requests"]
                    if request.get("headers", {}).get("authorization")}

        as_text = set().union(*map(sent_as_text, self.text_runs))
        self.assertTrue({"www.wikidata.org", "suggestqueries.google.com"} <= as_text, as_text)
        said = sorted(f"{run['program']} {' '.join(run['argv'])} -> {sorted(presented(run))}"
                      for run in self.text_runs if sent_as_text(run) and presented(run))
        self.assertEqual(said, [])
        token = "Basic " + base64.b64encode(b"me:").decode()
        elsewhere = sorted({f"{run['program']} {' '.join(run['argv'])} -> {request.get('origin')}"
                            for run in self.text_runs for request in run["requests"]
                            if request.get("headers", {}).get("authorization")
                            and (request.get("origin") != "example.com"
                                 or request["headers"]["authorization"] != token)})
        self.assertEqual(elsewhere, [])
        as_userinfo = sorted({f"{run['program']} {' '.join(run['argv'])} -> {request.get('origin')}"
                              for run in self.text_runs for request in run["requests"]
                              if request.get("origin") != "example.com"
                              and "://me@" in unquote(unquote(request.get("target", "")
                                                              + request.get("body", "")))})
        self.assertEqual(as_userinfo, [])

    def test_a_token_typed_alone_and_read_as_a_url_is_shown_as_the_url_read(self):
        """Where the program reads `tok@host` as a URL, nothing it prints or writes
        carries the token, nobody else is given it, and what it shows is the URL it
        read, `https://host`, as it shows `https://tok@host` typed with its scheme."""
        self.assertEqual([f"{run['program']} {run['argv']}"
                          for run in self.bare_runs + self.bare_controls
                          if run["exit"] in (97, "timeout") or run["unfinished"]], [])
        read = [run for run in self.bare_runs if run["carried"]]
        self.assertGreater(len({run["program"] for run in read}), 40)
        forms = self.forms(self.TOKEN)
        said = sorted({f"{run['program']} {' '.join(run['argv'])}: {where}"
                       for run in read for where in ("printed", "written")
                       if self.found(run[where], forms)})
        self.assertEqual(said, [], "read what was typed once, after `parse_args`: "
                                   "`read_as_url`, or `seo_common.read_source`")
        self.assertEqual(self.leaks(read), [])
        shown = {run["program"] for run in read if self.SITE in run["printed"]}
        self.assertGreater(len(shown), 20)

    def test_a_token_typed_where_a_file_or_text_is_asked_for_is_shown_as_typed(self):
        """The counter-case. Typed where a file is asked for, `tok@host` is a file
        name, and a program that cannot find it says so with the name as typed;
        typed where text is asked for, it is that text. Neither sets a credential."""
        typed = f"{self.TOKEN}@staging.example".lower()
        unread = [run for run in self.bare_runs if not run["carried"]
                  and self.found(run["printed"] + run["written"], self.forms(self.TOKEN))]
        self.assertGreater(len({run["program"] for run in unread}), 5)
        self.assertEqual(sorted({f"{run['program']} {' '.join(run['argv'])}" for run in unread
                                 if typed not in (run["printed"] + run["written"]).lower()}), [])
        self.assertEqual(sorted({f"{run['program']} {' '.join(run['argv'])} -> {r.get('origin')}"
                                 for run in unread for r in run["requests"]
                                 if r.get("headers", {}).get("authorization")}), [])

    def test_a_saved_page_named_like_an_address_is_read_as_the_page_it_is(self):
        """A file on disk wins over any spelling (`seo_common.is_url`), and
        `read_source` reads a source as a URL only where `is_url` says so. The programs
        that both fetch a URL and read a page saved to disk in their first argument —
        handed `tok@host` they ask the site, handed an existing `saved.html` they ask
        nobody — handed an existing page named `tok@host` read it: they ask nobody,
        end carrying no credential, and show the name as typed where they show it.
        Measured on 15 October 2026 at 0.165.0's first build, eight of them took the
        name on for the page's address and ended carrying `tok` as the credential of
        `host`; a name read as a file is a file name from there on
        (`typed_credential.read_as_file`)."""
        typed = f"{self.TOKEN}@staging.example"
        self.assertEqual([f"{run['program']} {run['argv']}" for run in self.saved_runs
                          if run["exit"] in (97, "timeout") or run["unfinished"]], [])
        fetches = {run["program"] for run in self.bare_runs
                   if run["argv"] == self.typed_in(self.slots_of[run["program"]],
                                                   self.first_text(run["program"]), typed)
                   and any(self.to_the_site(request) for request in run["requests"])}
        saved = {(run["program"], "saved.html" if "saved.html" in run["argv"] else typed): run
                 for run in self.saved_runs}
        reads_pages = sorted(program for program in fetches
                             if saved[(program, "saved.html")]["exit"] == 0
                             and not saved[(program, "saved.html")]["requests"])
        self.assertGreater(len(reads_pages), 10)
        said = []
        for program in reads_pages:
            run = saved[(program, typed)]
            shown = run["printed"] + run["written"]
            if (run["exit"] != 0 or run["requests"] or run["carried"]
                    or (self.found(shown, self.forms(self.TOKEN))
                        and typed.lower() not in shown.lower())):
                said.append(f"{program} {' '.join(run['argv'])}: exit {run['exit']}, "
                            f"asked {sorted({r.get('origin') for r in run['requests']})}, "
                            f"carried {run['carried']}")
        self.assertEqual(said, [])

    def first_text(self, program: str) -> dict:
        return next(slot for slot in self.slots_of[program] if slot["takes_text"])

    def test_the_control_sees_the_token_shown_as_typed_without_the_repair(self):
        """Without this the first test above could pass because the observer is blind."""
        self.assertNotEqual([run["program"] for run in self.bare_controls if run["carried"]
                             and self.found(run["printed"] + run["written"],
                                            self.forms(self.TOKEN))], [])

    def test_the_control_sees_the_credential_leave_without_the_entrance(self):
        """Without the recognition the credential leaves as it did at 0.163.0, and the
        program started is never seen giving it to the site: the observer is not blind,
        and the repair is what moved. A child the runner starts is a program of its own,
        with its own entrance, and the control does not reach into it."""
        self.assertNotEqual(self.leaks(self.controls), [])
        self.assertEqual([f"{run['program']} -> {request['target']}" for run in self.controls
                          for request in run["requests"]
                          if request["program"] == run["program"] and self.to_the_site(request)
                          and request["headers"].get("authorization")], [])


class TwoArgumentsTheSweepCannotTellFromText(unittest.TestCase):
    """INP-7, *a script started by hand*, for two arguments named here on purpose.

    `server_log_audit.py --url` is the site a log belongs to, and `parse_html.py --url`
    the base a saved page's links are resolved against. Neither program asks anything of
    that URL: at 0.164.0 the first wrote it into its JSON as `base_url`, the second handed
    it to `urljoin`, and nothing read it as a URL, so `tok@host` typed there was shown, or
    used, as typed. Each now reads it once after `parse_args`, as every program does an
    argument it reads as a URL. The derived sweep above cannot see either: it tells an
    argument read as a URL from text by the credential the process ends carrying, and
    with the read taken out nothing reads these as a URL, so the start looks like one of
    text — measured on the PC on 15 October 2026, taking either read out left every test
    of that sweep green (`local/printtok/pc/round3/`). Do not fold these into it.
    """

    SWEEP = EveryProgramStartedByHandGivesASchemelessCredentialToItsSiteAlone
    TOKEN, SITE = SWEEP.TOKEN, SWEEP.SITE
    started = classmethod(SWEEP.started.__func__)

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="seo-urlhand-")
        cls.addClassCleanup(shutil.rmtree, cls.folder, ignore_errors=True)
        cls.bin = os.path.join(cls.folder, "bin")
        os.makedirs(cls.bin)
        typed, inputs = f"{cls.TOKEN}@staging.example", cls.SWEEP.inputs()
        cls.log = cls.started(("server_log_audit.py", ["access.log", "--url", typed, "--json"],
                               cls.TOKEN, False, False, {"access.log": inputs["access.log"]}))
        cls.page = cls.started(("parse_html.py", ["page.html", "--url", typed, "--json"],
                                cls.TOKEN, False, False, {"page.html": inputs["page.html"]}))

    def shown_and_presented(self, run) -> tuple[list[str], list[str]]:
        self.assertEqual((run["exit"], run["unfinished"]), (0, []), run["printed"][-600:])
        shown = self.SWEEP.found(run["printed"] + run["written"], self.SWEEP.forms(self.TOKEN))
        presented = sorted({request.get("origin") for request in run["requests"]
                            if request.get("headers", {}).get("authorization")})
        return shown, presented

    def test_a_log_names_the_site_it_belongs_to_as_read(self):
        self.assertEqual(self.shown_and_presented(self.log), ([], []))
        self.assertIn(f'"base_url": "{self.SITE}"', self.log["printed"])

    def test_a_saved_page_resolves_its_links_against_the_url_as_read(self):
        self.assertEqual(self.shown_and_presented(self.page), ([], []))
        self.assertIn(f'"href": "{self.SITE}/about"', self.page["printed"])


HAMMER = r"""
import sys, threading, sitecustomize
who, lines = sys.argv[1], int(sys.argv[2])
def write(thread):
    for n in range(lines):
        sitecustomize.record("http", origin="x.example", target="/p?" + "a" * 700,
                             who=who, thread=thread, n=n)
threads = [threading.Thread(target=write, args=(t,)) for t in range(2)]
for t in threads: t.start()
for t in threads: t.join()
"""


class WhatTheCaptureWritesIsReadWholeAndOnce(unittest.TestCase):
    """The capture above is the observer: a line it loses is a request nobody saw. On
    Windows an append is not atomic, and eight processes appending to one file were
    measured on 11 October 2026 keeping 9120 of 12000 lines and tearing seven. So each
    process writes a file of its own and closes it with an `end` line, and the reader
    says which files are not whole. Counted, not timed: every line written is read
    back once, whatever the order the processes ran in."""

    PROCESSES, THREADS, LINES = 8, 2, 750

    def capture_env(self, log):
        return dict(harness.offline_env(), PYTHONPATH=CAPTURE, SEO_CAPTURE_LOG=log,
                    PYTHONDONTWRITEBYTECODE="1")

    def test_many_processes_writing_at_once_lose_and_tear_nothing(self):
        log = tempfile.mkdtemp(prefix="seo-capture-")
        self.addCleanup(shutil.rmtree, log, ignore_errors=True)
        env = self.capture_env(log)
        children = [subprocess.Popen([sys.executable, "-c", HAMMER, str(who), str(self.LINES)],
                                     env=env, stdin=subprocess.DEVNULL, close_fds=False)
                    for who in range(self.PROCESSES)]
        self.assertEqual([child.wait(timeout=300) for child in children],
                         [0] * self.PROCESSES)
        lines, unfinished = hand_capture.read(log)
        self.assertEqual(unfinished, [])
        self.assertEqual(len(os.listdir(log)), self.PROCESSES)
        seen = sorted((line["who"], line["thread"], line["n"]) for line in lines)
        self.assertEqual(seen, [(str(who), thread, n) for who in range(self.PROCESSES)
                                for thread in range(self.THREADS) for n in range(self.LINES)])
        self.assertTrue(all(line["target"] == "/p?" + "a" * 700 for line in lines))

    def test_a_process_that_did_not_finish_is_named_not_read_as_whole(self):
        log = tempfile.mkdtemp(prefix="seo-capture-")
        self.addCleanup(shutil.rmtree, log, ignore_errors=True)
        killed = ("import os, signal, sitecustomize\n"
                  "sitecustomize.record('http', origin='x.example')\n"
                  "os.kill(os.getpid(), signal.SIGTERM)\n")
        subprocess.run([sys.executable, "-c", killed], env=self.capture_env(log),
                       stdin=subprocess.DEVNULL, close_fds=False, timeout=60)
        with open(os.path.join(log, "torn.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"kind": "start"}\n{"kind": "http", "orig')
        lines, unfinished = hand_capture.read(log)
        self.assertEqual(len(unfinished), 2)
        self.assertIn("torn.jsonl", unfinished)


if __name__ == "__main__":
    unittest.main()
