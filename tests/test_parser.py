"""Which HTML parser reads a page, and what changes when it is the other one.

KNOWN-ISSUES carried this as "it needs measuring on real sites, not a default". This
file is that measurement, taken against a committed corpus instead of a crawl, and the
reasoning for the substitution is worth stating because it is a judgement, not a
shortcut:

- **A crawl is evidence that decays.** The sites would change, the numbers behind the
  decision could not be re-derived by anyone reading this later, and nothing could be
  committed. This project already made that call once, for the Public Suffix List:
  bundle a dated snapshot rather than fetch at audit time, because a run must answer
  the same offline and next month. Evidence behind a *decision* deserves the same
  treatment as evidence behind a verdict.
- **The suite is offline and stays offline.** Loopback only. A test that reached
  en.wikipedia.org to decide a parser would make every future contributor's CI depend
  on somebody else's uptime, and `broken_links.py` requests every link it finds.
- **What a corpus cannot do** is contain a divergence nobody thought of. So the
  decision is also made *cheap to revisit*: `SEO_HTML_PARSER` switches the parser, the
  run records which one produced its verdicts, and an operator who suspects the parser
  on a real site can re-run and diff. That override is the honest half of a
  fixture-measured decision — it is what makes being wrong here recoverable.

The shapes are chosen for what real generators emit, not for what breaks a parser:
unclosed `<p>` and `<li>` (WordPress themes, hand-written HTML), 300-deep `<div>`
nesting (React/Tailwind output), an inline `<svg>` carrying its own `<title>` (icon
sprites), `<template>` and `<noscript>` (component frameworks), a `<div>` inside
`<head>` (injected tags), `<picture>` (responsive images), a bare fragment (a CMS
partial), duplicate attributes and unquoted values (CDN rewriting).

**The result.** Every field the registry reads is identical under both parsers across
all fifteen shapes. The divergence is structural — parent/child, not values — and it
reached exactly two call sites, both pinned below.

One of the two used to change a *verdict*: `answer_block_scanner.py` scored the same
page 10 or 32 depending on the parser. 0.15.0 fixed it rather than recording it, and
the tests below now assert the two parsers **agree**. That is a stronger pin than the
numbers were: a divergence recorded as a pair of numbers goes stale the moment either
side moves, while an equality assertion fails the day a new structural query is
written against sibling position again.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import bs4  # noqa: E402
import seo_common  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import served, spawn  # noqa: E402

PARSERS = ("lxml", "html.parser")

# Every field `seo_common.parse_html` returns that a registry rule reads. Not a
# hand-picked subset: the assertion below is that *all* of them agree, so a field
# added to the parser output joins this test by existing.
SKIP_FIELDS = {"soup", "body_text"}          # not JSON-serialisable / whitespace-only


CORPUS = {
    "picture_source": """<html><head><title>T</title></head><body>
<picture><source srcset="a.webp" type="image/webp"><source srcset="a.avif">
<img src="a.jpg" alt="A"></picture></body></html>""",

    "unclosed_p_li": """<html><head><title>T</title></head><body>
<p>one<p>two<ul><li>a<li>b</ul><div><span>x</div></body></html>""",

    "inline_svg_title": """<html><head><title>Real page title</title></head><body>
<svg viewBox="0 0 10 10"><title>Icon label</title><path d="M0 0"/></svg>
<h1>H</h1></body></html>""",

    "div_in_head": """<html><head><div>junk in head</div>
<title>T</title><meta name="description" content="D">
<meta name="viewport" content="width=device-width"></head><body><h1>H</h1></body></html>""",

    "template_and_noscript": """<html><head><title>T</title></head><body>
<h1>Real</h1><template><h1>In template</h1></template>
<noscript><h1>In noscript</h1><a href="/ns">ns</a></noscript></body></html>""",

    "deep_nesting_300": ("<html><head><title>T</title>"
                         '<meta name="description" content="D"></head><body>'
                         + "<div>" * 300 + '<h1>Deep heading</h1><a href="/deep">deep</a>'
                         + "</div>" * 300 + "</body></html>"),

    "deep_nesting_60": ("<html><head><title>T</title></head><body>"
                        + "<div>" * 60 + "<h1>Deep heading</h1>"
                        + "</div>" * 60 + "</body></html>"),

    "nested_form": """<html><head><title>T</title></head><body>
<form action="/a"><input name="x"><form action="/b"><input name="y"></form></form>
</body></html>""",

    "table_implied_tbody": """<html><head><title>T</title></head><body>
<table><tr><td><a href="/in-table">link</a></td></tr></table></body></html>""",

    "custom_elements": """<html><head><title>T</title></head><body>
<my-widget><h1>Inside a custom element</h1><a href="/ce">x</a></my-widget>
<slot name="s"><p>slotted</p></slot></body></html>""",

    "conditional_comment": """<html><head><title>T</title></head><body>
<!--[if IE]><p>old</p><![endif]--><h1>H</h1></body></html>""",

    "bad_attrs": """<html><head><title>T &amp; more</title></head><body>
<a href="/q?a=1&b=2" class="x" class="y">link</a><img src=a.jpg alt=Unquoted>
</body></html>""",

    "fragment_no_html": "<title>T</title><h1>H</h1><p>A CMS partial, no html or body.</p>",

    "ldjson_in_body": """<html><head><title>T</title></head><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article"}</script>
<h1>H</h1></body></html>""",

    "two_titles": """<html><head><title>First</title><title>Second</title></head>
<body><h1>H</h1></body></html>""",
}


def parse_with(html: str, parser: str) -> dict:
    """`seo_common.parse_html`, forced onto one parser.

    Patched at `seo_common.BeautifulSoup` rather than through `SEO_HTML_PARSER`,
    because this has to keep working if `html_parser()` is ever changed — the point of
    the test is the two parsers' behaviour, not the function that picks between them.
    """
    saved = seo_common.BeautifulSoup
    seo_common.BeautifulSoup = lambda markup, _parser: bs4.BeautifulSoup(markup, parser)
    try:
        return seo_common.parse_html(html, "https://example.com/")
    finally:
        seo_common.BeautifulSoup = saved


def executable_source(path: str) -> str:
    """A file's code with every comment and string literal removed.

    `tokenize` rather than a regex or the AST: the AST would need a visitor per node
    type to reconstruct the expression, and a regex cannot tell code from the prose
    beside it — which is the whole reason this function exists.
    """
    import io
    import tokenize
    kept = []
    with open(path, "rb") as f:
        for token in tokenize.tokenize(io.BytesIO(f.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def comparable(parsed: dict) -> dict:
    out = {}
    for key, value in parsed.items():
        if key in SKIP_FIELDS:
            continue
        out[key] = json.dumps(value, default=str, sort_keys=True)
    return out


class TheChoiceIsDeliberate(unittest.TestCase):
    """The defect, separately from which parser wins it.

    `"lxml" if "lxml" in sys.modules else "html.parser"` asks whether something
    imported lxml first, not whether lxml is installed — so the same page could be
    parsed two ways on one machine, and `parse_html.py` and `seo_common` could
    disagree inside a single audit.
    """

    def setUp(self):
        self.saved = os.environ.get("SEO_HTML_PARSER")
        os.environ.pop("SEO_HTML_PARSER", None)

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("SEO_HTML_PARSER", None)
        else:
            os.environ["SEO_HTML_PARSER"] = self.saved

    def test_no_script_decides_the_parser_by_import_order_any_more(self):
        """Source-level, and deliberately so: a behavioural test cannot see a second
        copy of the pattern in a script nobody thought to import here.

        Comments and string literals are stripped first, and that is not fussiness —
        the first version of this test failed on `seo_common.py` and `parse_html.py`
        because their new docstrings *quote* the old expression while explaining why it
        was wrong. Same trap `audit_assertions.py` fell into: a scan for "strings this
        file contains" counts the paragraph describing what the code used to do.
        """
        offenders = []
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py"):
                continue
            code = executable_source(os.path.join(SCRIPTS, name))
            if "sys.modules" in code and "lxml" in code:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_lxml_is_preferred_when_it_imports(self):
        self.assertEqual(seo_common.html_parser(), "lxml")

    def test_the_override_is_honoured_and_a_typo_is_not(self):
        os.environ["SEO_HTML_PARSER"] = "html.parser"
        self.assertEqual(seo_common.html_parser(), "html.parser")
        # Same rule as a nonsense SEO_MAX_RPS falling back to the default rather than
        # to no limit: a typo must never quietly change what a run measures.
        os.environ["SEO_HTML_PARSER"] = "lxlm"
        self.assertEqual(seo_common.html_parser(), "lxml")

    def test_the_run_records_which_parser_produced_its_verdicts(self):
        """A reader comparing two runs that disagree has to be able to rule this out."""
        from checklist_runner import html_parser as recorded
        self.assertEqual(recorded(), seo_common.html_parser())

    def test_an_unimportable_seo_common_costs_a_label_and_not_the_run(self):
        """Why the import stays inside the function, asserted rather than commented.

        The runner is importable without bs4 or lxml on purpose: `--archive` has to
        run on a bare checkout, and this label is one field in the artifact. Hoisting
        `from seo_common import html_parser` to module level would read as a tidy-up
        and would turn a missing optional dependency into a runner that cannot start.
        """
        import checklist_runner
        with mock.patch.dict(sys.modules, {"seo_common": None}):
            self.assertEqual(checklist_runner.html_parser(), "unknown")

    def test_both_html_parsing_entry_points_agree(self):
        """`parse_html.py` had its own copy of the import-order test, so one audit
        could parse the same page two ways depending on which check reached it."""
        import parse_html
        self.assertIs(parse_html.html_parser, seo_common.html_parser)


class NoScriptChoosesItsOwnParser(unittest.TestCase):
    """`html_parser` opens by calling itself "one decision, in one place". It was not.

    Until 0.79.0 thirteen of the seventeen files that build a soup passed `"html.parser"`
    themselves, so the function's claim was false for most of the tree and a verdict could
    depend on which file happened to read the page. `WhereTheParsersActuallyDiverge` below
    says what that costs, in the words 0.15.0 left there: a verdict that depends on which
    parser is installed is not a fact worth recording, it is a defect.

    The switch was made on evidence. Each of the twelve remaining scripts was run over a
    page carrying every shape the two parsers are known to read differently —
    `<picture><source><img>`, unclosed `<p>` and `<li>`, a table with no `<tbody>`, a block
    inside an inline, `<noscript>` wrapping a `<link>`, a `<meta>`, a `<script src>` and an
    `<img>` — once under each parser, and ten emitted byte-identical JSON. The two that
    take no page argument had the reads they actually make measured instead, eleven of
    eleven identical. The whole suite run with every `"html.parser"` call forced to the
    shared choice moved nothing and left the oracle at 246/219/0/27.

    **Two censuses, because one of them has a hole a reviewer found before this shipped.**
    Matching calls whose callee is named `BeautifulSoup` misses
    `from bs4 import BeautifulSoup as BS` followed by `BS(html, "html.parser")`, and misses
    a wrapper that takes the parser as an argument. So the first census is over the
    *literal*: `"html.parser"` may be written in `seo_common.py`, which owns the decision,
    and nowhere else — which is what "one decision, in one place" means when it is enforced
    rather than asserted. The second census still walks `BeautifulSoup(` calls, because the
    literal census cannot see a call that names no parser at all and takes whatever bs4
    guesses.

    A census rather than a sample, because no test data in this repository can tell the two
    parsers apart in any field the registry reads — `EveryFieldTheRegistryReadsIsParserIndependent`
    is the proof of that, and it is why a hardcoded parser in a new script would fail here
    and nowhere else.
    """

    @staticmethod
    def _docstring_nodes(tree):
        import ast
        found = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not (body and isinstance(node, (ast.Module, ast.ClassDef,
                                               ast.FunctionDef, ast.AsyncFunctionDef))):
                continue
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                found.add(id(first.value))
        return found

    def test_the_parser_name_is_written_in_one_file_only(self):
        """The literal census: it catches an aliased import, which the call census cannot."""
        import ast
        written = []
        for path in sorted(pathlib.Path(SCRIPTS).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            skip = self._docstring_nodes(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and node.value == "html.parser"
                        and id(node) not in skip and path.name != "seo_common.py"):
                    written.append(f"{path.name}:{node.lineno}")
        self.assertEqual(written, [],
                         "the parser name belongs in seo_common.html_parser and nowhere "
                         "else; these name it themselves")

    def test_every_soup_names_the_shared_choice(self):
        """The call census: it catches a call that names no parser at all."""
        import ast

        def called(node):
            return getattr(node.func, "id", getattr(node.func, "attr", ""))

        shared, unnamed = [], []
        for path in sorted(pathlib.Path(SCRIPTS).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and called(node) == "BeautifulSoup"):
                    continue
                where = f"{path.name}:{node.lineno}"
                if any(isinstance(x, ast.Call) and called(x) == "html_parser"
                       for x in ast.walk(node)):
                    shared.append(where)
                else:
                    unnamed.append(where)
        self.assertEqual(unnamed, [],
                         "these build a soup without asking html_parser(), so the parser "
                         "is whatever bs4 guesses from what is installed")
        self.assertGreaterEqual(len(shared), 18,
                                "fewer call sites than when this was written; if one was "
                                "deleted, say so here")


class EveryFieldTheRegistryReadsIsParserIndependent(unittest.TestCase):
    """The measurement. Fifteen shapes, every returned field, both parsers.

    This is what licenses choosing lxml on fixtures rather than on a crawl: the
    disagreement is not in the values any rule reads. If a future bs4 or libxml2
    release changes that, this fails and the decision gets revisited with evidence.
    """

    def test_all_fields_match_on_every_shape(self):
        divergences = []
        for name, html in CORPUS.items():
            a, b = comparable(parse_with(html, "lxml")), comparable(parse_with(html, "html.parser"))
            self.assertEqual(sorted(a), sorted(b), f"{name}: different fields emitted")
            for field in sorted(a):
                if a[field] != b[field]:
                    divergences.append(f"{name}.{field}: lxml={a[field][:60]} "
                                       f"html.parser={b[field][:60]}")
        self.assertEqual(divergences, [],
                         "the parsers disagree about a field a rule reads:\n"
                         + "\n".join(f"  {d}" for d in divergences))

    def test_the_corpus_covers_the_shapes_the_docstring_claims(self):
        """A corpus is only evidence for what is in it, so what is in it is asserted
        rather than described. Dropping a shape has to be a visible act."""
        self.assertEqual(len(CORPUS), 15)
        for required in ("picture_source", "unclosed_p_li", "deep_nesting_300",
                         "inline_svg_title", "template_and_noscript",
                         "fragment_no_html", "div_in_head"):
            self.assertIn(required, CORPUS)


class WhereTheParsersActuallyDiverge(unittest.TestCase):
    """The two structural call sites, and what each one does about it.

    The first — `<picture>` — is a divergence the code copes with, pinned with its
    numbers because those are the facts that would have to be re-measured if the
    parser choice were revisited.

    The second used to be pinned the same way, at 10 against 32, and that was the
    wrong thing to do with it. A verdict that depends on which parser is installed is
    not a fact worth recording; it is a defect, and 0.15.0 fixed the instrument that
    caused it. The tests below assert agreement now.
    """

    def scan(self, html: str, parser: str) -> dict:
        """`answer_block_scanner` over fixed markup with a fixed parser.

        The patch goes at `seo_common.BeautifulSoup` and `load_source`, so the script
        runs its real logic over a document it cannot fetch and a parser it did not
        choose. Restored in `finally` because leaving either patched changes every
        test that runs after this one in the same process.

        Patched on the module that imported it, not on `seo_common`: the scripts do
        `from seo_common import load_source`, so each holds its own reference and
        rebinding the source module would not reach them.
        """
        import answer_block_scanner as scanner
        saved_load, saved_bs = scanner.load_source, seo_common.BeautifulSoup
        scanner.load_source = lambda source, timeout: (html, "https://example.com/", {})
        seo_common.BeautifulSoup = (
            lambda markup, _p, _parser=parser: bs4.BeautifulSoup(markup, _parser))
        try:
            return scanner.scan_answer_blocks("https://example.com/")
        finally:
            scanner.load_source, seo_common.BeautifulSoup = saved_load, saved_bs

    PICTURE = """<picture><source srcset="a.webp" type="image/webp">
<source srcset="a.avif"><img src="a.jpg" alt="A"></picture>"""

    def test_lxml_nests_the_img_inside_the_first_source(self):
        """libxml2 predates `<picture>` and does not know `<source>` is void. This is
        the whole divergence, and it is why `picture_sources()` walks up to any
        ancestor and scans recursively instead of trusting the parent."""
        shapes = {}
        for parser in PARSERS:
            soup = bs4.BeautifulSoup(self.PICTURE, parser)
            img = soup.find("img")
            picture = soup.find("picture")
            shapes[parser] = (img.parent.name,
                              len(picture.find_all("source", recursive=False)),
                              len(picture.find_all("source")))
        self.assertEqual(shapes["lxml"], ("source", 1, 2))
        self.assertEqual(shapes["html.parser"], ("picture", 2, 2))

    def test_picture_sources_survives_both(self):
        """The function every responsive-image check goes through. It found two
        sources under both parsers before this test existed — by luck of being written
        defensively, which is not a property anybody should rely on twice."""
        for parser in PARSERS:
            soup = bs4.BeautifulSoup(self.PICTURE, parser)
            sources = seo_common.picture_sources(soup.find("img"), "https://example.com/")
            self.assertEqual(len(sources), 2, parser)
            self.assertEqual(sources[0]["type"], "image/webp", parser)

    UNCLOSED_ANSWER = """<html><head><title>T</title></head><body>
<h2>How long does bread keep?</h2><p>Three days in paper, a week in the freezer,
because the acidity in sourdough slows staling down considerably.
<h2>What is a starter?</h2><ul><li>flour<li>water<li>time</ul></body></html>"""

    VALID_ANSWER = """<html><head><title>T</title></head><body>
<h2>How long does bread keep?</h2><p>Three days in paper, a week in the freezer,
because the acidity in sourdough slows staling down considerably.</p>
<h2>What is a starter?</h2><ul><li>flour</li><li>water</li><li>time</li></ul></body></html>"""

    UNCLOSED_LI = """<html><head><title>T</title></head><body>
<h2>How long does bread keep?</h2><p>Three days in paper, a week in the freezer,
because the acidity in sourdough slows staling down considerably.</p>
<h2>What is a starter?</h2><ul><li>flour<li>water<li>time</ul></body></html>"""

    def test_the_answer_block_score_no_longer_depends_on_closing_tags(self):
        """The one place the parser used to change a *verdict*, and now the one place
        this file proves a fix rather than records a fact.

        Three documents that a browser renders identically — one closing every tag,
        one leaving `<p>` open, one leaving `<li>` open. They used to score 10, 32 and
        0 across the two parsers, because `html.parser` applies none of HTML's implied
        end tags: an unclosed paragraph swallows the heading and list that follow it,
        and three list items nest three deep. Every one of those numbers was wrong
        about the page.

        All nine readings are the same now, and it is the same reading a browser gives:
        one three-item list, no direct answer — the paragraph is 18 words, under the
        20-word floor. The assertion is *equality between the parsers and between the
        three shapes*, which is a stronger statement than the old pair of pinned
        numbers: it fails on any new structural query that trusts sibling position,
        not only on the two that did.
        """
        shapes = {"valid": self.VALID_ANSWER,
                  "unclosed_p": self.UNCLOSED_ANSWER,
                  "unclosed_li": self.UNCLOSED_LI}
        seen = {}
        for shape, html in shapes.items():
            for parser in PARSERS:
                out = self.scan(html, parser)
                seen[f"{shape}/{parser}"] = (out["score"], len(out["direct_answers"]),
                                             len(out["definitions"]), len(out["lists"]))
        self.assertEqual(set(seen.values()), {(10, 0, 0, 1)}, seen)

    def test_a_list_item_reports_its_own_text_under_either_parser(self):
        """Not only the count. `html.parser`'s nested items make each `<li>`'s
        `get_text()` include every item after it, so the first item of a three-item
        list read "flour water time" — the evidence string a report shows a client,
        wrong in a way the score could not reveal."""
        for html in (self.VALID_ANSWER, self.UNCLOSED_LI, self.UNCLOSED_ANSWER):
            for parser in PARSERS:
                out = self.scan(html, parser)
                self.assertEqual(out["lists"][0]["sample"], ["flour", "water", "time"],
                                 parser)

    WRAPPED_ANSWER = """<html><body><h2>How long does bread keep?</h2>
<div class="entry-content"><p>Three days in paper, a week in the freezer, because the
acidity in a sourdough starter slows the staling process down very considerably.</p>
<p>Longer if you slice it first and freeze the slices, which also means you can toast
straight from frozen without waiting for a whole loaf to thaw on the counter.</p></div>
</body></html>"""

    def test_a_wrapped_answer_is_the_paragraph_and_not_the_wrapper(self):
        """The second defect the sibling walk was hiding, and it needed no invalid
        markup at all.

        A `<div>` between the heading and the paragraph — every themed CMS on the web
        — was itself read as the answer, so the word count was the whole section's.
        Two paragraphs measured 53 words and squeezed under the 70-word ceiling with
        the wrong text attached; three or more went over it and the page had no direct
        answer. Walking through wrappers to the prose gives the paragraph, 23 words,
        under both parsers.
        """
        for parser in PARSERS:
            out = self.scan(self.WRAPPED_ANSWER, parser)
            self.assertEqual(len(out["direct_answers"]), 1, parser)
            answer = out["direct_answers"][0]
            self.assertEqual(answer["word_count"], 23, parser)
            self.assertTrue(answer["answer"].endswith("considerably."), answer)

    def test_no_structural_query_trusts_sibling_position(self):
        """What actually keeps the fix from being written back.

        `find_next_sibling` asks the parser where an element's parent ends, and that
        is the one question the two parsers answer differently. Read from the tokens
        rather than the text, because this file's own prose names the method and the
        first version of a grep test in this tree matched its own docstring.
        """
        path = os.path.join(SCRIPTS, "answer_block_scanner.py")
        self.assertNotIn("find_next_sibling", executable_source(path))


class PageSchemaBoundary(unittest.TestCase):
    @staticmethod
    def _script(document):
        return ('<script type="application/ld+json">' + json.dumps(document) +
                '</script>')

    def _split_page(self):
        own = self._script({"@type": "Article", "name": "Page article"})
        foreign = self._script({"@type": "Person", "name": "D Petras"})
        return seo_common.parse_html(
            own + '<div itemprop="comment">' + foreign + '</div>',
            "https://example.com/",
        )

    def test_document_schema_keeps_two_blocks_while_page_schema_keeps_one(self):
        parsed = self._split_page()
        self.assertEqual(len(parsed["schema"]), 2)
        self.assertEqual(len(parsed["page_schema"]), 1)

    def test_page_schema_shares_the_document_schema_object(self):
        parsed = self._split_page()
        self.assertIs(parsed["page_schema"][0], parsed["schema"][0])

    def test_invalid_json_inside_a_comment_is_document_schema_only(self):
        parsed = seo_common.parse_html(
            '<div itemprop="comment"><script type="application/ld+json">'
            '{broken json</script></div>',
            "https://example.com/",
        )
        self.assertEqual(len(parsed["schema"]), 1)
        self.assertEqual(parsed["schema"][0]["error"], "invalid_json")
        self.assertIn("{broken json", parsed["schema"][0]["snippet"])
        self.assertEqual(parsed["page_schema"], [])

    def test_without_microdata_page_schema_matches_schema_entry_for_entry(self):
        parsed = seo_common.parse_html(
            self._script({"@type": "Article"}) +
            self._script({"@type": "Organization"}),
            "https://example.com/",
        )
        self.assertEqual(parsed["page_schema"], parsed["schema"])
        self.assertTrue(all(page is document for page, document in
                            zip(parsed["page_schema"], parsed["schema"], strict=True)))

    def test_is_based_on_excludes_even_the_pages_own_article(self):
        # This is the current answer, not the right one: KNOWN-ISSUES.md records the
        # open question about the foreign-credit key set's width.
        parsed = seo_common.parse_html(
            '<div itemprop="isBasedOn">' + self._script({
                "@type": "Article", "author": {"name": "M K"},
            }) + '</div>',
            "https://example.com/",
        )
        self.assertEqual(len(parsed["schema"]), 1)
        self.assertEqual(parsed["page_schema"], [])

    def test_document_schema_still_keeps_the_commenters_block(self):
        parsed = self._split_page()
        self.assertEqual(len(parsed["schema"]), 2)



class TheRecordedParserReachesTheArtifactAndTheReader(unittest.TestCase):
    """`openspec/specs/http/` HTTP-12's last clause: the run SHALL record which parser
    produced its verdicts, and a report produced by the fallback parser says so on its face.

    Agreement between the parsers is enforced across fifteen document shapes, and the single
    choice point by two AST censuses. The *recording* was the gap, and the gap had a
    particular shape worth naming: `test_the_run_records_which_parser_produced_its_verdicts`
    is named for it and asserts that two functions return the same string. That reads the
    label; nothing read the field. The runner could have stopped writing `html_parser` into
    the payload, or written a constant, and the suite would have stayed green — and the
    field exists for exactly one purpose, which is to be read out of an artifact months
    later when two runs disagree about a structural verdict.

    So this runs the audit twice, once under each parser, and reads the field out of the
    file both times. It is slower than any other test in this module and it is the only one
    that holds the sentence.
    """

    PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>A page that satisfies the basics</title>"
            "<meta name=\"description\" content=\"Enough of a page for the runner to reach "
            "the end and write an artifact.\"></head><body><h1>A page</h1>"
            "<p>Body copy with enough words in it that the thin-entry guard stays quiet, "
            "because a guard firing here would stop the audit before the thing under test "
            "ran at all.</p></body></html>")

    @classmethod
    def audit(cls, parser=None):
        work = tempfile.mkdtemp(prefix="seo-parser-")
        out = os.path.join(work, "results.json")
        env = dict(os.environ)
        env.pop("SEO_HTML_PARSER", None)
        if parser:
            env["SEO_HTML_PARSER"] = parser
        with served({"/": cls.PAGE}) as site:
            proc = spawn([sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"),
                          site.url, "--allow-private", "--max-rps", "0", "--no-history",
                          "--no-prompt", "--quiet", "--timeout", "90", "--json", out,
                          "--only", "crawling_indexing"], env=env, timeout=600)
        if proc.returncode != 0:
            raise AssertionError("the audit exited %s\n%s\n%s"
                                 % (proc.returncode, proc.stdout[-2000:],
                                    proc.stderr[-2000:]))
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    @classmethod
    def setUpClass(cls):
        cls.default = cls.audit()
        cls.fallback = cls.audit("html.parser")

    def test_the_artifact_names_the_parser_that_produced_the_verdicts(self):
        self.assertEqual(self.default["html_parser"], seo_common.html_parser())

    def test_choosing_the_other_parser_changes_what_the_artifact_says(self):
        """The half a hard-coded field would pass: the recording has to follow the choice,
        not merely exist."""
        self.assertEqual(self.fallback["html_parser"], "html.parser")
        self.assertNotEqual(self.fallback["html_parser"], self.default["html_parser"])

    def test_a_report_from_the_fallback_parser_says_so_on_its_face(self):
        """The recording is only diagnosable if it reaches the file a person is handed.
        `provenance_warnings` is that surface, and it had no test naming the parser."""
        sys.path.insert(0, SCRIPTS)
        from checklist_report import provenance_warnings
        warnings = provenance_warnings(self.fallback)
        self.assertTrue(any("html.parser" in w for w in warnings),
                        "a report produced by the fallback parser does not say so: %r"
                        % (warnings,))

    def test_the_default_parser_is_not_announced(self):
        """The other direction, and the reason the warning is conditional: `lxml` is what a
        normal run uses, so saying it every time would be noise a reader learns to skip —
        and a caveat everybody skips is not a caveat."""
        sys.path.insert(0, SCRIPTS)
        from checklist_report import provenance_warnings
        if self.default["html_parser"] != "lxml":
            self.skipTest("lxml is not installed here, so there is no default to be quiet "
                          "about")
        self.assertFalse(any("parser" in w.lower() for w in provenance_warnings(self.default)))

if __name__ == "__main__":
    unittest.main()
