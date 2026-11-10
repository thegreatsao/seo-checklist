#!/usr/bin/env python3
"""Check VideoObject JSON-LD for video rich-result readiness."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from schema_required_props import (extract_schema_documents, find_schema_nodes,
                                   missing_rich_result_props)
from seo_common import read_source, as_list, html_parser, issue, print_json_or_text


ISO_DURATION_RE = re.compile(r"^P(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# Hosts whose embed URL is a video player. A page carrying one shows a video, whatever
# its markup says (F15, MD-190's ruling: a video with no VideoObject fails).
PLAYER_HOSTS = ("youtube.com", "youtube-nocookie.com", "player.vimeo.com",
                "fast.wistia.net", "fast.wistia.com", "dailymotion.com", "player.twitch.tv")
# On the hosts that serve other frames too (a subscribe button, a channel page), the path
# a video embed takes.
PLAYER_PATHS = {"youtube.com": "/embed/", "youtube-nocookie.com": "/embed/",
                "dailymotion.com": "/embed/"}


def page_videos(html: str, base_url: str = "") -> list[str]:
    """The videos a visitor is shown: a `<video>` with a source, unless it is a muted
    autoplaying or looping background with no controls, and an `<iframe>` or `<embed>`
    from a video player. Each as its source URL."""
    if not html:
        return []
    soup = BeautifulSoup(html, html_parser())
    found = []
    for video in soup.find_all("video"):
        source = video.get("src") or next(
            (tag.get("src") for tag in video.find_all("source") if tag.get("src")), "")
        background = (not video.has_attr("controls") and video.has_attr("muted")
                      and (video.has_attr("autoplay") or video.has_attr("loop")))
        if source and not background:
            found.append(urljoin(base_url, source))
    for frame in soup.find_all(["iframe", "embed"]):
        src = urljoin(base_url, frame.get("src") or "")
        parsed = urlparse(src)
        host = (parsed.hostname or "").lower()
        player = next((p for p in PLAYER_HOSTS if host == p or host.endswith("." + p)), None)
        if player and parsed.path.startswith(PLAYER_PATHS.get(player, "/")):
            found.append(src)
    return found


def check_video_schema(documents: list[Any], html: str = "", base_url: str = "") -> dict[str, Any]:
    rows = []
    issues = []
    videos = find_schema_nodes(documents, "VideoObject")
    shown = page_videos(html, base_url)
    if shown and not videos:
        issues.append(issue("error", "The page shows a video but declares no VideoObject",
                            evidence=shown[0]))
    for row in videos:
        node = row["node"]
        row_issues = []
        # Google's required properties, read by value (`missing_rich_result_props`,
        # the table TE-172 reads); `description` is recommended and warns (F15 aside:
        # this errored on recommended properties).
        for prop in missing_rich_result_props("VideoObject", node, row["path"]):
            row_issues.append(issue("error", f"VideoObject is missing {prop}", evidence=row["path"]))
        if not node.get("description"):
            row_issues.append(issue("warning", "VideoObject is missing description", evidence=row["path"]))
        if node.get("uploadDate") and not DATE_RE.match(str(node["uploadDate"])):
            row_issues.append(issue("warning", "uploadDate should be ISO-like YYYY-MM-DD or datetime", evidence=row["path"]))
        if node.get("duration") and not ISO_DURATION_RE.match(str(node["duration"])):
            row_issues.append(issue("warning", "duration should be ISO 8601, e.g. PT2M30S", evidence=row["path"]))
        if not node.get("contentUrl") and not node.get("embedUrl"):
            row_issues.append(issue("warning", "VideoObject needs contentUrl or embedUrl", evidence=row["path"]))
        if not node.get("publisher"):
            row_issues.append(issue("warning", "VideoObject is missing publisher", evidence=row["path"]))
        if not node.get("transcript") and not node.get("caption"):
            row_issues.append(issue("info", "VideoObject is missing transcript/caption signal", evidence=row["path"]))
        clips = [part for part in as_list(node.get("hasPart")) if isinstance(part, dict) and part.get("@type") == "Clip"]
        if clips:
            for index, clip in enumerate(clips):
                for prop in ("name", "startOffset", "url"):
                    if clip.get(prop) in (None, ""):
                        row_issues.append(issue("warning", f"Clip is missing {prop}", evidence=f"{row['path']}.hasPart[{index}]"))
        actions = [action for action in as_list(node.get("potentialAction")) if isinstance(action, dict)]
        if actions and not any(action.get("@type") == "SeekToAction" for action in actions):
            row_issues.append(issue("info", "potentialAction exists but no SeekToAction found", evidence=row["path"]))
        rows.append({"path": row["path"], "issues": row_issues})
        issues.extend(row_issues)
    # `videos` counts VideoObject nodes (MB-102 applies to them); `video_signals` is
    # what MD-190 applies to: a node, or a video the page shows.
    return {"videos": len(videos), "page_videos": shown[:20],
            "video_signals": max(len(videos), len(shown)), "rows": rows, "issues": issues}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check VideoObject JSON-LD")
    parser.add_argument("source", help="URL, HTML file, or JSON-LD file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    args.source = read_source(args.source)
    documents, meta = extract_schema_documents(args.source, timeout=args.timeout)
    result = check_video_schema(documents, meta.get("html") or "", meta["final_url"])
    result.update({"source": args.source, "final_url": meta["final_url"],
                   "fetch_error": (meta.get("fetch") or {}).get("error"),
                   "fetch_error_kind": (meta.get("fetch") or {}).get("error_kind")})
    lines = [f"Video schema check for {args.source}", f"Videos: {result['videos']}  Issues: {len(result['issues'])}"]
    lines.extend(f"[{item['severity']}] {item['message']} {item.get('evidence') or ''}" for item in result["issues"][:30])
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
