#!/usr/bin/env python3
"""Scan pages for answer-block and featured-snippet-ready formatting.

Every structural query here is written against **document order and ownership**
rather than against sibling position and direct children, and that is not a style
preference. `html.parser` applies none of HTML's implied end tags, so the two
commonest invalidities on the web — an unclosed `<p>` and an unclosed `<li>` — give
it a document no browser would build: the paragraph swallows every heading and list
that follows it, and three list items nest three deep. `lxml` closes both. A check
written against the parser's tree therefore returned different verdicts on the same
page depending on which parser was installed — 10 against 32 before 0.15.0 rewrote
this file — and *neither* number was the one a reader would give. Both return 42 on
that markup now, and `tests/test_parser.py` asserts the agreement rather than the
old pair of numbers.

Document order and nearest-ancestor ownership are the two things both parsers agree
about, and they agree with the browser. See `_answer_after`, `_own_text` and
`_own_descendants` for the three places that matters.
"""

from __future__ import annotations

import argparse
import json
import re

from seo_common import load_source, parse_html


QUESTION_RE = re.compile(r"^(what|why|how|when|where|who|which|can|does|is|are)\b|\?$", re.I)
DEFINITION_RE = re.compile(r"\b([A-Z][A-Za-z0-9 -]{2,80})\s+(?:is|are|refers to|means)\s+.{20,220}", re.S)
HEADING_RE = re.compile(r"^h[1-6]$")

# Elements whose text is not the page's prose, skipped subtree and all. `<template>`
# and `<noscript>` are the clearest case: their contents are markup the page has not
# used, and the two parsers do not agree on whether it is markup or text.
NON_PROSE = frozenset({"script", "style", "template", "noscript", "svg"})

# What a reader sees start on its own line. Used for two questions: where one block
# ends and the next begins, and whether a candidate carries prose of its own or is
# only a wrapper around other blocks.
BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "dd", "details", "dialog", "div",
    "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "nav", "ol",
    "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "ul",
})

# The elements a direct answer may be written in. `div` is here because plenty of
# editors emit one per paragraph; `dd` because a definition list is an answer to the
# term above it.
ANSWER_TAGS = frozenset({"p", "div", "dd", "blockquote"})

# basis: convention — Google shows a paragraph snippet at roughly 40-60 words, so the
# band is that with room either side. Nothing here measured what actually gets lifted;
# the lower bound is "long enough to be an answer rather than a label".
ANSWER_MIN_WORDS = 20
ANSWER_MAX_WORDS = 70   # basis: convention — the top of the band above; above it the
#  paragraph is an introduction rather than an answer
# basis: convention — the same lower bound, and a wider top because a definition is
# allowed one sentence of context after the definition itself.
DEFINITION_MIN_WORDS = 20
DEFINITION_MAX_WORDS = 80   # basis: convention — the top of the band above, ten words
#  wider than an answer for the same reason stated there
# basis: convention — three is the shortest list a reader reads as a list instead of
# as two related sentences.
LIST_MIN_ITEMS = 3
# basis: convention — a header row and one row of data is the least that is a table.
TABLE_MIN_ROWS = 2
# basis: convention — the four signals are not equally strong and nothing here
# measured how much stronger. A direct answer weighs most because it is the only one
# of the four a snippet can be lifted from verbatim; a list weighs least because
# every navigation menu is one.
SIGNAL_POINTS = {"direct_answer": 20, "definition": 12, "list": 10, "table": 12}
# basis: convention — the score is a 0-100 readout for a report, so it saturates
# rather than rewarding a page for its twentieth list.
SCORE_MAX = 100


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def _own_text(node) -> str:
    """A node's own prose: its text with every block-level descendant's removed.

    `get_text()` folds the rest of the document into this node's word count whenever
    the markup left the node open, and an unclosed `<p>` is the commonest invalidity
    there is: under `html.parser` an 18-word paragraph that swallows the next heading
    and list measures 26. The count a reader would give is the text between this
    node's own tags, and that is what this returns — inline children (`<em>`, `<a>`,
    `<strong>`) included, because a reader counts those words too.
    """
    parts = []
    for child in node.children:
        name = getattr(child, "name", None)
        if name is None:
            parts.append(str(child))
        elif name in BLOCK_TAGS or name in NON_PROSE:
            continue                      # belongs to that block, not to this one
        else:
            parts.append(_own_text(child))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _own_descendants(node, tag: str, containers: tuple[str, ...]) -> list:
    """The `tag` elements this container owns — those whose nearest container of the
    same kind is this one.

    Not `recursive=False`: `<ul><li>a<li>b<li>c</ul>` is one item nested three deep
    to `html.parser` and three siblings to `lxml`, so counting direct children reads
    1 against 3 for a list every browser renders identically. Nearest-ancestor gives
    3 under both, and unlike a plain `find_all` it still leaves a genuinely nested
    sublist's items to the sublist.
    """
    return [el for el in node.find_all(tag)
            if el.find_parent(list(containers)) is node]


def _answer_after(heading):
    """The block that answers a question heading, found in document order.

    Not `find_next_sibling()`. A sibling walk asks the parser where the heading's
    parent ends, and that is precisely the question the parsers answer differently:
    with an unclosed `<p>` before it, `lxml` closes the paragraph per HTML's implied
    end tags and the heading becomes its sibling, while `html.parser` leaves the
    heading *inside* the paragraph, where it has no siblings at all. One parser then
    finds a list and no answer, the other an answer and no list, on one page.

    Wrappers are walked through rather than measured: a `<div>` holding the answer
    used to be read as the answer, so its word count was the whole section's and no
    page wrapping its content could have a direct answer. Stops at the next heading,
    because a section that ends without prose has no answer and the next section's
    first paragraph answers a different question.
    """
    skipping = None
    for node in heading.find_all_next():
        if skipping is not None:
            if skipping in node.parents:
                continue
            skipping = None
        name = node.name or ""
        if name in NON_PROSE:
            skipping = node
            continue
        if HEADING_RE.match(name):
            return None
        if not _own_text(node):
            continue                      # a wrapper; the prose is further in
        return node if name in ANSWER_TAGS else None
    return None


def scan_answer_blocks(source: str, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout)
    parsed = parse_html(html, url)
    soup = parsed["soup"]

    questions = []
    direct_answers = []
    for heading in soup.find_all(HEADING_RE):
        heading_text = heading.get_text(" ", strip=True)
        if not QUESTION_RE.search(heading_text):
            continue
        questions.append(heading_text)
        answer = _answer_after(heading)
        if answer is None:
            continue
        answer_text = _own_text(answer)
        words = _word_count(answer_text)
        if ANSWER_MIN_WORDS <= words <= ANSWER_MAX_WORDS:
            direct_answers.append({"question": heading_text,
                                   "answer": answer_text[:320], "word_count": words})

    definitions = []
    for paragraph in soup.find_all("p"):
        text = _own_text(paragraph)
        if DEFINITION_MIN_WORDS <= _word_count(text) <= DEFINITION_MAX_WORDS \
                and DEFINITION_RE.search(text):
            definitions.append(text[:320])

    lists = []
    for node in soup.find_all(["ol", "ul"]):
        items = [_own_text(li) for li in _own_descendants(node, "li", ("ol", "ul"))]
        if len(items) >= LIST_MIN_ITEMS:
            lists.append({"type": node.name, "items": len(items), "sample": items[:5]})

    tables = []
    for table in soup.find_all("table"):
        rows = _own_descendants(table, "tr", ("table",))
        headers = [_own_text(th) for th in _own_descendants(table, "th", ("table",))]
        if len(rows) >= TABLE_MIN_ROWS:
            tables.append({"rows": len(rows), "headers": headers[:10]})

    score = min(SCORE_MAX,
                len(direct_answers) * SIGNAL_POINTS["direct_answer"]
                + len(definitions) * SIGNAL_POINTS["definition"]
                + len(lists) * SIGNAL_POINTS["list"]
                + len(tables) * SIGNAL_POINTS["table"])
    issues = []
    if not direct_answers:
        issues.append({"severity": "info", "message": f"No {ANSWER_MIN_WORDS}-{ANSWER_MAX_WORDS} word answer paragraph immediately follows a question heading."})
    if not definitions:
        issues.append({"severity": "info", "message": "No concise definition paragraph detected."})
    if not lists and not tables:
        issues.append({"severity": "info", "message": "No snippet-friendly list or table detected."})

    return {
        "url": url or source,
        "score": score,
        "questions": questions[:50],
        "direct_answers": direct_answers[:50],
        "definitions": definitions[:50],
        "lists": lists[:50],
        "tables": tables[:50],
        "issues": issues,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan for direct answers, definitions, lists, and tables.")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = scan_answer_blocks(args.source, args.timeout)
    print(json.dumps(result, indent=2) if args.json else f"Score: {result['score']} Direct answers: {len(result['direct_answers'])}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
