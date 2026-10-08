#!/usr/bin/env python3
"""
Article SEO Optimizer & Keyword Researcher

Fetches an article, detects the CMS (Blogger, WordPress, Ghost, generic),
extracts structured content, performs keyword research, and collects
readability, JSON-LD, and meta signals for LLM-driven SEO analysis.

Supported platforms:
  - Blogger / Blogspot  (itemprop=articleBody, class=post-body)
  - WordPress            (class=entry-content, class=post-content)
  - Ghost               (class=post-content, class=gh-content)
  - Generic / fallback  (<article>, <main>, or all <p> tags)

Usage:
    python article_seo.py https://example.com/article
    python article_seo.py https://example.com/article --keyword "red team ops"
    python article_seo.py https://example.com/article --json
"""

import argparse
import json
import re
import sys
import urllib.parse
from collections import Counter

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from lib.safe_http import safe_get
    from seo_common import (THIN_CONTENT_WORDS, declared_publication_dates,
                            fetch_html, page_author_names, parse_html,
                            primary_language)
except ImportError:
    from scripts.lib.safe_http import safe_get
    from scripts.seo_common import (THIN_CONTENT_WORDS,
                                    declared_publication_dates, fetch_html,
                                    page_author_names, parse_html,
                                    primary_language)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Most thresholds in this file are `inherited`: article_seo.py arrived from
# Agentic-SEO-Skill and those numbers were not decided here. The three Flesch Reading
# Ease boundaries are the exception. Naming the rest does not calibrate them — it makes
# them arguable, which is the step that was missing while they were literals scattered
# through 600 lines.

# basis: inherited — 8 words, present at import. Filters navigation entries and captions
#  out of the paragraph list so readability is measured on prose.
MIN_PARAGRAPH_WORDS = 8
# basis: inherited — present at import, and part of the Flesch syllable estimate rather
#  than a verdict: a word of three letters or fewer is counted as one syllable.
SHORT_WORD_LETTERS = 3
# basis: standard — 70 is a Flesch Reading Ease boundary; Flesch, R. (1948), "A new
#  readability yardstick", Journal of Applied Psychology, 32(3), 221-233. Flesch's table
#  has seven bands and this file has three, so the grouping and the audience wording are
#  this tool's own; only the boundary is his.
READABILITY_EASY = 70
# basis: standard — 50 is a Flesch Reading Ease boundary, same source as READABILITY_EASY
#  above: Flesch, R. (1948), Journal of Applied Psychology, 32(3), 221-233. The band it
#  opens is Flesch's "fairly difficult"; calling it medium is this tool's wording.
READABILITY_MEDIUM = 50
# basis: standard — 30 is a Flesch Reading Ease boundary, same source as READABILITY_EASY
#  above: Flesch, R. (1948), Journal of Applied Psychology, 32(3), 221-233. Below it is
#  Flesch's bottom band; reporting that as "very difficult to read" is this tool's wording.
READABILITY_HARD = 30
# basis: inherited — a unigram has to appear more than three times to be a keyword
#  candidate, present at import.
MIN_UNIGRAM_COUNT = 3
# basis: convention — a pixel truncation budget establishes no minimum: 30 characters
#  is retained as this project's editorial judgement that a shorter title is unlikely
#  to identify the page adequately, without pretending font metrics prove that claim.
TITLE_MIN_CHARS = 30
# basis: measured — corpus=tools/calibration/serp-length.json; date=2026-08-10; method=ordinary composition in Arial using frequency-weighted glyph advances at 20px fitted to the assumed 600px desktop budget. The 65-character capacity is exact only for the declared average mix: Arial's measured ASCII-letter advances vary 4.25x, so capitals can truncate sooner and narrow lowercase text can leave room.
TITLE_MAX_CHARS = 65
# basis: convention — a pixel truncation budget establishes no minimum: 100 characters
#  is retained as this project's editorial judgement that a shorter description may
#  undersell the page, not as a result measured from glyph widths.
META_MIN_CHARS = 100
# basis: measured — corpus=tools/calibration/serp-length.json; date=2026-08-10; method=ordinary composition in Arial using frequency-weighted glyph advances at 14px fitted to the assumed 920px desktop budget. The budget is a third-party observation, not a Google-published limit — if it is wrong, 144 is wrong.
META_MAX_CHARS = 144
# basis: inherited — 1000 words, present at import: the "may be thin for a blog post"
#  line, itself below the 1500 the fix text asks for.
BLOG_THIN_WORDS = 1000
# basis: inherited — more than three images without loading="lazy", present at import.
MAX_EAGER_IMAGES = 3
# basis: inherited — five related keywords, present at import. A padding target for the
#  keyword list, not a verdict about the page.
MIN_RELATED_KEYWORDS = 5

# Curated per-language lists, selected from the page's declared `<html lang>`.
# Add a new language here and to no shared/global union: applying every language's
# function words to every page can remove a real content word in another language.
STOP_WORDS = {
    "en": {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "with", "by", "of", "from", "as", "is", "are", "was", "were", "be",
        "been", "this", "that", "these", "those", "it", "he", "she", "they",
        "we", "you", "i", "your", "my", "their", "our", "its", "which", "who",
        "whom", "whose", "what", "where", "when", "why", "how", "all", "any",
        "both", "each", "few", "more", "most", "other", "some", "such", "no",
        "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can",
        "will", "just", "should", "have", "has", "had", "do", "does", "did",
        "get", "got", "make", "use", "used", "also", "about", "into",
        "then", "there", "would", "could", "here",
    },
    "lt": {
        "aš", "apie", "ant", "ar", "arba", "be", "bei", "bet", "bus", "buvo",
        "būti", "čia", "dar", "dėl", "gali", "galima", "ir", "iš", "jei", "jis",
        "ji", "jo", "jos", "jų", "juos", "jas", "jam", "jai", "jiems", "joms",
        "jūs", "jus", "jums", "kaip", "kad", "kas", "kada", "kiek", "kitą",
        "kitų", "kur", "kuri", "kurie", "kurio", "labai", "man", "manęs", "mes",
        "mus", "mums", "mūsų", "ne", "nei", "nes", "nuo", "o", "pas", "per",
        "po", "prie", "prieš", "sau", "savęs", "savo", "su", "šį", "ši", "šis",
        "šią", "šie", "šios", "šių", "tačiau", "tai", "taip", "tas", "tavo",
        "tavęs", "ten", "tik", "tiktai", "tu", "turi", "tą", "tų", "tuo", "už",
        "va", "viena", "vienas", "vis", "visa", "visi", "yra",
    },
    "ru": {
        "а", "без", "более", "больше", "будет", "будто", "бы", "был", "была",
        "были", "было", "быть", "в", "вам", "вас", "ведь", "весь", "во", "вот",
        "впрочем", "все", "всегда", "всего", "всех", "всю", "вы", "где", "да",
        "даже", "для", "до", "другой", "его", "ее", "ей", "ему", "если", "есть",
        "еще", "её", "ж", "же", "за", "зачем", "здесь", "и", "из", "или", "им",
        "иногда", "их", "к", "как", "какая", "какой", "когда", "конечно", "куда",
        "ли", "лучше", "между", "меня", "мне", "много", "может", "мой", "моя",
        "мы", "на", "над", "надо", "нас", "не", "него", "нее", "ней", "нельзя",
        "нет", "ни", "нибудь", "никогда", "ним", "них", "ничего", "но", "ну", "о",
        "об", "один", "он", "она", "они", "опять", "от", "перед", "по", "под",
        "после", "потом", "потому", "почти", "при", "про", "раз", "разве", "с",
        "сам", "свою", "себе", "себя", "сейчас", "сказать", "со", "совсем", "так",
        "такой", "там", "тебя", "тем", "теперь", "то", "тогда", "того", "тоже",
        "только", "том", "тот", "три", "тут", "ты", "у", "уж", "уже", "хорошо",
        "хоть", "чего", "чем", "через", "что", "чтобы", "чуть", "этой", "этом",
        "этот", "эти", "этого", "эту", "я",
    },
}

# Deprecated / restricted schema types (as of Feb 2026)
DEPRECATED_SCHEMA = {
    "HowTo", "SpecialAnnouncement", "CourseInfo", "EstimatedSalary",
    "LearningVideo", "ClaimReview", "VehicleListing", "PracticeProblems",
}
RESTRICTED_SCHEMA = {"FAQPage"}  # government / healthcare only


# ---------------------------------------------------------------------------
# CMS detection
# ---------------------------------------------------------------------------

def detect_cms(soup: BeautifulSoup, url: str) -> str:
    """Detect the publishing platform from HTML signals."""
    # Blogger: generator meta OR blogspot.com in URL
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator:
        gen_val = generator.get("content", "").lower()
        if "blogger" in gen_val:
            return "blogger"
        if "wordpress" in gen_val:
            return "wordpress"
        if "ghost" in gen_val:
            return "ghost"

    if "blogspot.com" in url or soup.find(attrs={"data-blog-id": True}):
        return "blogger"

    if soup.find("body", class_=re.compile(r"wp-")):
        return "wordpress"
    if soup.find(attrs={"class": re.compile(r"gh-content|ghost-")}):
        return "ghost"

    # WordPress theme signals
    if soup.find("link", attrs={"rel": "https://api.w.org/"}):
        return "wordpress"

    return "generic"


# ---------------------------------------------------------------------------
# Content extraction (CMS-aware)
# ---------------------------------------------------------------------------

def extract_content(parsed: dict, cms: str) -> dict:
    """
    Extract structured content from the parsed page.

    Returns a dict with:
      title, meta_description, og_description, h1, h2s, h3s,
      paragraphs, images, labels, publish_date, authors, publication_dates
    """
    soup = parsed["soup"]
    publication_dates = declared_publication_dates(parsed)
    result = {
        "title": "",
        "meta_description": "",
        "og_description": "",
        "h1": [],
        "h2s": [],
        "h3s": [],
        "paragraphs": [],
        "images": [],
        "labels": [],
        "publish_date": publication_dates[0] if publication_dates else "",
        "authors": page_author_names(parsed),
        "publication_dates": publication_dates,
    }

    # ── Meta tags (common for all CMSes) ──────────────────────────────────
    title_tag = soup.find("title")
    if title_tag:
        result["title"] = title_tag.get_text(strip=True)

    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag:
        result["meta_description"] = desc_tag.get("content", "")

    og_desc = soup.find("meta", property="og:description")
    if not og_desc:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc:
        result["og_description"] = og_desc.get("content", "")

    # ── CMS-specific body containers ───────────────────────────────────────
    # Every block the template names, not the first of them: read first-only, a
    # listing was its first card (`openspec/specs/evidence/` EVD-11).
    containers = []

    if cms == "blogger":
        # Primary: itemprop=articleBody. Fallback: Blogger classic template
        containers = (
            soup.find_all(attrs={"itemprop": "articleBody"})
            or soup.find_all(attrs={"class": re.compile(r"post-body|entry-content", re.I)})
        )
        # Labels (Blogger categories)
        for label_a in soup.find_all("a", attrs={"class": re.compile(r"label-link|goog-label", re.I)}):
            label_text = label_a.get_text(strip=True)
            if label_text:
                result["labels"].append(label_text)
        # Post title override (Blogger uses h3.post-title in some templates)
        post_title = soup.find(attrs={"class": re.compile(r"post-title|entry-title", re.I)})
        if post_title and not result["title"]:
            result["title"] = post_title.get_text(strip=True)

    elif cms == "wordpress":
        containers = soup.find_all(
            attrs={"class": re.compile(r"entry-content|post-content|article-content", re.I)})
        # WP categories/tags
        for cat in soup.find_all(attrs={"class": re.compile(r"cat-links|tags-links|post-categories", re.I)}):
            for a in cat.find_all("a"):
                t = a.get_text(strip=True)
                if t:
                    result["labels"].append(t)

    elif cms == "ghost":
        containers = soup.find_all(
            attrs={"class": re.compile(r"gh-content|post-content|article-content", re.I)})

    # A named block inside another is part of the outer one, and is read once.
    named = {id(c) for c in containers}
    containers = [c for c in containers if not any(id(p) in named for p in c.parents)]

    if not containers:
        # No template, or one that names nothing on this page — which until 0.152.0
        # was read whole, footer and all.
        # `<main>` before `<article>`: an article is part of the body copy, not the
        # whole of it. Read first, it dropped copy that follows it inside `<main>` and
        # made a listing its first card (`openspec/specs/evidence/` EVD-11).
        containers = [
            soup.find("main")
            or soup.find("article")
            or soup.find(attrs={"id": re.compile(r"content|main|article", re.I)})
            or soup.find(attrs={"class": re.compile(r"content|article|post|entry", re.I)})
            or soup
        ]

    for scope in containers:
        # ── Headings ──────────────────────────────────────────────────────
        for tag, key in (("h1", "h1"), ("h2", "h2s"), ("h3", "h3s")):
            result[key] += [h.get_text(strip=True) for h in scope.find_all(tag)
                            if h.get_text(strip=True)]

        # ── Paragraphs ────────────────────────────────────────────────────
        for p in scope.find_all("p"):
            text = p.get_text(" ", strip=True)
            if len(text.split()) > MIN_PARAGRAPH_WORDS:  # skip tiny fragments
                result["paragraphs"].append(text)

        # ── Images ────────────────────────────────────────────────────────
        for img in scope.find_all("img"):
            result["images"].append({
                "src": img.get("src", img.get("data-src", "")),
                "alt": img.get("alt", ""),
                "width": img.get("width", ""),
                "height": img.get("height", ""),
                "loading": img.get("loading", ""),
            })

    return result


# ---------------------------------------------------------------------------
# JSON-LD structured data extraction
# ---------------------------------------------------------------------------

def extract_structured_data(soup: BeautifulSoup) -> list:
    """
    Extract and parse all <script type="application/ld+json"> blocks.
    Flags deprecated / restricted types.
    """
    blocks = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            blocks.append({"error": "invalid_json", "raw_snippet": raw[:120]})
            continue

        nodes = _flatten_jsonld(data)
        if not nodes:
            blocks.append({"error": "no_schema_nodes", "raw_snippet": raw[:120]})
            continue
        blocks.extend(_describe_schema_node(node) for node in nodes)

    return blocks


def _flatten_jsonld(data) -> list:
    """Return the schema nodes inside one JSON-LD block.

    A block is legally a single node, an array of nodes, or a @graph container.
    Assuming a dict crashed on every site shipping the array form — WordPress
    with Yoast among them.
    """
    nodes = []
    for node in (data if isinstance(data, list) else [data]):
        if not isinstance(node, dict):
            continue
        graph = node.get("@graph")
        if isinstance(graph, list):
            nodes.extend(n for n in graph if isinstance(n, dict))
        else:
            nodes.append(node)
    return nodes


def _describe_schema_node(data: dict) -> dict:
    """Classify one JSON-LD node against the deprecated / restricted lists."""
    schema_type = data.get("@type", "Unknown")
    if isinstance(schema_type, list):
        # Multi-typed nodes ("@type": ["Person", "Organization"]) are legal.
        schema_type = schema_type[0] if schema_type else "Unknown"

    status = "active"
    note = ""
    if schema_type in DEPRECATED_SCHEMA:
        status = "deprecated"
        note = f"{schema_type} was deprecated/removed from rich results. Remove or replace."
    elif schema_type in RESTRICTED_SCHEMA:
        status = "restricted"
        note = f"{schema_type} is restricted to government/healthcare authority sites only."

    return {
        "@type": schema_type,
        "@context": data.get("@context", ""),
        "status": status,
        "note": note,
        "has_context": bool(data.get("@context")),
        "has_type": bool(data.get("@type")),
        "raw": data,
    }


# ---------------------------------------------------------------------------
# Readability scoring (Flesch-Kincaid)
# ---------------------------------------------------------------------------

def _count_syllables(word: str) -> int:
    """Approximate syllable count for a word."""
    word = word.lower().strip(".,!?;:")
    if len(word) <= SHORT_WORD_LETTERS:
        return 1
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e"):
        count -= 1
    return max(1, count)


def compute_readability(text: str) -> dict:
    """
    Compute Flesch Reading Ease and Flesch-Kincaid Grade Level.

    Flesch Reading Ease: 206.835 - 1.015*(words/sentences) - 84.6*(syllables/words)
    FK Grade Level:       0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    """
    if not text.strip():
        return {"flesch_reading_ease": None, "fkgl": None, "grade_label": "N/A"}

    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = max(1, len(sentences))

    words = re.findall(r"\b[a-zA-Z'-]+\b", text)
    word_count = max(1, len(words))

    syllable_count = sum(_count_syllables(w) for w in words)

    avg_sentence_len = word_count / sentence_count
    avg_syllables_per_word = syllable_count / word_count

    fre = 206.835 - 1.015 * avg_sentence_len - 84.6 * avg_syllables_per_word
    fkgl = 0.39 * avg_sentence_len + 11.8 * avg_syllables_per_word - 15.59

    fre = round(max(0, min(100, fre)), 1)
    fkgl = round(max(0, fkgl), 1)

    if fre >= READABILITY_EASY:
        grade_label = "Easy (suitable for general audience)"
    elif fre >= READABILITY_MEDIUM:
        grade_label = "Medium (suitable for high school / college)"
    else:
        grade_label = "Difficult (technical / specialist audience)"

    return {
        "flesch_reading_ease": fre,
        "fkgl": fkgl,
        "grade_label": grade_label,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_len, 1),
        "avg_syllables_per_word": round(avg_syllables_per_word, 2),
    }


# ---------------------------------------------------------------------------
# Keyword extraction (frequency-weighted n-grams — honest naming)
# ---------------------------------------------------------------------------

def page_language(soup: BeautifulSoup) -> str:
    """Return the primary declared language, without guessing from the URL/text."""
    html = soup.find("html")
    return primary_language({"lang": html.get("lang") if html else None}) or ""


def extract_keywords_frequency(text: str, top_n: int = 12, lang: str = "") -> list:
    """
    Extract high-frequency unigrams, bigrams, and trigrams as keyword candidates.
    Uses frequency counting (not TF-IDF — no corpus reference available).
    Favors multi-word phrases over single terms.
    """
    # Python's Unicode word class keeps Lithuanian diacritics and Cyrillic letters.
    # A declared unsupported language gets no guessed list; missing `lang` retains
    # the historical English fallback for callers that pass plain text directly.
    words = re.findall(r"[^\W\d_]{3,}", text.lower(), re.UNICODE)
    stop_words = STOP_WORDS.get(lang, set()) if lang else STOP_WORDS["en"]
    filtered = [w for w in words if w not in stop_words]

    unigrams = Counter(filtered)
    bigrams = Counter(
        f"{words[i]} {words[i+1]}"
        for i in range(len(words) - 1)
        if words[i] not in stop_words and words[i + 1] not in stop_words
    )
    trigrams = Counter(
        f"{words[i]} {words[i+1]} {words[i+2]}"
        for i in range(len(words) - 2)
        if all(word not in stop_words for word in words[i:i + 3])
    )

    scored: list[tuple[str, float]] = []
    for term, cnt in unigrams.items():
        if cnt > MIN_UNIGRAM_COUNT:
            scored.append((term, float(cnt)))
    for term, cnt in bigrams.items():
        if cnt > 1:
            scored.append((term, cnt * 3.0))
    for term, cnt in trigrams.items():
        if cnt > 1:
            scored.append((term, cnt * 5.0))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Deduplicate: if a shorter term is a substring of a longer one, prefer longer
    final: list[str] = []
    all_terms = [t for t, _ in scored]
    for term, _ in scored:
        if not any(term in other and term != other for other in all_terms[:top_n * 3]):
            final.append(term)
        if len(final) >= top_n:
            break

    return final


# ---------------------------------------------------------------------------
# Google Autocomplete (related keyword suggestions)
# ---------------------------------------------------------------------------

def get_google_autocomplete(query: str) -> list:
    """Fetch Google Autocomplete suggestions (free, no API key required)."""
    try:
        url = (
            "https://suggestqueries.google.com/complete/search"
            f"?client=chrome&q={urllib.parse.quote(query)}"
        )
        data = safe_get(url, timeout=6).json()
        if len(data) >= 2 and isinstance(data[1], list):
            return data[1]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# SEO issue detection
# ---------------------------------------------------------------------------

def detect_seo_issues(content: dict, structured_data: list, readability: dict) -> list:
    """
    Lightweight rule-based SEO issue flags for the article.
    Returns list of {severity, finding, fix} dicts.
    """
    issues = []

    title = content.get("title", "")
    meta = content.get("meta_description", "")
    h1s = content.get("h1", [])
    word_count = readability.get("word_count", 0)
    images = content.get("images", [])

    # Title checks
    if not title:
        issues.append({"severity": "Critical", "area": "Title", "finding": "No <title> tag found.", "fix": "Add a descriptive title tag (30-65 characters)."})
    elif len(title) < TITLE_MIN_CHARS:
        issues.append({"severity": "Warning", "area": "Title", "finding": f"Title too short ({len(title)} chars).", "fix": "Expand title to at least 30 characters with the primary keyword near the start."})
    elif len(title) > TITLE_MAX_CHARS:
        issues.append({"severity": "Warning", "area": "Title", "finding": f"Title may be truncated in SERPs ({len(title)} chars).", "fix": "Keep title at or below 65 characters."})

    # Meta description
    if not meta:
        issues.append({"severity": "Warning", "area": "Meta Description", "finding": "No meta description found.", "fix": "Add a compelling 100-144 character meta description with a CTA."})
    elif len(meta) < META_MIN_CHARS:
        issues.append({"severity": "Warning", "area": "Meta Description", "finding": f"Meta description too short ({len(meta)} chars).", "fix": "Expand to at least 100 characters."})
    elif len(meta) > META_MAX_CHARS:
        issues.append({"severity": "Warning", "area": "Meta Description", "finding": f"Meta description may be truncated ({len(meta)} chars).", "fix": "Keep at or below 144 characters."})

    # H1
    if not h1s:
        issues.append({"severity": "Critical", "area": "H1", "finding": "No H1 tag detected.", "fix": "Add a single, descriptive H1 containing the primary keyword."})
    elif len(h1s) > 1:
        issues.append({"severity": "Warning", "area": "H1", "finding": f"Multiple H1 tags found ({len(h1s)}).", "fix": "Use exactly one H1 per page."})

    # Word count (blog post minimum = 1,500)
    if word_count < THIN_CONTENT_WORDS:
        issues.append({"severity": "Critical", "area": "Content", "finding": f"Very thin content ({word_count} words).", "fix": "Expand content to at least 1,500 words for blog posts."})
    elif word_count < BLOG_THIN_WORDS:
        issues.append({"severity": "Warning", "area": "Content", "finding": f"Content may be thin for a blog post ({word_count} words).", "fix": "Aim for 1,500+ words of substantive, unique content."})

    # Author attribution (E-E-A-T)
    if not content.get("authors"):
        issues.append({"severity": "Warning", "area": "E-E-A-T", "finding": "No author attribution detected.", "fix": "Add a visible author byline with credentials. Critical post-Dec 2025 E-E-A-T update."})

    # Publish date
    if not content.get("publish_date"):
        issues.append({"severity": "Info", "area": "Freshness", "finding": "No publish date detected in markup.", "fix": "Add visible publish/update date and datePublished in Article schema."})
    distinct_publication_dates = list(dict.fromkeys(content.get("publication_dates", [])))
    if len(distinct_publication_dates) > 1:
        issues.append({
            "severity": "Warning",
            "area": "Freshness",
            "finding": f"Conflicting publication dates declared: {', '.join(distinct_publication_dates)}.",
            "fix": "Align publication dates across JSON-LD, meta, and microdata declarations.",
        })

    # Images: alt text
    missing_alt = [img for img in images if not img.get("alt")]
    if missing_alt:
        issues.append({"severity": "Warning", "area": "Images", "finding": f"{len(missing_alt)} image(s) missing alt text.", "fix": "Add descriptive alt text (10-125 chars) to all non-decorative images."})

    # Images: lazy loading
    no_lazy = [img for img in images if img.get("loading") != "lazy" and img.get("src")]
    if len(no_lazy) > MAX_EAGER_IMAGES:
        issues.append({"severity": "Info", "area": "Images", "finding": f"{len(no_lazy)} image(s) without loading='lazy'.", "fix": "Add loading='lazy' to below-the-fold images to improve LCP."})

    # Structured data
    if not structured_data:
        issues.append({"severity": "Warning", "area": "Schema", "finding": "No JSON-LD structured data found.", "fix": "Add Article/BlogPosting schema with author, datePublished, image, and publisher."})
    else:
        for sd in structured_data:
            if sd.get("status") == "deprecated":
                issues.append({"severity": "Critical", "area": "Schema", "finding": sd["note"], "fix": "Remove deprecated schema type immediately."})
            elif sd.get("status") == "restricted":
                issues.append({"severity": "Warning", "area": "Schema", "finding": sd["note"], "fix": "Remove FAQPage schema unless you are a government or healthcare authority site."})

    # Readability
    fre = readability.get("flesch_reading_ease")
    if fre is not None and fre < READABILITY_HARD:
        issues.append({"severity": "Info", "area": "Readability", "finding": f"Content is very difficult to read (Flesch score: {fre}).", "fix": "Simplify sentences. Aim for Flesch score ≥ 50 for broader audience reach."})

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Article SEO Extractor & Keyword Researcher (BS4 + Blogger/WP/Ghost support)"
    )
    parser.add_argument("url", help="URL of the article to analyze")
    parser.add_argument("--keyword", help="Target primary keyword (optional — extracted automatically if omitted)")
    parser.add_argument("--json", action="store_true", help="Output full JSON result")
    parser.add_argument("--no-autocomplete", action="store_true", help="Skip Google Autocomplete lookup")
    args = parser.parse_args()

    html = fetch_html(args.url, timeout=15)[0]
    if not html:
        out = {"error": "Failed to fetch URL", "url": args.url}
        print(json.dumps(out) if args.json else f"Error: Failed to fetch {args.url}")
        sys.exit(1)

    parsed = parse_html(html, args.url)
    soup = parsed["soup"]

    # ── CMS detection ──────────────────────────────────────────────────────
    cms = detect_cms(soup, args.url)

    # ── Content extraction ─────────────────────────────────────────────────
    content = extract_content(parsed, cms)

    # ── Structured data ────────────────────────────────────────────────────
    structured_data = extract_structured_data(soup)

    # ── Full text for keyword extraction + readability ─────────────────────
    all_text_parts = content["h1"] + content["h2s"] + content["h3s"] + content["paragraphs"]
    full_text = " ".join(all_text_parts)

    # ── Readability ────────────────────────────────────────────────────────
    readability = compute_readability(full_text)

    # ── Keyword research ───────────────────────────────────────────────────
    extracted_kws = extract_keywords_frequency(full_text, lang=page_language(soup))
    target_kw = (args.keyword.lower() if args.keyword else "") or (extracted_kws[0] if extracted_kws else "")

    keyword_usage = None
    if args.keyword is not None:
        # Match case-insensitively at word boundaries: "seo" must not match
        # "seoul". `full_text` is the body corpus already assembled above for
        # keyword extraction; using it here avoids inventing a second definition.
        keyword_pattern = (re.compile(rf"(?<!\w){re.escape(args.keyword)}(?!\w)",
                                      re.IGNORECASE)
                           if args.keyword else None)
        body_occurrences = (len(keyword_pattern.findall(full_text))
                            if keyword_pattern else 0)
        keyword_usage = {
            "keyword": args.keyword,
            "in_body": body_occurrences > 0,
            "body_occurrences": body_occurrences,
            "in_title": bool(keyword_pattern.search(content["title"]))
                        if keyword_pattern else False,
        }

    related_kws: list[str] = []
    if target_kw and not args.no_autocomplete:
        related_kws = get_google_autocomplete(target_kw)
        # Remove exact match
        related_kws = [k for k in related_kws if k.lower() != target_kw.lower()]

    # Pad with extracted keywords if autocomplete returned few results
    if len(related_kws) < MIN_RELATED_KEYWORDS:
        extras = [k for k in extracted_kws if k not in related_kws and k != target_kw]
        related_kws.extend(extras)

    # ── SEO issue detection ─────────────────────────────────────────────────
    seo_issues = detect_seo_issues(content, structured_data, readability)

    # ── Build result ───────────────────────────────────────────────────────
    result = {
        "url": args.url,
        "cms_detected": cms,
        "title": content["title"],
        "meta_description": content["meta_description"],
        "og_description": content["og_description"],
        "authors": content["authors"],
        "publish_date": content["publish_date"],
        "labels": content["labels"],
        "headings": {
            "h1": content["h1"],
            "h2": content["h2s"],
            "h3": content["h3s"],
        },
        "paragraphs": content["paragraphs"],
        "images": content["images"],
        "structured_data": structured_data,
        "readability": readability,
        "extracted_keywords": extracted_kws,
        "related_keywords": related_kws[:15],
        "seo_issues": seo_issues,
    }
    # Missing is the output contract for "could not determine one": the registry
    # reads absence as NO_DATA. An empty string used to turn uncertainty into FAIL.
    if target_kw:
        result["target_keyword"] = target_kw
    # Absence means no keyword was supplied, so no usage measurement happened.
    if keyword_usage is not None:
        result["keyword_usage"] = keyword_usage

    if args.json:
        print(json.dumps(result, indent=2))
        return

    # ── Human-readable output ──────────────────────────────────────────────
    issues_by_sev = {"Critical": [], "Warning": [], "Info": []}
    for issue in seo_issues:
        issues_by_sev.get(issue["severity"], issues_by_sev["Info"]).append(issue)

    print(f"\nArticle SEO Analysis — {args.url}")
    print("=" * 60)
    print(f"CMS Detected      : {cms.capitalize()}")
    print(f"Title             : {result['title'][:80]}")
    print(f"Meta Description  : {result['meta_description'][:100]}")
    print(f"Authors           : {', '.join(result['authors']) or '⚠️ Not detected'}")
    print(f"Publish Date      : {result['publish_date'] or 'Not detected'}")
    print(f"Labels/Categories : {', '.join(result['labels']) or 'None'}")
    print(f"\nHeadings → H1: {len(content['h1'])}  H2: {len(content['h2s'])}  H3: {len(content['h3s'])}")
    print(f"Word Count        : {readability.get('word_count', 0):,} words")
    print(f"Sentences         : {readability.get('sentence_count', 0)}")
    print(f"Images            : {len(content['images'])}")

    fre = readability.get('flesch_reading_ease')
    fkgl = readability.get('fkgl')
    print("\nReadability")
    print(f"  Flesch Reading Ease : {fre}  ({readability.get('grade_label', '')})")
    print(f"  FK Grade Level      : {fkgl}")

    print(f"\nStructured Data ({len(structured_data)} block(s))")
    for sd in structured_data:
        flag = "✅" if sd.get("status") == "active" else "🔴" if sd.get("status") == "deprecated" else "⚠️"
        print(f"  {flag} @type: {sd.get('@type', 'Unknown')}  ({sd.get('status', 'unknown')})")
        if sd.get("note"):
            print(f"     → {sd['note']}")

    print(f"\nTarget Keyword    : '{target_kw}'")
    print(f"Related Keywords  : {', '.join(result['related_keywords'][:8])}")

    print(f"\nSEO Issues Found: {len(seo_issues)}")
    for sev, label in [("Critical", "🔴"), ("Warning", "⚠️"), ("Info", "ℹ️")]:
        for iss in issues_by_sev[sev]:
            print(f"  {label} [{iss['area']}] {iss['finding']}")
            print(f"       Fix: {iss['fix']}")

    print("\nNote: Use --json flag to pipe full output into an LLM for deeper analysis.")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
