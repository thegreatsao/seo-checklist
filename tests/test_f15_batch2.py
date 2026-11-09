"""F15 batch 2: the defects F03's second reading found in `rendered_audit.py` (and the
`SKILL.md` snippet that produces its input), `pagespeed.py`, `image_inventory.py` and
`image_weight_audit.py`, as the owner ruled them (docs/sprint-20261109-F15.md).

Each verdict is the item's real rule from the registry over the script's real output.
The snippet is JavaScript run in a browser; `RenderedSnippet` runs the copy in
`SKILL.md` under Node against a small stand-in DOM, so what is tested is the text an
operator pastes. The `measures` rows are held by `MeasuresSentences`.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import image_inventory  # noqa: E402
import image_weight_audit  # noqa: E402
import pagespeed  # noqa: E402
import rendered_audit  # noqa: E402
import seo_common  # noqa: E402
from test_evidence import verdict  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, WARN  # noqa: E402

ITEMS = {item["id"]: item for item in harness.registry()["items"]}
NODE = shutil.which("node")


def snippet() -> str:
    """The rendered-page snippet exactly as `SKILL.md` prints it."""
    with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as handle:
        text = handle.read()
    blocks = re.findall(r"```js\n(.*?)```", text, re.S)
    found = [b for b in blocks if "text_nodes_below_contrast" in b]
    assert len(found) == 1, "SKILL.md carries one rendered-page snippet"
    return found[0]


# A stand-in for the few DOM calls the snippet makes. Computed colour, font size and
# weight inherit as they do in a browser; every other style takes the initial value.
FAKE_DOM = r"""
const spec = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const INITIAL = {display: 'block', visibility: 'visible', opacity: '1',
  position: 'static', backgroundColor: 'rgba(0, 0, 0, 0)', backgroundImage: 'none',
  textDecorationLine: 'none'};
const INHERITED = {color: 'rgb(0, 0, 0)', fontSize: '16px', fontWeight: '400'};
const all = [];
function build(node, parent) {
  const style = Object.assign({}, INITIAL, node.style || {});
  for (const k of Object.keys(INHERITED))
    if (!(node.style || {})[k]) style[k] = parent ? parent._style[k] : INHERITED[k];
  const el = {nodeType: 1, tagName: node.tag.toUpperCase(), parentElement: parent,
              attrs: node.attrs || {}, _style: style, childNodes: []};
  if (parent) all.push(el);
  for (const kid of node.kids || []) {
    if (typeof kid === 'string') el.childNodes.push({nodeType: 3, textContent: kid});
    else el.childNodes.push(build(kid, el));
  }
  const r = node.rect || [200, 20, 0, 0];
  el.getBoundingClientRect = () => ({width: r[0], height: r[1], left: r[2], top: r[3],
                                     right: r[2] + r[0], bottom: r[3] + r[1]});
  Object.defineProperty(el, 'textContent',
    {get() { return el.childNodes.map(n => n.textContent).join(''); }});
  el.scrollWidth = el.clientWidth = r[0];
  el.scrollHeight = el.clientHeight = r[1];
  el.getAttribute = n => (n in el.attrs ? el.attrs[n] : null);
  el.hasAttribute = n => n in el.attrs;
  return el;
}
function simple(el, token) {
  const m = token.match(/^([a-z0-9*]*)(?:\[([a-z-]+)(?:=([^\]]+))?\])?$/);
  if (!m) throw new Error('selector not understood: ' + token);
  if (m[1] && m[1] !== '*' && el.tagName.toLowerCase() !== m[1]) return false;
  if (m[2] && !(m[2] in el.attrs)) return false;
  if (m[3] !== undefined && el.attrs[m[2]] !== m[3]) return false;
  return true;
}
function matches(el, selector) {
  return selector.split(',').some(part => {
    const tokens = part.trim().split(/\s+/);
    if (!simple(el, tokens[tokens.length - 1])) return false;
    if (tokens.length === 1) return true;
    for (let n = el.parentElement; n; n = n.parentElement)
      if (simple(n, tokens[0])) return true;
    return false;
  });
}
const body = build({tag: 'body', kids: spec.body, style: spec.bodyStyle}, null);
global.innerWidth = 390; global.innerHeight = 844;
global.location = {href: 'http://example.test/'};
global.getComputedStyle = el => el._style;
global.document = {
  body,
  documentElement: {scrollWidth: 390, outerHTML: '<html></html>'},
  querySelectorAll: selector => all.filter(el => matches(el, selector)),
};
const result = eval(require('fs').readFileSync(process.argv[2], 'utf8'));
delete result.html;
process.stdout.write(JSON.stringify(result));
"""


@unittest.skipUnless(NODE, "node is not installed")
class RenderedSnippet(unittest.TestCase):
    """CN-036 and CN-035: the snippet's contrast and link measures."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.dom = os.path.join(cls.dir, "dom.js")
        cls.code = os.path.join(cls.dir, "snippet.js")
        with open(cls.dom, "w", encoding="utf-8") as handle:
            handle.write(FAKE_DOM)
        with open(cls.code, "w", encoding="utf-8") as handle:
            handle.write(snippet())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def measure(self, body, body_style=None):
        proc = subprocess.run(
            [shutil.which("node"), self.dom, self.code], input=json.dumps(
                {"body": body, "bodyStyle": body_style or {}}),
            capture_output=True, encoding="utf-8", timeout=60, close_fds=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def read(self, measured):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump(measured, handle)
        try:
            return rendered_audit.read(handle.name)
        finally:
            os.unlink(handle.name)

    def test_text_over_a_background_image_is_not_measured_and_withholds_the_pass(self):
        """Batch 3: dark text on a dark background image was scored against white."""
        out = self.measure([{"tag": "div", "style": {
            "backgroundImage": 'url("dark.jpg")'}, "kids": [
                {"tag": "p", "style": {"color": "rgb(20, 20, 20)"},
                 "kids": ["Words on a picture"]}]}])
        self.assertEqual(out["text_nodes_below_contrast"], 0)
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 1)
        self.assertEqual(verdict("CN-036", self.read(out)), NO_DATA)

    def test_a_gradient_is_a_background_image(self):
        out = self.measure([{"tag": "p", "style": {
            "backgroundImage": "linear-gradient(black, white)"},
            "kids": ["Words on a gradient"]}])
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 1)

    def test_a_background_image_behind_an_opaque_colour_is_hidden_by_it(self):
        out = self.measure([{"tag": "div", "style": {
            "backgroundImage": 'url("dark.jpg")'}, "kids": [
                {"tag": "p", "style": {"backgroundColor": "rgb(255, 255, 255)"},
                 "kids": ["Words on a white card"]}]}])
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 0)
        self.assertEqual(verdict("CN-036", self.read(out)), PASS)

    def test_a_faint_foreground_is_composited(self):
        """`rgba(0,0,0,0.3)` on white is about 2:1, not 21:1."""
        out = self.measure([{"tag": "p", "style": {"color": "rgba(0, 0, 0, 0.3)"},
                             "kids": ["Faint words"]}])
        self.assertEqual(out["text_nodes_below_contrast"], 1)
        self.assertEqual(verdict("CN-036", self.read(out)), FAIL)

    def test_a_faint_background_is_composited_over_what_is_behind_it(self):
        """White text on a 10% black wash over white is white on near-white."""
        out = self.measure([{"tag": "p", "style": {
            "color": "rgb(255, 255, 255)", "backgroundColor": "rgba(0, 0, 0, 0.1)"},
            "kids": ["Pale words"]}])
        self.assertEqual(out["text_nodes_below_contrast"], 1)

    def test_a_colour_outside_rgb_is_unmeasured_not_misread(self):
        """Review round 1: Chrome keeps oklch(), color() and lab() in computed style,
        and their first three numbers are not RGB. Tailwind's gray-300 on white
        passed CN-036, and a gray-900 text with a blue-600 link failed CN-035."""
        for colour in ("oklch(0.872 0.01 258.338)", "color(srgb 0.85 0.85 0.85)"):
            with self.subTest(colour=colour):
                out = self.measure([{"tag": "p", "style": {"color": colour},
                                     "kids": ["Faint gray words"]}])
                self.assertEqual(out["text_nodes_contrast_unmeasured"], 1)
                self.assertEqual(verdict("CN-036", self.read(out)), NO_DATA)
        out = self.measure([{"tag": "p", "kids": ["Words on a tinted card"],
                             "style": {"backgroundColor": "oklch(0.2 0.03 264)"}}])
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 1)
        out = self.measure([{"tag": "p", "style": {"color": "oklch(0.21 0.034 264.665)"},
                             "kids": ["Read ", {"tag": "a", "attrs": {"href": "/x"},
                                                "style": {"color": "oklch(0.546 0.245 262.881)"},
                                                "kids": ["the guide"]}, " first."]}])
        self.assertEqual(out["links_indistinct"], 0)
        self.assertEqual(out["links_contrast_unmeasured"], 1)
        self.assertEqual(verdict("CN-035", self.read(out)), NO_DATA)

    def test_a_link_in_its_texts_own_colour_is_indistinct_whatever_the_space(self):
        """Review round 3: Tailwind's preflight gives links `color: inherit` and no
        underline; in oklch the zero was a pass."""
        colour = "oklch(0.21 0.034 264.665)"
        out = self.measure([{"tag": "p", "style": {"color": colour}, "kids": [
            "Read ", {"tag": "a", "attrs": {"href": "/x"}, "style": {"color": colour},
                      "kids": ["the guide"]}, " first."]}])
        self.assertEqual(out["links_indistinct"], 1)
        self.assertEqual(verdict("CN-035", self.read(out)), FAIL)

    def test_a_link_with_its_own_background_is_distinct(self):
        """Review round 3: a button-styled link is told apart by its background."""
        for style in ({"backgroundColor": "rgb(255, 212, 0)"},
                      {"backgroundImage": "linear-gradient(red, blue)"}):
            with self.subTest(style=style):
                out = self.measure(self.link("rgb(51, 51, 51)", **style))
                self.assertEqual(out["links_indistinct"], 0)

    def test_a_transparent_fill_is_unmeasured_not_a_failure(self):
        """Review round 5: outlined text (`color: transparent` with a stroke) was 1:1."""
        out = self.measure([{"tag": "h2", "style": {"color": "rgba(0, 0, 0, 0)"},
                             "kids": ["Outlined heading"]}])
        self.assertEqual(out["text_nodes_below_contrast"], 0)
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 1)

    def test_ordinary_dark_text_on_white_passes(self):
        out = self.measure([{"tag": "p", "kids": ["Plain words"]}])
        self.assertEqual(out["text_nodes_below_contrast"], 0)
        self.assertEqual(out["text_nodes_contrast_unmeasured"], 0)
        self.assertEqual(verdict("CN-036", self.read(out)), PASS)

    def link(self, colour, parent="div", **style):
        return [{"tag": parent, "style": {"color": "rgb(51, 51, 51)"}, "kids": [
            "Read ", {"tag": "a", "attrs": {"href": "/x"},
                      "style": dict({"color": colour}, **style), "kids": ["the guide"]},
            " first."]}]

    def test_a_link_in_a_div_is_looked_at(self):
        """Batch 3: only `p a, li a, td a, article a` were scanned."""
        out = self.measure(self.link("rgb(51, 51, 51)"))
        self.assertEqual(out["links_indistinct"], 1)

    def test_a_link_one_shade_off_its_text_is_indistinct(self):
        """Batch 3: `#333334` in `#333333` text passed on exact colour inequality."""
        out = self.measure(self.link("rgb(51, 51, 52)", parent="p"))
        self.assertEqual(out["links_indistinct"], 1)

    def test_a_link_three_to_one_from_its_text_is_distinct(self):
        out = self.measure(self.link("rgb(255, 255, 255)", parent="p"))
        self.assertEqual(out["links_indistinct"], 0)

    def test_an_underlined_or_bolder_link_is_distinct(self):
        for style in ({"textDecorationLine": "underline"}, {"fontWeight": "700"}):
            with self.subTest(style=style):
                out = self.measure(self.link("rgb(51, 51, 51)", parent="p", **style))
                self.assertEqual(out["links_indistinct"], 0)

    def test_a_link_with_no_text_around_it_is_not_in_running_text(self):
        out = self.measure([{"tag": "li", "kids": [
            {"tag": "a", "attrs": {"href": "/x"}, "kids": ["Menu entry"]}]}])
        self.assertEqual(out["links_indistinct"], 0)


class RenderedFiles(unittest.TestCase):
    """CN-036 over `rendered_audit.read`: a zero is a pass only when nothing went
    unmeasured, and a file from the old snippet never says so."""

    def read(self, **counts):
        data = {"url": "https://example.test/", "viewport": {"width": 390}}
        data.update(counts)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump(data, handle)
        try:
            return rendered_audit.read(handle.name)
        finally:
            os.unlink(handle.name)

    def test_a_zero_beside_unmeasured_text_is_no_data(self):
        out = self.read(text_nodes_below_contrast=0, text_nodes_contrast_unmeasured=2)
        self.assertNotIn("text_nodes_below_contrast", out)
        self.assertEqual(verdict("CN-036", out), NO_DATA)

    def test_a_zero_from_the_old_snippet_is_no_data(self):
        out = self.read(text_nodes_below_contrast=0, links_indistinct=0)
        self.assertEqual(verdict("CN-036", out), NO_DATA)
        self.assertEqual(verdict("CN-035", out), NO_DATA)

    def test_a_withheld_link_count_gives_the_link_reason(self):
        out = self.read(links_indistinct=0, links_contrast_unmeasured=2)
        reason = next(m for m in out["missing"] if m.startswith("links_indistinct"))
        self.assertNotIn("background image", reason)

    def test_each_withheld_zero_names_its_unmeasured_count(self):
        self.assertEqual(rendered_audit.WITHHELD_BESIDE, {
            "text_nodes_below_contrast": "text_nodes_contrast_unmeasured",
            "links_indistinct": "links_contrast_unmeasured"})
        out = self.read(links_indistinct=0, links_contrast_unmeasured=2)
        self.assertEqual(verdict("CN-035", out), NO_DATA)
        out = self.read(links_indistinct=1, links_contrast_unmeasured=2)
        self.assertEqual(verdict("CN-035", out), FAIL)
        out = self.read(links_indistinct=0, links_contrast_unmeasured=0)
        self.assertEqual(verdict("CN-035", out), PASS)

    def test_a_failure_stands_whatever_went_unmeasured(self):
        out = self.read(text_nodes_below_contrast=3, text_nodes_contrast_unmeasured=2)
        self.assertEqual(verdict("CN-036", out), FAIL)

    def test_a_zero_with_nothing_unmeasured_passes(self):
        out = self.read(text_nodes_below_contrast=0, text_nodes_contrast_unmeasured=0)
        self.assertEqual(verdict("CN-036", out), PASS)


def psi(field=None, lab=None):
    """A PageSpeed v5 response: CrUX percentiles by our label, lab values by audit."""
    names = {label: name for name, label in pagespeed.PSI_METRIC_MAP.items()}
    categories = {"good": "FAST", "needs-improvement": "AVERAGE", "poor": "SLOW"}
    data = {"lighthouseResult": {"categories": {"performance": {"score": 0.9}},
                                 "audits": {}}}
    if field:
        data["loadingExperience"] = {"metrics": {
            names[label]: {"percentile": 1, "category": categories[rating]}
            for label, rating in field.items()}}
    for audit_id, value in (lab or {}).items():
        data["lighthouseResult"]["audits"][audit_id] = {"numericValue": value}
    return pagespeed.parse_pagespeed_response(data, "https://example.test/")


class AboveTheFold(unittest.TestCase):
    """SP-107: FCP alone is not the above-the-fold content. Both paints come from one
    source — CrUX when it has the page, Lighthouse when it has nothing — because the
    report names lab numbers only on a page with no field data (INP-5)."""

    def test_crux_without_fcp_is_not_completed_from_the_lab(self):
        out = psi(field={"LCP": "good", "CLS": "good"},
                  lab={"first-contentful-paint": 900})
        self.assertNotIn("FCP", out["above_fold"])
        self.assertEqual(out["above_fold"]["LCP"]["source"], "field")
        self.assertEqual(verdict("SP-107", out), NO_DATA)

    def test_field_paints_decide_with_field_data(self):
        out = psi(field={"FCP": "good", "LCP": "good", "CLS": "good"},
                  lab={"first-contentful-paint": 9000})
        self.assertEqual(out["above_fold"]["FCP"]["source"], "field")
        self.assertEqual(verdict("SP-107", out), PASS)

    def test_a_slow_largest_paint_fails_a_fast_first_paint(self):
        out = psi(field={"FCP": "good", "LCP": "poor", "CLS": "good"})
        self.assertEqual(verdict("SP-107", out), FAIL)
        out = psi(field={"FCP": "good", "LCP": "needs-improvement", "CLS": "good"})
        self.assertEqual(verdict("SP-107", out), WARN)

    def test_lab_only_reads_both_paints(self):
        out = psi(lab={"first-contentful-paint": 900,
                       "largest-contentful-paint": 5000})
        self.assertEqual(out["above_fold"]["rating"], "poor")
        self.assertEqual(verdict("SP-107", out), FAIL)

    def test_one_good_paint_alone_is_no_pass(self):
        out = psi(field={"FCP": "good", "CLS": "good"})
        self.assertEqual(verdict("SP-107", out), NO_DATA)

    def test_one_slow_paint_alone_is_a_failure(self):
        out = psi(field={"FCP": "poor", "CLS": "good"})
        self.assertEqual(verdict("SP-107", out), FAIL)


class CoreWebVitalsCoverage(unittest.TestCase):
    """SP-108, SP-113 (batch 3): a pass over the metrics CrUX publishes stands without
    INP, as Google's own assessment does, but never without LCP or CLS."""

    def test_no_pass_with_lcp_or_cls_absent(self):
        for field in ({"CLS": "good", "INP": "good"}, {"LCP": "good", "INP": "good"},
                      {"LCP": "good"}):
            out = psi(field=field)
            for item_id in ("SP-108", "SP-113"):
                with self.subTest(field=field, item=item_id):
                    self.assertEqual(verdict(item_id, out), NO_DATA)

    def test_lcp_and_cls_are_what_a_pass_needs(self):
        self.assertEqual(pagespeed.FIELD_PASS_NEEDS, ("LCP", "CLS"))
        self.assertTrue(set(pagespeed.FIELD_PASS_NEEDS) <= set(pagespeed.CORE_WEB_VITALS))

    def test_a_pass_without_inp_stands(self):
        out = psi(field={"LCP": "good", "CLS": "good"})
        for item_id in ("SP-108", "SP-113"):
            self.assertEqual(verdict(item_id, out), PASS)

    def test_a_failure_stands_with_a_metric_absent(self):
        out = psi(field={"LCP": "poor"})
        for item_id in ("SP-108", "SP-113"):
            self.assertEqual(verdict(item_id, out), FAIL)


def inventory(body):
    html = ('<!doctype html><html lang="en"><head><title>Images</title></head>'
            f"<body>{body}</body></html>")
    return harness.through_html(html, image_inventory.inventory)


OK_IMAGE = '<img src="/ok.jpg" alt="A loaf on the counter" width="40" height="40">'


class EmptyAltWhereTheImageCarriesMeaning(unittest.TestCase):
    """CI-016 and MD-186: `alt=""` is right on a decorative image and wrong on one a
    reader needs — the only content of a link, or a large image in the content."""

    def assert_both(self, out, expected):
        for item_id in ("CI-016", "MD-186"):
            self.assertEqual(verdict(item_id, out), expected, item_id)

    def test_an_empty_alt_on_a_links_only_content_fails(self):
        self.assert_both(inventory('<a href="/"><img src="/logo.png" alt=""></a>'), FAIL)

    def test_a_links_only_image_fails_however_it_is_marked(self):
        """Review round 1: `role=presentation` or `aria-hidden` on the link's only
        image leaves the link with no name all the same."""
        for marks in ('role="presentation"', 'role="none"', 'aria-hidden="true"'):
            with self.subTest(marks=marks):
                self.assert_both(inventory(
                    f'<a href="/"><img src="/logo.png" alt="" {marks}></a>'), FAIL)

    def test_a_link_named_by_an_inner_label_passes(self):
        self.assert_both(inventory(
            '<a href="/"><svg aria-label="Home"></svg><img src="/l.png" alt=""></a>'),
            PASS)

    def test_a_link_named_otherwise_passes(self):
        for link in ('<a href="/" aria-label="Home"><img src="/l.png" alt=""></a>',
                     '<a href="/">Home <img src="/l.png" alt=""></a>',
                     '<a href="/"><img src="/l.png" alt=""><img src="/m.png" alt="Home"></a>'):
            with self.subTest(link=link):
                self.assert_both(inventory(link), PASS)

    def test_a_large_in_content_image_with_an_empty_alt_fails(self):
        out = inventory('<main><img src="/hero.jpg" alt="" width="800" height="500"></main>')
        self.assertEqual(out["alt_not_meaningful"], 1)
        self.assert_both(out, FAIL)

    def test_a_thin_rule_or_a_small_picture_is_not_large(self):
        """Review round 1: 100x100 of area flagged a 1200x12 divider and an avatar
        beside its name."""
        for img in ('<img src="/rule.png" alt="" width="1200" height="12">',
                    '<img src="/avatar.jpg" alt="" width="100" height="100">'):
            with self.subTest(img=img):
                self.assert_both(inventory(f"<main><p>Text</p>{img}</main>" + OK_IMAGE),
                                 PASS)
        side = seo_common.MEANINGFUL_IMAGE_MIN_PX
        self.assert_both(inventory(f'<main><img src="/x.jpg" alt="" width="{side}" '
                                   f'height="{side}"></main>'), FAIL)

    def test_an_articles_own_header_or_footer_is_content(self):
        """Review round 2: inside article/aside/main/nav/section a header or footer is
        no landmark (HTML-AAM); the featured image there is content."""
        for wrapper in ("header", "footer"):
            with self.subTest(wrapper=wrapper):
                out = inventory(f'<main><article><{wrapper}><h1>Title</h1><img src="/h.jpg" '
                                f'width="1200" height="600" alt=""></{wrapper}>'
                                '<p>Body.</p></article></main>')
                self.assert_both(out, FAIL)

    def test_a_header_inside_any_content_section_is_content(self):
        self.assertEqual(set(seo_common._SECTIONING),
                         {"article", "aside", "main", "nav", "section"})
        for section in ("article", "main", "section"):
            with self.subTest(section=section):
                out = inventory(f'<{section}><header><img src="/h.jpg" width="1200" '
                                f'height="600" alt=""></header></{section}>')
                self.assert_both(out, FAIL)

    def test_a_header_inside_an_aria_section_is_content(self):
        for role in ("main", "article", "region"):
            self.assertIn(role, seo_common._SECTIONING_ROLES)
            with self.subTest(role=role):
                out = inventory(f'<div role="{role}"><header><img src="/h.jpg" '
                                'width="1200" height="600" alt=""></header></div>')
                self.assert_both(out, FAIL)

    def test_an_image_under_a_hidden_ancestor_carries_nothing(self):
        """Review round 5: a hero background in an aria-hidden wrapper, or `hidden`."""
        for body in ('<main><div aria-hidden="true"><img src="/bg.jpg" alt="" width="1920" '
                     'height="1080"></div><p>Hello</p></main>',
                     '<main><img src="/bg.jpg" alt="" width="1920" height="1080" hidden></main>',
                     '<div aria-hidden="true"><a href="/"><img src="/l.png" alt=""></a></div>'):
            with self.subTest(body=body):
                self.assert_both(inventory(body + OK_IMAGE), PASS)

    def test_a_link_hidden_from_assistive_technology_needs_no_name(self):
        """Review round 2: WordPress's post thumbnail beside a titled link."""
        out = inventory('<article><a href="/post" aria-hidden="true" tabindex="-1">'
                        '<img src="/t.jpg" alt=""></a><h2><a href="/post">Post title</a>'
                        '</h2></article>')
        self.assert_both(out, PASS)

    def test_an_aria_landmark_is_furniture_too(self):
        for role in seo_common._FURNITURE_ROLES:
            with self.subTest(role=role):
                out = inventory(f'<div role="{role}"><img src="/x.jpg" alt="" '
                                f'width="800" height="500"></div>' + OK_IMAGE)
                self.assert_both(out, PASS)

    def test_every_furniture_landmark_holds_decoration(self):
        self.assertEqual(set(seo_common._FURNITURE), {"header", "footer", "nav", "aside"})
        for landmark in seo_common._FURNITURE:
            with self.subTest(landmark=landmark):
                out = inventory(f'<{landmark}><img src="/x.jpg" alt="" width="800" '
                                f'height="500"></{landmark}>' + OK_IMAGE)
                self.assert_both(out, PASS)

    def test_decorative_images_still_pass(self):
        for body in ('<main><img src="/rule.png" alt="" width="20" height="20"></main>',
                     '<main><img src="/x.jpg" alt="" width="800" height="500" '
                     'role="presentation"></main>',
                     '<main><img src="/x.jpg" alt="" width="800" height="500" '
                     'aria-hidden="true"></main>',
                     '<header><img src="/x.jpg" alt="" width="800" height="500"></header>',
                     '<main><img src="/x.jpg" alt=""></main>'):
            with self.subTest(body=body):
                self.assert_both(inventory(body + OK_IMAGE), PASS)


class EveryImageSourceIsAnImage(unittest.TestCase):
    """MD-184 and CN-054: `srcset`, `<picture>` and `data-srcset`-only images were
    dropped by the empty-`src` guard."""

    def test_a_srcset_only_image_is_an_image(self):
        out = inventory('<img srcset="/a-480.jpg 480w, /a-960.jpg 960w" alt="A loaf">')
        self.assertEqual(out["summary"]["images"], 1)
        self.assertEqual(verdict("MD-184", out), PASS)

    def test_a_picture_with_only_sources_is_an_image(self):
        out = inventory('<picture><source srcset="/a.webp"><img alt="A loaf"></picture>')
        self.assertEqual(verdict("MD-184", out), PASS)

    def test_a_data_srcset_only_image_is_undiscoverable(self):
        out = inventory(OK_IMAGE + '<img data-srcset="/a.jpg 1x" alt="A loaf">')
        self.assertEqual(out["summary"]["lazy_lcp_candidates"], 1)
        self.assertEqual(verdict("CN-054", out), FAIL)

    def test_a_data_uri_placeholder_is_no_native_source(self):
        """Review round 1: lazysizes' 1x1 GIF beside `data-src` is no fallback."""
        out = inventory(OK_IMAGE + '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                        'data-src="/real.jpg" class="lazyload" alt="A loaf">')
        self.assertEqual(out["summary"]["lazy_lcp_candidates"], 1)
        self.assertEqual(verdict("CN-054", out), FAIL)
        out = inventory('<img src="data:image/png;base64,AAAA" alt="An inline mark">')
        self.assertEqual(out["summary"]["lazy_lcp_candidates"], 0)

    def test_a_data_uri_srcset_placeholder_is_no_native_source(self):
        out = inventory(OK_IMAGE + '<img srcset="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                        'data-srcset="/real.jpg 800w" alt="A loaf">')
        self.assertEqual(out["summary"]["lazy_lcp_candidates"], 1)

    def test_an_unparseable_srcset_is_skipped_not_a_crash(self):
        out = inventory('<img srcset="http://[::1 1x" alt="A loaf">')
        self.assertEqual(out["skipped_no_src"], 1)

    def test_an_image_with_no_source_at_all_is_still_skipped(self):
        out = inventory('<img alt="nothing">')
        self.assertEqual(out["skipped_no_src"], 1)
        self.assertEqual(verdict("MD-184", out), FAIL)


def weigh(body, width=3000, content_type="image/png"):
    """`image_weight_audit.audit` over local markup, every image `width` pixels wide."""
    head = {"status": 200, "headers": {"content-type": content_type,
                                       "content-length": "90000"}}
    html = ('<!doctype html><html lang="en"><head><title>Images</title></head>'
            f"<body>{body}</body></html>")
    with mock.patch.object(image_weight_audit, "_check_image",
                           lambda url, timeout, sizes=None: ("fine", head, None)), \
            mock.patch.object(image_weight_audit, "_intrinsic_size",
                              lambda *a, **k: (("png", width, 100), 90000)):
        return harness.through_html(
            html, lambda path: image_weight_audit.audit(path, fetch_images=True))


ABS = "https://img.example.test"


class ResponsiveMeansWidths(unittest.TestCase):
    """MB-096 and MD-189: a format-only `<source>` or a density srcset sends the same
    3000 px file to a phone."""

    def test_a_format_only_source_is_not_responsive(self):
        out = weigh(f'<picture><source type="image/webp" srcset="{ABS}/a.webp">'
                    f'<img src="{ABS}/a.png" alt="w"></picture>')
        self.assertEqual(verdict("MB-096", out), FAIL)

    def test_a_density_srcset_is_not_responsive(self):
        out = weigh(f'<img src="{ABS}/a.png" srcset="{ABS}/a.png 1x, {ABS}/b.png 2x" '
                    'alt="w">')
        self.assertEqual(verdict("MB-096", out), FAIL)

    def test_width_descriptors_or_a_media_source_are_responsive(self):
        for body in (f'<img src="{ABS}/a.webp" srcset="{ABS}/s.webp 800w, '
                     f'{ABS}/a.webp 3000w" sizes="100vw" alt="w">',
                     f'<picture><source media="(max-width: 600px)" '
                     f'srcset="{ABS}/s.webp"><img src="{ABS}/a.webp" alt="w"></picture>'):
            with self.subTest(body=body):
                self.assertEqual(verdict("MB-096", weigh(body)), PASS)

    def test_a_media_source_that_is_not_about_width_is_not_responsive(self):
        """Review round 1: a dark-mode or `all` source sends a phone the same file."""
        for media in ("(prefers-color-scheme: dark)", "all", "print"):
            with self.subTest(media=media):
                out = weigh(f'<picture><source media="{media}" srcset="{ABS}/d.webp">'
                            f'<img src="{ABS}/a.webp" alt="w"></picture>')
                self.assertEqual(verdict("MB-096", out), FAIL)
                self.assertEqual(verdict("MD-189", out), FAIL)
        out = weigh(f'<picture><source media="(max-width: 600px)" srcset="{ABS}/s.webp">'
                    f'<img src="{ABS}/a.webp" alt="w"></picture>')
        self.assertEqual(verdict("MB-096", out), PASS)

    def test_a_desktop_or_print_source_is_not_what_a_phone_gets(self):
        """Review round 4: a phone matches no `min-width` or `print` source, so it
        loads the next candidate — the 3000 px fallback here."""
        for media in ("(min-width: 1024px)", "print", "(width >= 1024px)",
                      "(1024px <= width)"):
            with self.subTest(media=media):
                out = weigh(f'<picture><source media="{media}" srcset="{ABS}/a.webp">'
                            f'<img src="{ABS}/a.webp" alt="w"></picture>')
                self.assertEqual(verdict("MB-096", out), FAIL)
                out = weigh(f'<picture><source media="{media}" srcset="{ABS}/p.webp">'
                            f'<img src="{ABS}/a.webp" srcset="{ABS}/s.webp 800w, '
                            f'{ABS}/a.webp 3000w" sizes="100vw" alt="w"></picture>')
                self.assertEqual(verdict("MB-096", out), PASS)

    def test_tab_separated_width_descriptors_are_read(self):
        self.assertTrue(image_weight_audit._responsive(
            {"srcset": "a.jpg\t800w, b.jpg\t1600w"}, []))

    def test_a_format_only_source_wins_over_the_imgs_widths(self):
        """Review round 3: the first source a phone can match is what it gets; the
        img's width candidates are never used behind a format-only source."""
        out = weigh(f'<picture><source type="image/webp" srcset="{ABS}/h.webp">'
                    f'<img src="{ABS}/h.jpg" srcset="{ABS}/h-800.jpg 800w, {ABS}/h.jpg 3000w" '
                    'sizes="100vw" alt="w"></picture>')
        self.assertEqual(verdict("MB-096", out), FAIL)
        self.assertEqual(verdict("MD-189", out), FAIL)
        out = weigh(f'<picture><source media="(max-width: 600px)" srcset="{ABS}/s.webp">'
                    f'<source type="image/webp" srcset="{ABS}/h.webp"><img src="{ABS}/h.jpg" '
                    'alt="w"></picture>')
        self.assertEqual(verdict("MB-096", out), PASS)

    def test_md_189_asserts_both_halves(self):
        responsive_png = (f'<img src="{ABS}/a.png" srcset="{ABS}/s.png 800w, '
                          f'{ABS}/a.png 3000w" sizes="100vw" alt="w">')
        self.assertEqual(verdict("MD-189", weigh(responsive_png)), FAIL)
        responsive_webp = responsive_png.replace(".png", ".webp")
        self.assertEqual(verdict("MD-189", weigh(responsive_webp)), PASS)
        self.assertEqual(verdict("MD-189", weigh(f'<img src="{ABS}/a.webp" alt="w">')),
                         FAIL)


class OptimizeImagesAgreesWithTheFormatItem(unittest.TestCase):
    """MD-185: a large legacy-format image failed MB-097 and passed MD-185, whose
    finding for it was `info`."""

    def test_a_large_png_passes_neither(self):
        """A `warning`, as the over-250 KB finding beside it is: MD-185 warns where
        MB-097 fails, the grade it already gave a heavy image."""
        out = weigh(f'<img src="{ABS}/a.png" srcset="{ABS}/s.png 800w, '
                    f'{ABS}/a.png 3000w" sizes="100vw" alt="w" width="3000" height="100">')
        self.assertEqual(verdict("MB-097", out), FAIL)
        self.assertEqual(verdict("MD-185", out), WARN)

    def test_a_small_png_passes_both(self):
        out = weigh(f'<img src="{ABS}/a.png" alt="w" width="40" height="40">', width=40)
        self.assertEqual(verdict("MB-097", out), PASS)
        self.assertEqual(verdict("MD-185", out), PASS)


class AnImageIsAnImageType(unittest.TestCase):
    """MD-187: a 204 or a JSON body is not an image; an `image/*` type is required,
    and a type that says nothing is settled by the file's first bytes."""

    URL = "https://example.test/photo.png"

    def classify(self, head, sniffed=None):
        with mock.patch.object(image_weight_audit, "_intrinsic_size",
                               return_value=(sniffed, None)) as sniff:
            state, _confirmation = image_weight_audit._classify_image(self.URL, head, 3)
        return state, sniff

    def test_a_204_is_broken(self):
        state, _ = self.classify({"status": 204, "headers": {}})
        self.assertEqual(state, "broken")

    def test_a_declared_type_that_is_not_an_image_is_broken(self):
        for ctype in ("application/json", "text/html", "application/pdf"):
            with self.subTest(ctype=ctype):
                state, sniff = self.classify({"status": 200,
                                              "headers": {"content-type": ctype}})
                self.assertEqual(state, "broken")
                sniff.assert_not_called()

    def test_an_image_type_is_fine_unread(self):
        state, sniff = self.classify({"status": 200,
                                      "headers": {"content-type": "IMAGE/PNG; q=1"}})
        self.assertEqual(state, "fine")
        sniff.assert_not_called()

    def test_a_ranged_confirmation_length_is_not_the_files(self):
        """Review round 2: `Range: bytes=0-0` answers 206 with length 1, which is not
        the file's size and must not ask for the whole file as if it were tiny."""
        confirmation = {"status": 206, "headers": {"content-length": "1",
                                                   "content-type": "application/octet-stream"}}
        with mock.patch.object(image_weight_audit, "fetch_url", return_value=confirmation), \
                mock.patch.object(image_weight_audit, "_intrinsic_size",
                                  return_value=(("png", 1, 1), None)) as sniff:
            image_weight_audit._classify_image(self.URL, {"status": 403, "headers": {}}, 3)
        self.assertIsNone(sniff.call_args.args[2])

    def test_a_silent_type_is_read(self):
        self.assertEqual(image_weight_audit.UNTYPED,
                         ("", "application/octet-stream", "binary/octet-stream"))
        # Review round 1: S3's default for an upload with no type is
        # `binary/octet-stream`, and browsers render it.
        for headers in ({"content-type": "application/octet-stream"}, {},
                        {"content-type": "binary/octet-stream"}):
            with self.subTest(headers=headers):
                state, _ = self.classify({"status": 200, "headers": headers},
                                         sniffed=("png", 10, 10))
                self.assertEqual(state, "fine")
                state, _ = self.classify({"status": 200, "headers": headers})
                self.assertEqual(state, "unchecked")


class MeasuresSentences(unittest.TestCase):
    """The `measures` rulings, and the sentences the fix rulings also asked for."""

    SAYS = {
        "CN-034": "12px",
        "CN-051": "quarter of the viewport",
        "MB-094": "quarter of the viewport",
        "MB-108": "ancestor",
        "MB-103": "48px",
        "CN-035": "3:1",
        "CN-036": "<img> behind",
        "CI-016": "describes",
        "MD-186": "describes",
        "CN-054": "data-srcset",
        "MB-097": "250 KB",
        "MB-096": "a phone",
        "MD-189": "a phone",
        "MB-098": "density",
        "SP-107": "LCP",
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, word in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(word, ITEMS[item_id].get("measures", ""))


if __name__ == "__main__":
    unittest.main()
