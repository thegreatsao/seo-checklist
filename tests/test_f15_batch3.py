"""F15 batch 3: the defects F03's second reading found in the crawl inventory readers —
`duplicate_content.py`, `canonical_checker.py`, `link_profile.py`, `internal_links.py`,
`topical_cluster_mapper.py`, `anchor_text_audit.py`, `server_log_audit.py` — and the
shared `site_crawl.page_key`, as the owner ruled them (docs/sprint-20261109-F15.md).

Each verdict is the item's real rule from the registry over the script's real output,
from a hand-built inventory or from a crawl of a site served on loopback. The
`measures` rows are held by `MeasuresSentences`.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import anchor_text_audit  # noqa: E402
import canonical_checker  # noqa: E402
import duplicate_content  # noqa: E402
import internal_links  # noqa: E402
import link_profile  # noqa: E402
import server_log_audit  # noqa: E402
import site_crawl  # noqa: E402
import topical_cluster_mapper  # noqa: E402
from harness import served  # noqa: E402
from test_evidence import verdict  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, WARN  # noqa: E402

ITEMS = {item["id"]: item for item in harness.registry()["items"]}
SITE = "https://example.test/"
ROBOTS = (200, "User-agent: *\nAllow: /\n")


def words(n: int, seed: str = "w") -> str:
    return " ".join(f"{seed}{i}" for i in range(n))


def row(url: str, *, title="A page", description=None, canonical=None, canonicals=None,
        noindex=False, text=None, links=(), status=200, final_url=None,
        anchors=None) -> dict:
    """One inventory row as `site_crawl._read_page` writes it; `text` is the page's own
    words (None: 400 distinct words), from which the hash, count and signature come."""
    text = words(400, url) if text is None else text
    if canonicals is None:
        canonicals = [canonical] if canonical else []
    anchors = anchors or {}
    return {
        "url": url, "final_url": final_url or url, "status": status, "html": True,
        "content_type": "text/html", "redirect_chain": [], "redirected": False,
        "error": None, "error_kind": None, "robots_blocked": False,
        "title": title, "meta_description": description or f"About {url}",
        "canonical": canonical, "canonicals": canonicals, "noindex": noindex,
        "content_words": site_crawl.word_count(text),
        "text_hash": site_crawl.exact_hash(text) if text.strip() else None,
        "signature": (site_crawl.minhash_signature(site_crawl.shingle(text))
                      if text.strip() else None),
        "links": [{"target": target, "internal": True,
                   "anchor": anchors.get(target, "Related reading"),
                   "rel": [], "nofollow": False} for target in links],
        "images": [], "schema_nodes": [], "lang": None,
    }


def inventory(rows: list, entry: str = SITE, truncated: bool = False,
              signatures: bool = True) -> dict:
    return {"inventory_version": site_crawl.INVENTORY_VERSION, "site": SITE,
            "entry": entry, "signatures": signatures,
            "pages": {site_crawl.page_key(r["url"]): r for r in rows},
            "summary": {"truncated": truncated}, "fetch_error": None,
            "redirected": [], "broken": []}


def duplicates(inv: dict) -> dict:
    return duplicate_content.detect_duplicates(
        duplicate_content.pages_from_inventory(inv),
        truncated=bool(inv["summary"].get("truncated")),
        signatures=inv.get("signatures", True))


def written(inv: dict) -> str:
    folder = tempfile.mkdtemp(prefix="f15-b3-")
    path = os.path.join(folder, "inventory.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(inv, handle)
    return path


def run_rule_script(module, item_id: str, url: str, inventory_path: str = "") -> dict:
    """The item's script run in-process with the registry's own arguments."""
    args = [a.replace("{url}", url).replace("{inventory_json}", inventory_path)
            for a in ITEMS[item_id]["check"]["args"]]
    saved = sys.argv
    sys.argv = [module.__file__] + args + ["--json"]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            module.main()
    finally:
        sys.argv = saved
    return json.loads(out.getvalue())


def crawled(routes: dict, **kw) -> tuple:
    """Crawl a loopback site; returns (inventory, site url)."""
    routes = dict(routes)
    routes.setdefault("/robots.txt", ROBOTS)
    with harness.allow_loopback(), served(routes) as site:
        inv = site_crawl.crawl(site.url, workers=1, **kw)
    return inv, site.url


# ---------------------------------------------------------------------------
# site_crawl.page_key — the shared starting point
# ---------------------------------------------------------------------------

class PageKey(unittest.TestCase):
    def test_a_page_number_keeps_its_own_key(self):
        """MS-022: `?page=N` is a page of its own, so its title is judged."""
        self.assertNotEqual(site_crawl.page_key("https://x.test/blog?page=2"),
                            site_crawl.page_key("https://x.test/blog"))
        self.assertNotEqual(site_crawl.page_key("https://x.test/blog?page=2"),
                            site_crawl.page_key("https://x.test/blog?page=3"))
        self.assertEqual(site_crawl.page_key("https://x.test/blog/?paged=2&utm_source=a"),
                         "https://x.test/blog?paged=2")

    def test_the_page_number_names_are_the_ones_kept(self):
        for name in site_crawl.PAGE_NUMBER_PARAMS:
            with self.subTest(name=name):
                self.assertEqual(site_crawl.page_key(f"https://x.test/b?{name}=3"),
                                 f"https://x.test/b?{name}=3")
        self.assertEqual(site_crawl.page_key("https://x.test/b?p=3"), "https://x.test/b")

    def test_other_queries_still_fold_into_the_page(self):
        self.assertEqual(site_crawl.page_key("https://x.test/blog?utm_source=news"),
                         "https://x.test/blog")
        self.assertEqual(site_crawl.page_key("https://x.test/blog?page=next"),
                         "https://x.test/blog")

    def test_percent_encoded_and_raw_paths_are_one_page(self):
        """The 2026-10-24 audit: `/café` and `/caf%C3%A9` were two pages."""
        keys = {site_crawl.page_key("https://x.test/caf%C3%A9"),
                site_crawl.page_key("https://x.test/caf%c3%a9/"),
                site_crawl.page_key("https://x.test/café")}
        self.assertEqual(len(keys), 1, keys)

    def test_the_server_log_agrees_on_one_page(self):
        """CI-018's set arithmetic compares the log's spelling with the crawl's."""
        self.assertEqual(server_log_audit._key("https://x.test/café/"),
                         server_log_audit._log_key("/caf%C3%A9"))
        self.assertEqual(server_log_audit._key("https://x.test/blog?page=2"),
                         server_log_audit._log_key("/blog?page=2&sort=asc"))
        self.assertNotEqual(server_log_audit._log_key("/blog?page=2"),
                            server_log_audit._log_key("/blog"))


# ---------------------------------------------------------------------------
# duplicate_content.py — MS-022, MS-026, MS-029, CN-039, CN-041
# ---------------------------------------------------------------------------

class TheTextHashGateIsGone(unittest.TestCase):
    """A page with no body text of its own is still a page with a title, a
    description and a word count of zero (MS-026, MS-029, CN-039)."""

    def test_an_untitled_page_with_no_text_fails_ms_026(self):
        out = duplicates(inventory([row(SITE), row(SITE + "gallery", title="", text="")]))
        self.assertEqual(verdict("MS-026", out), FAIL)
        self.assertIn("https://example.test/gallery", out["missing_titles"])

    def test_duplicate_descriptions_on_pages_with_no_text_fail_ms_029(self):
        out = duplicates(inventory([
            row(SITE),
            row(SITE + "a", text="", description="Same words"),
            row(SITE + "b", text="", description="Same words")]))
        self.assertNotEqual(verdict("MS-029", out), PASS)

    def test_a_zero_word_page_is_thin(self):
        out = duplicates(inventory([row(SITE), row(SITE + "empty", text="")]))
        self.assertEqual(out["summary"]["thin_pages"], 1)
        self.assertNotEqual(verdict("CN-039", out), PASS)

    def test_two_pages_without_text_are_not_duplicate_content(self):
        out = duplicates(inventory([row(SITE), row(SITE + "a", text=""),
                                    row(SITE + "b", text="")]))
        self.assertEqual(verdict("CN-041", out), PASS)


class DuplicateTitles(unittest.TestCase):
    def test_a_self_canonical_on_a_trailing_slash_site_is_judged(self):
        """The 2026-10-24 audit: the slash-stripped key against the canonical's own
        spelling read every page of a trailing-slash site as canonicalised away."""
        out = duplicates(inventory([
            row(SITE + "a/", title="Same", canonical=SITE + "a/"),
            row(SITE + "b/", title="Same", canonical=SITE + "b/")]))
        self.assertEqual(out["summary"]["title_group_exclusions"]["canonicalized"], 0)
        self.assertEqual(verdict("MS-022", out), FAIL)

    def test_a_page_canonicalised_elsewhere_is_left_out(self):
        out = duplicates(inventory([
            row(SITE + "a", title="Same"),
            row(SITE + "a-print", title="Same", canonical=SITE + "a")]))
        self.assertEqual(verdict("MS-022", out), PASS)

    def test_a_canonical_naming_another_query_is_not_self(self):
        out = duplicates(inventory([
            row(SITE + "p?id=1", title="Same", canonical=SITE + "p?id=2"),
            row(SITE + "q", title="Same")]))
        self.assertEqual(out["summary"]["title_group_exclusions"]["canonicalized"], 1)

    def test_paginated_pages_sharing_a_title_fail_ms_022(self):
        page = '<html><head><title>Blog</title></head><body>{}</body></html>'
        inv, url = crawled({
            "/": page.format('<a href="/blog?page=2">2</a> ' + words(300, "a")),
            "/blog?page=2": page.format(words(300, "b")),
        }, use_sitemap=False)
        self.assertIn(url + "blog?page=2", inv["pages"])
        self.assertEqual(verdict("MS-022", duplicates(inv)), FAIL)


class DuplicateContent(unittest.TestCase):
    def test_a_page_and_its_noindex_copy_pass_cn_041(self):
        text = words(300, "same")
        out = duplicates(inventory([row(SITE + "a", text=text),
                                    row(SITE + "a-copy", text=text, noindex=True)]))
        self.assertEqual(verdict("CN-041", out), PASS)

    def test_a_canonicalised_copy_passes_cn_041(self):
        text = words(300, "same")
        out = duplicates(inventory([row(SITE + "a", text=text),
                                    row(SITE + "a-copy", text=text, canonical=SITE + "a")]))
        self.assertEqual(verdict("CN-041", out), PASS)

    def test_two_indexable_copies_fail_cn_041(self):
        text = words(300, "same")
        out = duplicates(inventory([row(SITE + "a", text=text), row(SITE + "b", text=text)]))
        self.assertEqual(verdict("CN-041", out), FAIL)

    def test_near_duplicates_reach_the_assertion(self):
        base = words(300, "same")
        out = duplicates(inventory([row(SITE + "a", text=base),
                                    row(SITE + "b", text=base + " one more")]))
        self.assertEqual(out["summary"]["near_duplicate_pairs"], 1)
        self.assertEqual(verdict("CN-041", out), WARN)

    def test_a_near_duplicate_with_a_noindex_page_does_not_count(self):
        base = words(300, "same")
        out = duplicates(inventory([row(SITE + "a", text=base),
                                    row(SITE + "b", text=base + " more", noindex=True)]))
        self.assertEqual(verdict("CN-041", out), PASS)

    def test_no_signatures_withholds_the_pass(self):
        out = duplicates(inventory([row(SITE + "a"), row(SITE + "b")], signatures=False))
        self.assertEqual(verdict("CN-041", out), NO_DATA)


# ---------------------------------------------------------------------------
# canonical_checker.py — CI-009, CI-011, TE-176
# ---------------------------------------------------------------------------

def page_html(title="Page", canonical=None, robots=None, body=None) -> str:
    head = f"<title>{title}</title>"
    if canonical:
        head += f'<link rel="canonical" href="{canonical}">'
    if robots:
        head += f'<meta name="robots" content="{robots}">'
    return f"<html><head>{head}</head><body>{body or words(50)}</body></html>"


def served_rule(item_id: str, routes: dict, path: str = "/a") -> dict:
    routes = dict(routes)
    routes.setdefault("/robots.txt", ROBOTS)
    with harness.allow_loopback(), served(routes) as site:
        origin = site.url.rstrip("/")
        other = origin.replace("127.0.0.1", "localhost")
        resolved = {k: (v.replace("{origin}", origin).replace("{other}", other)
                        if isinstance(v, str) else v) for k, v in routes.items()}
        site.routes.clear()
        site.routes.update({k: harness._normalise(v) for k, v in resolved.items()})
        return run_rule_script(canonical_checker, item_id, site.url.rstrip("/") + path)


class CanonicalTargets(unittest.TestCase):
    def test_ci_009_and_ci_011_request_targets_and_variants(self):
        sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
        import build_checklist
        self.assertEqual(build_checklist.CANONICAL_ARGS,
                         ["{url}", "--check-targets", "--variants"])
        for item_id in ("CI-009", "CI-011"):
            with self.subTest(item=item_id):
                self.assertEqual(ITEMS[item_id]["check"]["args"],
                                 build_checklist.CANONICAL_ARGS)

    def test_a_canonical_to_a_404_fails_ci_009(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/gone")})
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_a_canonical_to_a_live_page_passes_ci_009(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/b"),
                                     "/b": page_html(canonical="/b")})
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_variant_serving_the_page_without_consolidation_fails_ci_009(self):
        """`/a/` answering 200 beside `/a` with no canonical: one page, two URLs."""
        out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                     "/a/": page_html()})
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_a_variant_that_redirects_or_declares_the_canonical_passes_ci_009(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                     "/a/": (301, {"Location": "/a"}, "")})
        self.assertEqual(verdict("CI-009", out), PASS)
        out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                     "/a/": page_html(canonical="{origin}/a")})
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_canonical_to_a_noindex_page_fails_ci_011(self):
        out = served_rule("CI-011", {"/a": page_html(canonical="/b"),
                                     "/b": page_html(canonical="/b", robots="noindex")})
        self.assertEqual(verdict("CI-011", out), FAIL)

    def test_a_cross_host_canonical_alone_passes_ci_011(self):
        out = served_rule("CI-011", {
            "/a": page_html(canonical="{other}/original"),
            "/original": page_html(canonical="{other}/original")})
        self.assertEqual(out["rows"][0]["verdict"], "cross_host")
        self.assertEqual(verdict("CI-011", out), PASS)


class InventoryCanonicals(unittest.TestCase):
    """TE-176: the crawl reads the canonical as `seo_common.declared_canonicals` does."""

    def test_the_crawl_reads_a_link_header_canonical(self):
        inv, url = crawled({"/": (200, {"Link": '</>; rel="canonical"'},
                                  "<html><body>Home</body></html>")}, use_sitemap=False)
        self.assertEqual(inv["pages"][url]["canonical"], url)

    def test_the_crawl_keeps_every_canonical_and_te_176_fails_a_conflict(self):
        html = ('<html><head><link rel="canonical" href="/"><link rel="canonical" '
                'href="/other"></head><body>Home</body></html>')
        inv, url = crawled({"/": html, "/other": page_html(canonical="/other")},
                           use_sitemap=False)
        self.assertEqual(len(inv["pages"][url]["canonicals"]), 2)
        out = canonical_checker.check_inventory(url, written(inv))
        verdicts = {r["url"]: r["verdict"] for r in out["rows"]}
        self.assertEqual(verdicts[url], "conflicting")
        self.assertEqual(verdict("TE-176", out), FAIL)

    def test_a_canonical_to_another_query_is_not_self(self):
        """Aside: the target was matched by the query-dropping page key."""
        inv = inventory([row(SITE, canonical=SITE + "?id=2")])
        out = canonical_checker.check_inventory(SITE, written(inv))
        self.assertEqual(out["rows"][0]["verdict"], "canonicalized")


# ---------------------------------------------------------------------------
# link_profile.py — CI-008, AR-162
# ---------------------------------------------------------------------------

def profile(inv: dict) -> dict:
    graph, crawled_keys, base, refused = link_profile.graph_from_inventory(inv)
    return link_profile.analyze_link_profile(
        graph, crawled_keys, base, refused,
        truncated=inv["summary"]["truncated"])


class Orphans(unittest.TestCase):
    def test_a_deep_entry_nothing_links_to_is_an_orphan(self):
        deep = SITE + "deep/page"
        out = profile(inventory([
            row(SITE, links=(SITE + "a", SITE + "b", SITE + "c")),
            row(SITE + "a", links=(SITE, SITE + "b", SITE + "c")),
            row(SITE + "b", links=(SITE, SITE + "a", SITE + "c")),
            row(SITE + "c", links=(SITE, SITE + "a", SITE + "b")),
            row(deep, links=(SITE, SITE + "a", SITE + "b"))], entry=deep))
        self.assertIn(deep, out["orphan_pages"]["urls"])
        self.assertEqual(verdict("CI-008", out), FAIL)

    def test_the_home_page_is_credited_unlinked(self):
        out = profile(inventory([
            row(SITE, links=(SITE + "a", SITE + "b", SITE + "c")),
            row(SITE + "a", links=(SITE + "b", SITE + "c", SITE + "d")),
            row(SITE + "b", links=(SITE + "a", SITE + "c", SITE + "d")),
            row(SITE + "c", links=(SITE + "a", SITE + "b", SITE + "d")),
            row(SITE + "d", links=(SITE + "a", SITE + "b", SITE + "c"))],
            entry=SITE + "a"))
        self.assertEqual(out["orphan_pages"]["count"], 0)
        self.assertEqual(verdict("CI-008", out), PASS)


class LinkStrength(unittest.TestCase):
    def test_repeated_and_self_links_do_not_make_a_page_well_linked(self):
        """AR-162: five links, all to one page or to itself, are not five links."""
        names = ("", "a", "b", "c")
        rows = []
        for i, name in enumerate(names):
            url, after = SITE + name, SITE + names[(i + 1) % len(names)]
            rows.append(row(url, links=(url, url, url, after, after)))
        out = profile(inventory(rows))
        self.assertEqual(out["orphan_pages"]["count"], 0)
        self.assertEqual(out["dead_end_pages"]["count"], 0)
        self.assertEqual(verdict("AR-162", out), FAIL)

    def test_a_page_linking_only_to_itself_is_a_dead_end(self):
        out = profile(inventory([
            row(SITE, links=(SITE + "a", SITE + "b", SITE + "c")),
            row(SITE + "a", links=(SITE + "a",)),
            row(SITE + "b", links=(SITE, SITE + "a", SITE + "c")),
            row(SITE + "c", links=(SITE, SITE + "a", SITE + "b"))]))
        self.assertIn(SITE + "a", out["dead_end_pages"]["urls"])


# ---------------------------------------------------------------------------
# internal_links.py — AR-149
# ---------------------------------------------------------------------------

class EachLinkedSpelling(unittest.TestCase):
    def test_a_redirecting_spelling_beside_a_live_one_is_counted(self):
        inv, url = crawled({
            "/": '<html><body><a href="/about">About</a> <a href="/x">X</a></body></html>',
            "/x": '<html><body><a href="/about/">About us</a></body></html>',
            "/about": "<html><body>About</body></html>",
            "/about/": (301, {"Location": "/about"}, ""),
        }, use_sitemap=False)
        out = internal_links.analyze(inv, url)
        self.assertEqual(out["summary"]["internal_redirects"], 1)
        self.assertEqual(out["internal_redirects"][0]["linked_from"], [url + "x"])
        self.assertNotEqual(verdict("AR-149", out), PASS)

    def test_a_sitemap_spelling_that_redirects_is_not_a_linked_redirect(self):
        """Aside: sitemap `/about/` 301, the links say `/about` — a false FAIL."""
        routes = {
            "/": '<html><body><a href="/about">About</a></body></html>',
            "/about": "<html><body>About</body></html>",
            "/about/": (301, {"Location": "/about"}, ""),
            "/sitemap.xml": (200, {"Content-Type": "application/xml"},
                             '<?xml version="1.0"?><urlset xmlns="http://www.'
                             'sitemaps.org/schemas/sitemap/0.9"><url><loc>{origin}'
                             '/about/</loc></url></urlset>'),
        }
        routes["/robots.txt"] = ROBOTS
        with harness.allow_loopback(), served(routes) as site:
            body = routes["/sitemap.xml"][2].replace("{origin}", site.url.rstrip("/"))
            site.routes["/sitemap.xml"] = harness._normalise(
                (200, {"Content-Type": "application/xml"}, body))
            inv = site_crawl.crawl(site.url, workers=1)
            url = site.url
        out = internal_links.analyze(inv, url)
        self.assertEqual(out["summary"]["internal_redirects"], 0, out["internal_redirects"])
        self.assertEqual(verdict("AR-149", out), PASS)


# ---------------------------------------------------------------------------
# topical_cluster_mapper.py — AR-153
# ---------------------------------------------------------------------------

class Hubs(unittest.TestCase):
    def test_singleton_clusters_are_not_hubs(self):
        titles = ["Plumbing repairs", "Garden design", "Tax returns", "Wedding cakes"]
        rows = []
        for i, title in enumerate(titles):
            url = SITE + f"p{i}"
            rows.append(row(url, title=title,
                            links=tuple(SITE + f"p{j}" for j in range(len(titles)) if j != i)))
        out = topical_cluster_mapper.map_inventory(inventory(rows))
        self.assertTrue(all(c["hub"] is None for c in out["clusters"].values()))
        self.assertEqual(verdict("AR-153", out), FAIL)

    def test_titles_this_reading_cannot_read_withhold_the_score(self):
        """No title word read (Cyrillic, empty): no hub cannot be told from no reading."""
        rows = [row(SITE + f"p{i}", title=title, links=(SITE,))
                for i, title in enumerate(["Главная", "Хлеб ржаной", "", "Доставка"])]
        out = topical_cluster_mapper.map_inventory(inventory(rows))
        self.assertNotIn("score", out)
        self.assertEqual(verdict("AR-153", out), NO_DATA)

    def test_a_one_page_site_keeps_its_score(self):
        """No hub needs two pages; one page is neither a site without hubs nor one
        whose titles could not be read (census: five one-page trees went NO_DATA)."""
        out = topical_cluster_mapper.map_inventory(inventory([row(SITE, title="Rye bread")]))
        self.assertEqual(verdict("AR-153", out), PASS)

    def test_a_cluster_of_two_or_more_has_a_hub(self):
        rows = [row(SITE + "roofing", title="Roofing guide",
                    links=(SITE + "roofing-tiles", SITE + "roofing-felt")),
                row(SITE + "roofing-tiles", title="Roofing tiles", links=(SITE + "roofing",)),
                row(SITE + "roofing-felt", title="Roofing felt", links=(SITE + "roofing",))]
        # Under half the titles, so "roofing" is a topic and not the site's own word.
        rows += [row(SITE + f"o{i}", title=title, links=(SITE + "roofing",))
                 for i, title in enumerate(["Contact details", "Delivery terms",
                                            "Careers board", "Privacy notice"])]
        out = topical_cluster_mapper.map_inventory(inventory(rows))
        self.assertEqual(verdict("AR-153", out), PASS)


# ---------------------------------------------------------------------------
# anchor_text_audit.py — BL-081
# ---------------------------------------------------------------------------

class Anchors(unittest.TestCase):
    def audit(self, rows):
        return anchor_text_audit.audit_anchor_text(SITE, inventory=inventory(rows))

    def test_generic_anchors_are_flagged(self):
        out = self.audit([
            row(SITE, links=(SITE + "a", SITE + "b"),
                anchors={SITE + "a": "Read more", SITE + "b": "Click here"}),
            row(SITE + "a"), row(SITE + "b")])
        self.assertNotEqual(verdict("BL-081", out), PASS)

    def test_empty_anchors_are_flagged(self):
        out = self.audit([row(SITE, links=(SITE + "a",), anchors={SITE + "a": ""}),
                          row(SITE + "a")])
        self.assertNotEqual(verdict("BL-081", out), PASS)

    def test_low_diversity_is_flagged(self):
        # Three of eight pages: under half, so editorial links and not a menu.
        rows = [row(SITE + f"s{i}", links=(SITE + "t",), anchors={SITE + "t": "blue widgets"})
                for i in range(3)] + [row(SITE + "t")] + [row(SITE + f"f{i}")
                                                         for i in range(4)]
        out = self.audit(rows)
        self.assertNotEqual(verdict("BL-081", out), PASS)

    def test_varied_descriptive_anchors_pass(self):
        out = self.audit([
            row(SITE, links=(SITE + "a", SITE + "b"),
                anchors={SITE + "a": "Roof repair prices", SITE + "b": "Gutter cleaning"}),
            row(SITE + "a"), row(SITE + "b")])
        self.assertEqual(verdict("BL-081", out), PASS)

    def test_an_image_link_is_named_by_its_alt(self):
        """Google reads an image link's alt as its anchor: a logo is not empty."""
        inv, url = crawled({
            "/": '<html><body><a href="/a"><img src="/l.png" alt="Acme home"></a>'
                 '</body></html>',
            "/a": "<html><body>A</body></html>"}, use_sitemap=False)
        anchors = [link["anchor"] for link in inv["pages"][url]["links"]]
        self.assertEqual(anchors, ["Acme home"])


# ---------------------------------------------------------------------------
# Review round 1
# ---------------------------------------------------------------------------

class ReviewRound1(unittest.TestCase):
    def test_a_redirect_and_its_target_are_one_page_not_duplicates(self):
        """A 301 `/old` -> `/new` row is `/new` read again, not a page competing."""
        new = row(SITE + "new", title="New", description="New page",
                  canonical=SITE + "new", text=words(300, "n"))
        old = dict(new, url=SITE + "old", final_url=SITE + "new", redirected=True,
                   redirect_chain=[SITE + "old"])
        inv = inventory([row(SITE), new])
        inv["pages"][site_crawl.page_key(SITE + "old")] = old
        out = duplicates(inv)
        self.assertEqual(verdict("MS-022", out), PASS)
        self.assertEqual(verdict("MS-029", out), PASS)
        self.assertEqual(verdict("CN-041", out), PASS)

    def test_a_page_read_at_a_query_spelling_still_names_itself(self):
        shop = row(SITE + "products?sort=price", title="Shop", canonical=SITE + "products",
                   text=words(300, "s"))
        inv = inventory([row(SITE + "shop", title="Shop", text=words(300, "s"))])
        inv["pages"][site_crawl.page_key(SITE + "products")] = shop
        out = duplicates(inv)
        self.assertEqual(out["summary"]["title_group_exclusions"]["canonicalized"], 0)
        self.assertEqual(verdict("MS-022", out), FAIL)

    def test_page_one_is_the_bare_page(self):
        self.assertEqual(site_crawl.page_key("https://x.test/blog?page=1"),
                         "https://x.test/blog")
        self.assertEqual(site_crawl.page_key("https://x.test/blog?PAGE=02"),
                         "https://x.test/blog?page=2")

    def test_a_variant_answering_another_page_is_not_this_page(self):
        """A soft 404 or a catch-all shell at `/a/` is not `/a` served twice."""
        for label, body in (
                ("soft-404", "<html><head><title>Page not found</title></head>"
                             "<body>Nothing here at all, sorry.</body></html>"),
                ("home-shell", page_html(title="Home", canonical="/",
                                         body=words(40, "home")))):
            with self.subTest(variant=label):
                out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                             "/a/": body})
                self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_variant_claiming_itself_with_the_page_fails(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                     "/a/": page_html(canonical="/a/")})
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_an_upper_case_host_has_its_www_twin(self):
        self.assertIn("https://www.ex.com/a",
                      [v.lower() for v in canonical_checker.url_variants("https://EX.com/a")])


class ReviewRound2(unittest.TestCase):
    def test_an_odd_page_number_does_not_crash_a_key(self):
        for value in ("%C2%B2", "\u2460", "9" * 5000):
            with self.subTest(value=value[:8]):
                self.assertEqual(site_crawl.page_key(f"https://x.test/blog?page={value}"),
                                 "https://x.test/blog")
                server_log_audit._log_key(f"/blog?page={value}")

    def test_a_canonical_to_the_page_on_another_scheme_is_still_the_page(self):
        text = words(300, "same")
        out = duplicates(inventory([
            row(SITE + "a", text=text, canonical="http://example.test/a"),
            row(SITE + "b", text=text, canonical="http://www.example.test/b")]))
        self.assertEqual(out["summary"]["title_group_exclusions"]["canonicalized"], 0)
        self.assertEqual(verdict("CN-041", out), FAIL)

    def test_a_canonical_to_a_broken_crawled_page_does_not_hide_the_copy(self):
        text = words(300, "same")
        out = duplicates(inventory([
            row(SITE + "a", text=text), row(SITE + "b", text=text, canonical=SITE + "gone"),
            row(SITE + "gone", status=404)]))
        self.assertEqual(verdict("CN-041", out), FAIL)

    def test_two_redirects_to_one_unread_page_are_one_page(self):
        target = SITE + "company"
        base = row(target, title="Company", description="Who we are", canonical=target,
                   text=words(300, "c"))
        inv = inventory([row(SITE)])
        for old in ("about-us", "company-info"):
            inv["pages"][site_crawl.page_key(SITE + old)] = dict(
                base, url=SITE + old, redirected=True, redirect_chain=[SITE + old])
        out = duplicates(inv)
        for item_id in ("MS-022", "MS-029", "CN-041"):
            with self.subTest(item=item_id):
                self.assertEqual(verdict(item_id, out), PASS)

    def test_go_137_folds_the_page_number(self):
        """A paginated listing with impressions is the listed page, as before F15."""
        import gsc_sitemap_reconcile

        class Service:
            def searchanalytics(self):
                return self

            def query(self, **kw):
                return self

            def execute(self):
                return {"rows": [{"keys": [SITE + "all?page=2"]},
                                 {"keys": [SITE + "all"]}]}
        pages = gsc_sitemap_reconcile._search_analytics_pages(Service(), "sc-domain:x",
                                                              SITE, 28)[0]
        self.assertEqual(pages, {SITE + "all"})

    def test_a_three_page_nav_is_not_low_diversity(self):
        """Under four pages a menu cannot be told from editorial links (navigation_links),
        so low diversity, newly counted, is not read there."""
        nav = (SITE, SITE + "about", SITE + "contact")
        names = {SITE: "Home", SITE + "about": "About", SITE + "contact": "Contact"}
        rows = [row(url, links=nav, anchors=names) for url in nav]
        out = anchor_text_audit.audit_anchor_text(SITE, inventory=inventory(rows))
        self.assertEqual(verdict("BL-081", out), PASS)

    def test_a_soft_404_sharing_the_site_title_is_not_the_page(self):
        out = served_rule("CI-009", {
            "/a": page_html(title="Acme", canonical="/a", body=words(60, "page")),
            "/a/": page_html(title="Acme", body="Sorry, that page was not found.")})
        self.assertEqual(verdict("CI-009", out), PASS)


class ReviewRound3(unittest.TestCase):
    def redirect_of(self, inv, landing_url, old_url):
        landing = inv["pages"][site_crawl.page_key(landing_url)]
        inv["pages"][site_crawl.page_key(old_url)] = dict(
            landing, url=old_url, redirected=True, redirect_chain=[old_url])

    def test_a_redirect_row_does_not_make_an_ar_153_hub(self):
        titles = ["Plumbing repairs", "Garden design", "Tax returns", "Wedding cakes"]
        rows = [row(SITE + f"p{i}", title=t,
                    links=tuple(SITE + f"p{j}" for j in range(4) if j != i))
                for i, t in enumerate(titles)]
        inv = inventory(rows)
        self.redirect_of(inv, SITE + "p0", SITE + "old-plumbing")
        out = topical_cluster_mapper.map_inventory(inv)
        self.assertEqual(verdict("AR-153", out), FAIL)

    def test_a_redirect_row_does_not_double_anchors(self):
        target = SITE + "target"
        guide = row(SITE + "guide", links=(target, target, target),
                    anchors={target: "Pricing"})
        guide["links"][2]["anchor"] = "Our prices"
        rows = [guide, row(target)] + [row(SITE + f"f{i}") for i in range(6)]
        inv = inventory(rows)
        self.redirect_of(inv, SITE + "guide", SITE + "old-guide")
        out = anchor_text_audit.audit_anchor_text(SITE, inventory=inv)
        self.assertEqual(out["summary"]["low_diversity_targets"], 0)
        self.assertEqual(verdict("BL-081", out), PASS)

    def test_pager_numbers_are_not_unnatural_anchors(self):
        pages = [SITE + "shop"] + [SITE + f"shop?page={n}" for n in range(2, 13)]
        rows = []
        for url in pages:
            r = row(url, links=tuple(pages))
            for link, target in zip(r["links"], pages, strict=True):
                link["anchor"] = target.rsplit("=", 1)[-1] if "=" in target else "1"
            rows.append(r)
        rows += [row(SITE + f"f{i}") for i in range(30)]
        out = anchor_text_audit.audit_anchor_text(SITE, inventory=inventory(rows))
        self.assertEqual(verdict("BL-081", out), PASS)

    def test_a_canonical_target_is_broken_only_at_its_own_url(self):
        text = words(300, "same")
        gone = row(SITE + "p?id=1", status=404)
        inv = inventory([row(SITE + "a", text=text),
                         row(SITE + "b", text=text, canonical=SITE + "p?id=2")])
        inv["pages"][site_crawl.page_key(SITE + "p")] = gone
        out = duplicates(inv)
        self.assertEqual(out["summary"]["title_group_exclusions"]["canonicalized"], 1)

    def test_a_spelling_answering_503_is_unchecked(self):
        inv, url = crawled({
            "/": '<html><body><a href="/about">About</a> <a href="/x">X</a></body></html>',
            "/x": '<html><body><a href="/about/">About us</a></body></html>',
            "/about": "<html><body>About</body></html>",
            "/about/": (503, {}, "busy"),
        }, use_sitemap=False)
        self.assertTrue(inv["spellings"][url + "about/"]["unchecked"])
        self.assertEqual(internal_links.analyze(inv, url)["truncated"], True)


class ReviewRound4(unittest.TestCase):
    def test_a_blog_linking_each_post_by_its_title_passes_bl_081(self):
        """Posts listed as cards (image + title link) on home and /blog, and by title on
        a category page and from the previous post: the natural anchor, not a pattern."""
        posts = [SITE + f"post-{i}" for i in range(12)]
        titles = {url: f"Post number {i} about baking" for i, url in enumerate(posts)}
        rows = []
        for listing in (SITE, SITE + "blog", SITE + "cat"):
            r = row(listing, links=())
            for url in posts:
                if listing != SITE + "cat":
                    r["links"].append({"target": url, "internal": True, "rel": [],
                                       "nofollow": False, "anchor": titles[url],
                                       "alt_named": True})
                r["links"].append({"target": url, "internal": True, "rel": [],
                                   "nofollow": False, "anchor": titles[url]})
            rows.append(r)
        for i, url in enumerate(posts):
            after = posts[(i + 1) % len(posts)]
            rows.append(row(url, title=f"{titles[url]} | Bakery", links=(after,),
                            anchors={after: titles[after]}))
        out = anchor_text_audit.audit_anchor_text(SITE, inventory=inventory(rows))
        self.assertEqual(out["summary"]["overused_exact_match_targets"], 0)
        self.assertEqual(out["summary"]["low_diversity_targets"], 0)
        self.assertEqual(verdict("BL-081", out), PASS)

    def test_a_title_with_its_brand_is_the_anchor_s_title(self):
        for sep in anchor_text_audit.TITLE_SEPARATORS:
            with self.subTest(sep=sep):
                self.assertTrue(anchor_text_audit.names_its_title(
                    "Rye bread", f"Rye bread {sep} Bakery"))
                self.assertTrue(anchor_text_audit.names_its_title(
                    "Rye bread", f"Bakery {sep} Rye bread"))
        self.assertFalse(anchor_text_audit.names_its_title("Rye", "Rye bread | Bakery"))

    def test_the_crawl_marks_an_anchor_named_by_alt(self):
        inv, url = crawled({
            "/": '<html><body><a href="/a"><img src="/l.png" alt="Acme"></a>'
                 '<a href="/a">Acme</a></body></html>',
            "/a": "<html><body>A</body></html>"}, use_sitemap=False)
        self.assertEqual([link.get("alt_named", False) for link in inv["pages"][url]["links"]],
                         [True, False])

    def test_an_http_copy_canonical_to_the_crawled_https_page_is_canonicalised(self):
        text = words(300, "same")
        out = duplicates(inventory([
            row(SITE + "a", text=text, canonical=SITE + "a"),
            row("http://example.test/a", text=text, canonical=SITE + "a")]))
        self.assertEqual(verdict("CN-041", out), PASS)

    def test_an_idn_site_keeps_its_sitemap_urls(self):
        site = "https://bücher.example/"
        body = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
                f'sitemap/0.9"><url><loc>{site}a</loc></url></urlset>')

        def fetch(url, **kw):
            return {"status": 200, "url": url, "text": body, "body": body.encode(),
                    "bytes": len(body), "headers": {"content-type": "application/xml"}}
        out = site_crawl.load_sitemap_urls(site, sitemap_urls=[site + "sitemap.xml"],
                                           fetch=fetch)
        self.assertEqual(out["off_host"], [])
        self.assertEqual(out["urls"], [site_crawl.page_key(site + "a")])

    def test_a_linked_page_one_spelling_is_fetched(self):
        self.assertNotEqual(site_crawl.spelling_of("https://x.test/blog?page=1"),
                            site_crawl.spelling_of("https://x.test/blog"))


class ReviewRound5(unittest.TestCase):
    def test_a_name_colon_subtitle_title_is_the_anchor_s_title(self):
        self.assertTrue(anchor_text_audit.names_its_title(
            "Rye starter", "Rye starter: a step-by-step guide (2026) | Bakery"))

    def test_a_mostly_unreadable_site_is_withheld_not_failed(self):
        titles = (["Хлеб ржаной", "Булочки", "Печенье", "Контакты", "Доставка", "Главная"]
                  + ["Миксер KitchenAid", "Духовка Bosch"])
        rows = [row(SITE + f"p{i}", title=t, links=(SITE,)) for i, t in enumerate(titles)]
        out = topical_cluster_mapper.map_inventory(inventory(rows))
        self.assertEqual(verdict("AR-153", out), NO_DATA)

    def test_an_idn_site_given_in_punycode_keeps_a_unicode_sitemap(self):
        site = "https://xn--bcher-kva.example/"
        body = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
                'sitemap/0.9"><url><loc>https://bücher.example/a</loc></url></urlset>')

        def fetch(url, **kw):
            return {"status": 200, "url": url, "text": body, "body": body.encode(),
                    "bytes": len(body), "headers": {"content-type": "application/xml"}}
        out = site_crawl.load_sitemap_urls(site, sitemap_urls=[site + "sitemap.xml"],
                                           fetch=fetch)
        self.assertEqual(out["off_host"], [])
        self.assertEqual(len(out["urls"]), 1)

    def test_a_canonical_in_the_body_or_an_svg_is_not_declared(self):
        inv, url = crawled({"/": '<html><head><link rel="canonical" href="/"></head><body>'
                                 '<svg><link rel="canonical" href="/x"/></svg>'
                                 '<link rel="canonical" href="/y">Home</body></html>'},
                           use_sitemap=False)
        self.assertEqual(inv["pages"][url]["canonicals"], [url])

    def test_a_busy_canonical_target_is_unchecked_not_unavailable(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/b"),
                                     "/b": (503, {"Retry-After": "0"}, "busy")})
        self.assertEqual(verdict("CI-009", out), NO_DATA)

    def test_a_busy_variant_is_unchecked(self):
        out = served_rule("CI-009", {"/a": page_html(canonical="/a"),
                                     "/a/": (503, {"Retry-After": "0"}, "busy")})
        self.assertEqual(verdict("CI-009", out), NO_DATA)
        self.assertEqual(out["issues"], [])


# ---------------------------------------------------------------------------
# The sentences
# ---------------------------------------------------------------------------

class MeasuresSentences(unittest.TestCase):
    """The `measures` ruling (CI-018) and the sentences the fix rulings asked for."""

    SAYS = {
        "CI-018": "crawl budget",
        "MS-022": "canonical",
        "CN-041": "noindex",
        "BL-081": "internal",
        "CI-009": "variant",
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, word in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(word, ITEMS[item_id].get("measures", ""))


if __name__ == "__main__":
    unittest.main()
