"""The boundary between the page's own credits and everybody else's, 0.78.0.

`page_nodes` prunes a node whose `@id` is referenced from under a foreign-credit key.
Until 0.78.0 the set it pruned on left the subject keys out, so a cited paper, a reviewed
book and an adapted recipe hoisted into `@graph` all handed the page their authors. The
default is now the wide set, with one exemption: a node the page declares as its own
subject through `mainEntityOfPage` or `mainEntity`, anchored to this page.

Thirteen shapes, and five implementations that satisfy all thirteen and are still wrong.
**Both expected lists are written out for every shape**: given prose for seven of them, an
executor inferred an empty author list for pages that name their own author, and would
have shipped seven green tests asserting the opposite of the truth.

Every page here carries `<link rel="canonical">`, and it is load-bearing rather than
decorative: `load_source` returns an empty `base_url` for a temp file, so the canonical is
the only anchor a file-based test has. Without it no exemption can ever fire and half of
this file would pass for the wrong reason.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

PAGE = "https://example.test/p"


def _person(name):
    return {"@type": "Person", "name": name}


def _org(name):
    return {"@type": "Organization", "name": name}


def _page(document, canonical=PAGE):
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>'
            + link
            + '<script type="application/ld+json">' + json.dumps(document) +
            '</script></head><body><p>Bread rises when the yeast is warm.</p>'
            '</body></html>')


def _through(html, check):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(html)
        path = handle.name
    try:
        return check(path)
    finally:
        os.unlink(path)


def _eeat(document, canonical=PAGE):
    import eeat_signal_checker
    return _through(_page(document, canonical), eeat_signal_checker.check_eeat)


class TheHoistedSubjectIsNotThePagesOwn(unittest.TestCase):
    """Seven shapes that answered wrongly on `v0.77.0` and answer correctly now."""

    def _assert(self, document, authors, publishers):
        result = _eeat(document)
        self.assertEqual(result["signals"]["authors"], authors)
        self.assertEqual(result["signals"]["publishers"], publishers)

    def test_a_hoisted_cited_paper_is_not_the_pages_author(self):
        """`R Franklin` wrote the paper this page cites; the page names its own author."""
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "author": _person("Page Author"),
             "publisher": _org("Page Press"), "citation": {"@id": "#paper"}},
            {"@id": "#paper", "@type": "ScholarlyArticle",
             "author": _person("R Franklin"), "publisher": _org("Nature")}]},
            ["Page Author"], ["Page Press"])

    def test_a_hoisted_reviewed_book_is_not_the_pages_author(self):
        """The `itemReviewed` spelling: a review of Moby Dick is not written by Melville.

        `itemReviewed`, not `review`. `review` is a contribution key and was pruned before
        this release too, so a shape written with it proves nothing about the change.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#r", "@type": "Review", "author": _person("Critic Carla"),
             "itemReviewed": {"@id": "#b"}},
            {"@id": "#b", "@type": "Book", "name": "Moby Dick",
             "author": _person("Herman Melville"), "publisher": _org("Penguin")}]},
            ["Critic Carla"], [])

    def test_a_hoisted_is_based_on_original_is_not_the_pages_author(self):
        """The third subject key: an adapted recipe is not by the original cook."""
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#r", "@type": "Recipe", "author": _person("Page Cook"),
             "isBasedOn": {"@id": "#o"}},
            {"@id": "#o", "@type": "Recipe", "author": _person("Original Cook")}]},
            ["Page Cook"], [])

    def test_a_reviewed_products_brand_is_not_the_review_pages_publisher(self):
        """The publisher half, and the recorded decision this release reversed.

        A review site's own publisher sits on its Review node. The manufacturer of the
        thing being reviewed is not the publisher of the review, and crediting it passed
        CN-057 — *Show Author and Publisher Clearly*, a `high` item — on a page that never
        names its own publisher.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#r", "@type": "Review", "author": _person("Staff Reviewer"),
             "publisher": _org("Crumb Journal"), "itemReviewed": {"@id": "#p"}},
            {"@id": "#p", "@type": "Product", "name": "Proofing Basket",
             "brand": _org("Crumb Supply")}]},
            ["Staff Reviewer"], ["Crumb Journal"])

    def test_a_cited_work_naming_its_own_page_is_still_not_this_page(self):
        """Kills the unanchored main-entity exemption, scored 23/26 against this rule's 25.

        Fixed by the release for the ordinary reason, and written for a second one: an
        exemption protecting any node that carries `mainEntityOfPage` looks obviously
        correct and re-admits this node, whose claim names the paper's own canonical page.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "author": _person("Page Author"),
             "publisher": _org("Page Press"), "citation": {"@id": "#paper"}},
            {"@id": "#paper", "@type": "ScholarlyArticle",
             "author": _person("R Franklin"), "publisher": _org("Nature"),
             "mainEntityOfPage": "https://elsewhere.test/the-paper"}]},
            ["Page Author"], ["Page Press"])

    def test_a_cited_work_carrying_its_own_reviews_is_still_not_this_page(self):
        """Kills the mutual-link exemption, scored 21/26.

        Protecting a node that points back at whoever points at it through a contribution
        key is a rule a product page satisfies — and so does a cited paper that carries
        reviews of its own.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "author": _person("Page Author"),
             "publisher": _org("Page Press"), "citation": {"@id": "#paper"}},
            {"@id": "#paper", "@type": "ScholarlyArticle",
             "author": _person("R Franklin"), "publisher": _org("Nature"),
             "review": {"@id": "#rev"}},
            {"@id": "#rev", "@type": "Review", "itemReviewed": {"@id": "#paper"}}]},
            ["Page Author"], ["Page Press"])

    def test_a_bibliography_entry_with_its_own_review_is_still_not_this_page(self):
        """Kills the strict-ownership exemption, scored 24/26.

        That rule survives the shape above by protecting a node only when *every*
        subject-key route into it is a contribution it claims back. A further-reading entry
        emitted with its own review and never cited from the page node satisfies it too:
        `#rev` reaches `#x` through `itemReviewed`, and `#x` claims `#rev` through
        `review`. **The back-pointer on `#rev` is what makes this shape the shape** —
        without it nothing references `#x` at all, no rule prunes it, and the test proves
        nothing about any exemption.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "author": _person("Page Author"),
             "publisher": _org("Page Press")},
            {"@id": "#x", "@type": "ScholarlyArticle",
             "author": _person("R Franklin"), "publisher": _org("Nature"),
             "review": {"@id": "#rev"}},
            {"@id": "#rev", "@type": "Review", "itemReviewed": {"@id": "#x"}}]},
            ["Page Author"], ["Page Press"])


class ThePagesOwnCreditsSurvive(unittest.TestCase):
    """Five shapes that answered correctly before this release and must still."""

    _assert = TheHoistedSubjectIsNotThePagesOwn._assert

    def test_a_nested_citation_was_already_excluded_by_key(self):
        """The control for the first shape: nesting is caught by `exclude`, not hoisting."""
        self._assert({"@context": "https://schema.org", "@type": "Article",
                      "author": _person("Page Author"), "publisher": _org("Page Press"),
                      "citation": {"@type": "ScholarlyArticle",
                                   "author": _person("R Franklin"),
                                   "publisher": _org("Nature")}},
                     ["Page Author"], ["Page Press"])

    def test_a_hoisted_accepted_answer_is_still_not_the_author(self):
        """A contribution key, hoisted: pruned before this release and after it."""
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": "#f", "@type": "FAQPage", "author": _person("Page Author"),
             "mainEntity": {"@type": "Question", "acceptedAnswer": {"@id": "#a"}}},
            {"@id": "#a", "@type": "Answer", "author": _person("Answerer Ann")}]},
            ["Page Author"], [])

    def test_the_pages_own_article_named_as_its_main_entity_keeps_its_credits(self):
        """The second spelling of the exemption, read from the page node outward.

        Nothing prunes `#a` here, so this guards against an implementation that
        over-prunes rather than one that under-prunes.
        """
        self._assert({"@context": "https://schema.org", "@graph": [
            {"@id": PAGE, "@type": "WebPage", "mainEntity": {"@id": "#a"},
             "publisher": _org("Page Press")},
            {"@id": "#a", "@type": "Article", "author": _person("Page Author")}]},
            ["Page Author"], ["Page Press"])

    def test_a_single_node_document_is_untouched(self):
        """No `@graph`, no `@id`: nothing for the hoisting rule to act on at all."""
        self._assert({"@context": "https://schema.org", "@type": "Article",
                      "author": _person("Page Author"), "publisher": _org("Page Press")},
                     ["Page Author"], ["Page Press"])

    def test_a_declared_subject_keeps_its_brand_however_the_claim_is_written(self):
        """The exemption itself, and the only shape in this file that exercises it.

        This one passes before and after **for different reasons**: before, because the
        narrow default pruned nothing; after, only because `page_own_ids` re-admits `#p`.
        It is what separates this release from a plain widening of the default, and an
        implementation that widens without the exemption fails here and nowhere else.

        Four spellings, all written by real emitters. The relative form is why
        `page_own_ids` resolves a claim against the fetch URL, or against the canonical
        when — as here, and in every file-based test — there is no fetch URL.
        """
        for claim in (PAGE, {"@id": PAGE}, {"url": PAGE}, "/p"):
            with self.subTest(claim=claim):
                self._assert({"@context": "https://schema.org", "@graph": [
                    {"@id": "#p", "@type": "Product", "name": "Proofing Basket",
                     "brand": _org("Crumb Supply"), "mainEntityOfPage": claim},
                    {"@id": "#c", "@type": "Article", "citation": {"@id": "#p"}}]},
                    [], ["Crumb Supply"])


class TheCostThisReleaseShips(unittest.TestCase):
    """One shape that answered correctly before this release and no longer does."""

    def test_an_undeclared_product_page_loses_its_brand(self):
        """Knowingly shipped, and the markup is the reason.

        `{@graph: [Product{brand}, Review{itemReviewed: #p}]}` is emitted both by a product
        page carrying a customer review and by a review site reviewing somebody else's
        product. The difference is a fact about the site, not about the document, so
        neither is credited: the false fail here buys the false pass removed in
        `test_a_reviewed_products_brand_is_not_the_review_pages_publisher`. A page that
        wants the old answer declares it — see
        `test_a_declared_subject_keeps_its_brand_however_the_claim_is_written`.
        """
        result = _eeat({"@context": "https://schema.org", "@graph": [
            {"@id": "#p", "@type": "Product", "name": "Proofing Basket",
             "brand": _org("Crumb Supply"), "review": {"@id": "#r"}},
            {"@id": "#r", "@type": "Review", "author": _person("Shopper Sam"),
             "itemReviewed": {"@id": "#p"}}]})
        self.assertEqual(result["signals"]["authors"], [])
        self.assertEqual(result["signals"]["publishers"], [])


class EveryReaderOfTheBoundaryGetsTheExemption(unittest.TestCase):
    """Six implementations that satisfy every shape above and are still wrong.

    Named by a cross-check asked what wrong implementation the thirteen shapes would pass.
    Each test here is the only one that fails the implementation it names.

    The class was called *every reader* while covering three of four: 0.86.0 found
    `citation_readiness._schema_entity_signals` passing no `protected` at all, which the
    title said could not happen. The fourth test below is that reader, and it is here
    rather than beside the other citation-readiness tests because what it guards is this
    class's claim.
    """

    def test_the_exempted_nodes_author_is_read(self):
        """Forgetting the set in `page_author_names` passes all thirteen shapes.

        None of them puts an author on an exempted node, so an implementation that threads
        `protected` into the publisher path and not the author path answers them all.
        """
        result = _eeat({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "citation": {"@id": "#p"}},
            {"@id": "#p", "@type": "Product", "author": _person("Bench Tester"),
             "mainEntityOfPage": PAGE}]})
        self.assertEqual(result["signals"]["authors"], ["Bench Tester"])

    def test_the_exempted_nodes_reviewer_is_read(self):
        """The same for `reviewedBy`, which no shape above asserts either."""
        result = _eeat({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "citation": {"@id": "#p"}},
            {"@id": "#p", "@type": "Product", "reviewedBy": _person("Dr Rye"),
             "mainEntityOfPage": PAGE}]})
        self.assertEqual(result["signals"]["reviewers"], ["Dr Rye"])

    def test_the_exempted_nodes_publication_date_is_read(self):
        """And for the date, which `check_eeat` never looks at.

        `freshness_checker` reads `datePublished` through the same boundary, so forgetting
        the set at its call site drops the page's own date while every assertion in every
        other class here stays green.
        """
        import freshness_checker
        document = {"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "WebPage", "citation": {"@id": "#a"}},
            {"@id": "#a", "@type": "Article", "datePublished": "2026-08-01",
             "mainEntityOfPage": PAGE}]}
        result = _through(_page(document),
                          lambda path: freshness_checker.check_freshness(
                              path, today=date(2026, 10, 1)))
        self.assertEqual(result["latest_date"], "2026-08-01")
        self.assertIn("2026-08-01", [entry["raw"] for entry in result["dates"]
                                     if entry["source"] == "schema_published"])

    def test_the_exempted_nodes_entity_signals_are_read(self):
        """The fourth reader, and the one the class's title used to skip.

        `citation_readiness` scores up to 20 of its 100 points on `sameAs`, so a page
        whose own declared entity is claimed by an `acceptedAnswer` loses its only
        anchor when the exemption is not threaded. Measured before 0.86.0 threaded it:
        this shape returned an empty `sameAs` list.
        """
        import citation_readiness
        document = {"@context": "https://schema.org", "@graph": [
            {"@type": "FAQPage", "name": "Our FAQ",
             "mainEntity": {"@type": "Question", "name": "Who are you?",
                            "acceptedAnswer": {"@id": "#us"}}},
            {"@id": "#us", "@type": "Organization", "name": "The Publisher",
             "mainEntityOfPage": PAGE,
             "sameAs": ["https://www.wikidata.org/wiki/Q_publisher"]}]}
        result = _through(_page(document),
                          citation_readiness.check_citation_readiness)
        self.assertEqual(result["entity_signals"]["sameAs"],
                         ["https://www.wikidata.org/wiki/Q_publisher"])
        self.assertIn("The Publisher", result["entity_signals"]["names"])

    def test_a_declaring_node_nested_below_the_top_level_is_found(self):
        """A scan of the top-level `@graph` members alone passes all thirteen shapes.

        Every one of them puts the declaring node at the top level, where a shallow scan
        succeeds. This nests it inside an `Organization`'s `makesOffer`.
        """
        result = _eeat({"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": "Crumb Supply",
             "makesOffer": {"@id": "#p", "@type": "Product",
                            "brand": _org("Nested Brand"),
                            "mainEntityOfPage": PAGE}},
            {"@id": "#c", "@type": "Article", "citation": {"@id": "#p"}}]})
        self.assertIn("Nested Brand", result["signals"]["publishers"])

    def test_an_empty_base_url_is_not_an_anchor(self):
        """`normalize_url("")` is `'https:///'`, and so is `normalize_url("/", "")`.

        A temp file has no `base_url`. An implementation that normalises it into the anchor
        set rather than dropping it protects any node whose claim is `"/"` — a wrong
        exemption, and a false pass. The page below carries a canonical, so the anchor set
        is not empty; only an unfiltered empty `base_url` could match this claim.
        """
        result = _eeat({"@context": "https://schema.org", "@graph": [
            {"@id": "#page", "@type": "Article", "author": _person("Page Author"),
             "citation": {"@id": "#x"}},
            {"@id": "#x", "@type": "ScholarlyArticle",
             "author": _person("R Franklin"), "mainEntityOfPage": "/"}]})
        self.assertEqual(result["signals"]["authors"], ["Page Author"])


if __name__ == "__main__":
    unittest.main()
