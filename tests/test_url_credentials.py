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
import base64
import http.client
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
from unittest import mock

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
        for typed, clean, userinfo in self.CASES:
            with self.subTest(typed=typed):
                self.assertEqual(runner.split_userinfo(typed), (clean, userinfo))


class WhatIsAddedToTheSecretSet(unittest.TestCase):
    """The split takes the credential out of every URL the run builds. What the *site*
    hands back is another route — a link with the credential baked in, a page that echoes
    the request — and redaction is what stands there. The forms are the specific ones: the
    bare password is not among them, because a password of one letter would then be
    replaced in every word of the record."""

    def test_the_forms(self):
        self.assertEqual(set(runner.url_credential_secrets("u:p%40ss")),
                         {"u:p%40ss@", "u:p@ss@",
                          base64.b64encode(b"u:p@ss").decode()})

    def test_a_token_alone(self):
        self.assertEqual(set(runner.url_credential_secrets("tok3n")),
                         {"tok3n@", base64.b64encode(b"tok3n:").decode()})

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


if __name__ == "__main__":
    unittest.main()
