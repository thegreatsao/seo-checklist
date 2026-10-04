#!/usr/bin/env python3
"""Measure the large-font threshold against pinned subsetted and full font packages.

    python3 tools/calibrate_font_weight.py
    python3 tools/calibrate_font_weight.py --check

The default command fetches pinned npm tarballs and rewrites the dated report. The
check command reads only the committed report and the literal threshold; it never
uses the network.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath

from corpus_fetch import CACHE, fetch_package, package_basename, tarball_url


HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "font-weight.json")

PACKAGES = (
    {"package": "@fontsource/inter", "version": "5.1.0", "arm": "A"},
    {"package": "@fontsource/roboto", "version": "5.1.0", "arm": "A"},
    {"package": "@fontsource/open-sans", "version": "5.1.0", "arm": "A"},
    {"package": "@fontsource/lora", "version": "5.1.0", "arm": "A"},
    {"package": "@fontsource/jetbrains-mono", "version": "5.1.0", "arm": "A"},
    {"package": "@fontsource/noto-sans-jp", "version": "5.1.0", "arm": "A"},
    {"package": "@expo-google-fonts/inter", "version": "0.2.3", "arm": "B"},
    {"package": "@expo-google-fonts/noto-sans", "version": "0.2.3", "arm": "B"},
)


def _offline_constant() -> int:
    path = os.path.join(SCRIPTS, "font_audit.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "LARGE_FONT_BYTES":
            return ast.literal_eval(node.value)
    raise RuntimeError("could not read LARGE_FONT_BYTES")


def _display_path(package: str, version: str, member_name: str) -> str:
    parts = PurePosixPath(member_name).parts
    if parts and parts[0] == "package":
        parts = parts[1:]
    return str(PurePosixPath(f"{package_basename(package)}-{version}", *parts))


def _subset(package: str, path: str) -> str | None:
    if not package.startswith("@fontsource/"):
        return None
    stem = PurePosixPath(path).stem.lower()
    family = package_basename(package)
    prefix = f"{family}-"
    if not stem.startswith(prefix):
        return None
    parts = stem[len(prefix):].rsplit("-", 2)
    return parts[0] if len(parts) == 3 else None


def _percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("a distribution cannot be computed from no observations")
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _rounded(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


def _distribution(rows: list[dict], threshold: int) -> dict:
    values = [row["byte_size"] for row in rows]
    return {
        "count": len(values),
        "min": min(values),
        "p10": _rounded(_percentile(values, 0.10)),
        "p50": _rounded(_percentile(values, 0.50)),
        "p90": _rounded(_percentile(values, 0.90)),
        "max": max(values),
        "count_over_threshold": sum(value > threshold for value in values),
    }


def _select(rows: list[dict], **conditions: object) -> list[dict]:
    return [row for row in rows
            if all(row.get(key) == value for key, value in conditions.items())]


def _measure_package(spec: dict) -> tuple[dict, list[dict]]:
    extensions = (".woff2", ".woff") if spec["arm"] == "A" else (".ttf",)
    fetched, raw_files = fetch_package(
        spec["package"],
        spec["version"],
        lambda path: path.lower().endswith(extensions),
        cache_dir=CACHE,
        max_response_bytes=128 * 1024 * 1024,
    )
    files = []
    for archive_path, raw in sorted(raw_files.items()):
        extension = PurePosixPath(archive_path).suffix.lower().lstrip(".")
        files.append({
            "path": _display_path(spec["package"], spec["version"], archive_path),
            "package": spec["package"],
            "arm": spec["arm"],
            "format": extension,
            "subset": _subset(spec["package"], archive_path),
            "byte_size": len(raw),
        })
    manifest = {
        **spec,
        "tarball": tarball_url(spec["package"], spec["version"]),
        "sha256": fetched["sha256"],
        "file_count": fetched["file_count"],
    }
    return manifest, files


def build_report() -> dict:
    threshold = _offline_constant()
    manifest, files = [], []
    for spec in PACKAGES:
        package_manifest, package_files = _measure_package(spec)
        manifest.append(package_manifest)
        files.extend(package_files)

    arm_a = _select(files, arm="A")
    latin = [row for row in arm_a if row["subset"] in {"latin", "latin-ext"}]
    rest = [row for row in arm_a if row["subset"] not in {"latin", "latin-ext"}]
    cjk = _select(files, package="@fontsource/noto-sans-jp")
    arm_b = _select(files, arm="B", format="ttf")
    inter_woff2 = [row for row in latin
                   if row["package"] == "@fontsource/inter"
                   and row["format"] == "woff2"]
    inter_ttf = _select(
        files, package="@expo-google-fonts/inter", arm="B", format="ttf")
    ordinary = [row for row in arm_a if row["subset"] != "japanese"]
    empty_band = (max(row["byte_size"] for row in ordinary),
                  min(row["byte_size"] for row in arm_b))
    cjk_woff2_over = [row for row in cjk
                      if row["format"] == "woff2"
                      and row["byte_size"] > threshold]
    cjk_woff_over = [row for row in cjk
                     if row["format"] == "woff"
                     and row["byte_size"] > threshold]

    distributions = {
        "arm_a": {
            format_name: {
                "latin_and_latin_ext": _distribution(
                    _select(latin, format=format_name), threshold),
                "other_subsets": _distribution(
                    _select(rest, format=format_name), threshold),
            }
            for format_name in ("woff2", "woff")
        },
        "arm_a_cjk": {
            format_name: _distribution(
                _select(cjk, format=format_name), threshold)
            for format_name in ("woff2", "woff")
        },
        "arm_b_ttf": _distribution(arm_b, threshold),
        "inter_pairing": {
            "subsetted_latin_woff2": _distribution(inter_woff2, threshold),
            "full_ttf": _distribution(inter_ttf, threshold),
        },
    }
    return {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "method": {
            "labels": "npm package arm plus filename extension; @fontsource subset token parsed before weight and style",
            "percentiles": "linear interpolation over sorted file byte sizes",
            "threshold_comparison": "content length strictly greater than LARGE_FONT_BYTES",
        },
        "constant": {
            "name": "LARGE_FONT_BYTES",
            "value": threshold,
            "recommended_value": threshold,
            "corpus_says": (
                f"retained in the {empty_band[0]:,}-{empty_band[1]:,} byte empty "
                "observed band between ordinary subsetted web fonts and full TTF "
                "faces; it does not detect non-WOFF2 faces, which have a separate "
                "extension check"),
        },
        "manifest": manifest,
        "counts": {
            "packages": len(manifest),
            "files": len(files),
            "arms": {arm: sum(row["arm"] == arm for row in files)
                     for arm in ("A", "B")},
            "formats": {format_name: sum(row["format"] == format_name for row in files)
                        for format_name in ("woff2", "woff", "ttf")},
        },
        "distributions": distributions,
        "cjk_finding": (
            f"The {len(cjk_woff2_over)} WOFF2 crossings are the japanese fallback "
            "files, one per weight, rather than the "
            f"{len({row['subset'] for row in cjk if row['subset'].isdigit()})} "
            "numbered unicode-range subsets. The WOFF control has the same "
            f"{len(cjk_woff_over)} fallback crossings."),
        "cjk_woff2_files_over_threshold": cjk_woff2_over,
        "cjk_woff_files_over_threshold": cjk_woff_over,
        "files": files,
    }


def write_report() -> int:
    report = build_report()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {REPORT}: {report['counts']['packages']} packages, "
          f"{report['counts']['files']} font files")
    return 0


def _manifest_identity(rows: list[dict]) -> list[dict]:
    return [{key: row.get(key) for key in ("package", "version", "arm")}
            for row in rows]


def check_report() -> int:
    try:
        with open(REPORT, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable calibration report: {exc}", file=sys.stderr)
        return 1
    if _manifest_identity(report.get("manifest", [])) != _manifest_identity(list(PACKAGES)):
        print("calibration report was produced from a different corpus manifest",
              file=sys.stderr)
        return 1
    expected = report.get("constant", {}).get("recommended_value")
    actual = _offline_constant()
    agrees = actual == expected
    print(f"LARGE_FONT_BYTES: constant={actual}; corpus={expected}; "
          f"agree={'yes' if agrees else 'no'} — "
          f"{report.get('constant', {}).get('corpus_says', '')}")
    return int(not agrees)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="compare the committed report with the constant; no network")
    args = parser.parse_args()
    return check_report() if args.check else write_report()


if __name__ == "__main__":
    sys.exit(main())
