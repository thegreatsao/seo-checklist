#!/usr/bin/env python3
"""Measure the CSS-minification thresholds against pinned, labelled npm packages.

The corpus deliberately contains two kinds of source CSS. Group A is generated build
output from Sass/PostCSS pipelines; it is useful for exact source/minified pairs, but
its unminified files are already formatted unusually tightly. Group B is authored CSS.
Without Group B, a boundary learned from generated source would misclassify ordinary
hand-written stylesheets as minified. The corpus is packages, not a sample of sites:
packages shipping both forms provide their own labels.

A corpus of build output is not a corpus of CSS, and many files from one package are
not many independent observations. Colour variants, partials and generated fragments
share one build pipeline. Corpus-level estimates therefore use the median of
per-package medians; pooled file and pair statistics remain visible to expose
pseudo-replication instead of silently giving prolific packages more weight.

    python3 tools/calibrate_css_minification.py
    python3 tools/calibrate_css_minification.py --check

The first command fetches pinned tarballs, measures them and rewrites the dated report.
The second reads only that report and the classifier constants; it never uses network.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath

from corpus_fetch import CACHE, display_path as _display_path, fetch_package, tarball_url
from calibration_common import literal_constants, percentile as _percentile


HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "css-minification.json")

PACKAGES = (
    {"package": "bootstrap", "version": "5.3.3", "group": "A"},
    {"package": "bulma", "version": "1.0.2", "group": "A"},
    {"package": "spectre.css", "version": "0.5.9", "group": "A"},
    {"package": "foundation-sites", "version": "6.8.1", "group": "A"},
    {"package": "milligram", "version": "1.4.1", "group": "A"},
    {"package": "purecss", "version": "3.0.0", "group": "A"},
    {"package": "tachyons", "version": "4.12.0", "group": "A"},
    {"package": "animate.css", "version": "4.1.1", "group": "A"},
    {"package": "water.css", "version": "2.1.1", "group": "A"},
    {"package": "normalize.css", "version": "8.0.1", "group": "B"},
    {"package": "sanitize.css", "version": "13.0.0", "group": "B"},
    {"package": "simpledotcss", "version": "2.3.0", "group": "B"},
    {"package": "@picocss/pico", "version": "2.0.6", "group": "B"},
    {"package": "98.css", "version": "0.1.20", "group": "B"},
    {"package": "nes.css", "version": "2.3.0", "group": "B"},
    {"package": "mvp.css", "version": "1.17.2", "group": "B"},
    {"package": "@vscode/codicons", "version": "0.0.36", "group": "B"},
    {"package": "jasmine-core", "version": "5.4.0", "group": "B"},
    {"package": "skeleton-css", "version": "2.0.4", "group": "B"},
)

CONSTANT_NAMES = (
    "MINIFIED_BYTES_PER_LINE",
    "MINIFIED_COMMENT_SHARE",
    "MINIFIED_MAX_INDENTED",
    "MINIFICATION_SAVINGS_FRACTION",
    "WASTED_BYTES_WARN",
    "SMALL_FILE_BYTES",
)

_RUNTIME = {}


def _load_runtime() -> None:
    """Import the classifier only for a corpus-building run."""
    sys.path.insert(0, SCRIPTS)
    import css_minify_check

    _RUNTIME.update({name: getattr(css_minify_check, name)
                     for name in CONSTANT_NAMES})
    _RUNTIME["looks_minified"] = css_minify_check.looks_minified
    _RUNTIME["minification_signals"] = css_minify_check.minification_signals


def _offline_constants() -> dict:
    """Read literal constants without importing optional checker dependencies."""
    return literal_constants(os.path.join(SCRIPTS, "css_minify_check.py"),
                             set(CONSTANT_NAMES),
                             "could not read classifier constants: {missing}")


def _label(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    return "minified" if name.endswith((".min.css", "-min.css")) else "source"


def _source_name(path: str) -> str | None:
    if path.lower().endswith(".min.css"):
        return path[:-8] + ".css"
    if path.lower().endswith("-min.css"):
        return path[:-8] + ".css"
    return None


def _round(value: float) -> float:
    return round(value, 6)


def _distribution(values: list[float]) -> dict:
    return {
        "count": len(values),
        "min": _round(min(values)),
        "p10": _round(_percentile(values, 0.10)),
        "p50": _round(_percentile(values, 0.50)),
        "p90": _round(_percentile(values, 0.90)),
        "max": _round(max(values)),
    }


def _package_names(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys(row["package"] for row in rows))


def _estimators(rows: list[dict], value_key: str, unit: str) -> dict:
    """Return the pooled median and the equally weighted package estimator."""
    pooled = [row[value_key] for row in rows]
    package_names = _package_names(rows)
    weight = 1 / len(package_names)
    by_package = {}
    package_medians = []
    for package in package_names:
        values = [row[value_key] for row in rows if row["package"] == package]
        median = _percentile(values, 0.50)
        package_medians.append(median)
        by_package[package] = {
            "median": _round(median),
            "observation_count": len(values),
            "weight_fraction": _round(weight),
        }
    return {
        "pooled": {
            "method": f"median across {unit}",
            "value": _round(_percentile(pooled, 0.50)),
            "observation_count": len(pooled),
        },
        "package_level": {
            "method": "median of per-package medians",
            "value": _round(_percentile(package_medians, 0.50)),
            "package_count": len(package_names),
            "by_package": by_package,
        },
    }


def _split_distributions(files: list[dict]) -> dict:
    signals = ("bytes_per_line", "comment_share", "indented_lines_first_400",
               "byte_size", "gzip_bytes")
    result = {}
    for signal in signals:
        result[signal] = {"by_group": {}, "by_package": {}}
        for group in ("A", "B"):
            result[signal]["by_group"][group] = {}
            for label in ("minified", "source"):
                values = [row[signal] for row in files
                          if row["group"] == group and row["label"] == label]
                result[signal]["by_group"][group][label] = (
                    _distribution(values) if values else {"count": 0})
        for package in _package_names(files):
            result[signal]["by_package"][package] = {}
            for label in ("minified", "source"):
                values = [row[signal] for row in files
                          if row["package"] == package and row["label"] == label]
                result[signal]["by_package"][package][label] = (
                    _distribution(values) if values else {"count": 0})
    return result


def _sides(values: list[float], value: float, condition: str) -> dict:
    if condition == "greater":
        return {"at_or_below": sum(v <= value for v in values),
                "above": sum(v > value for v in values)}
    if condition == "less":
        return {"below": sum(v < value for v in values),
                "at_or_above": sum(v >= value for v in values)}
    raise ValueError(condition)


def _measure_package(spec: dict) -> tuple[dict, list[dict], list[dict]]:
    package, version, group = spec["package"], spec["version"], spec["group"]
    fetched, raw_files = fetch_package(
        package,
        version,
        lambda path: path.lower().endswith(".css"),
        cache_dir=CACHE,
    )

    files = []
    by_archive_path = {}
    for archive_path, raw in sorted(raw_files.items()):
        css = raw.decode("utf-8", errors="replace")
        classifier_label, classifier_ratio = _RUNTIME["looks_minified"](css)
        bytes_per_line, comment_share, indented = _RUNTIME["minification_signals"](css)
        display = _display_path(package, version, archive_path)
        row = {
            "path": display,
            "package": package,
            "group": group,
            "label": _label(archive_path),
            "classifier_minified": classifier_label,
            "bytes_per_line": _round(bytes_per_line),
            "classifier_bytes_per_line": classifier_ratio,
            "comment_share": _round(comment_share),
            "indented_lines_first_400": indented,
            "byte_size": len(raw),
            "gzip_bytes": len(gzip.compress(raw, compresslevel=9, mtime=0)),
        }
        files.append(row)
        by_archive_path[archive_path] = row

    pairs = []
    for min_path, min_row in sorted(by_archive_path.items()):
        src_path = _source_name(min_path)
        if src_path is None or src_path not in by_archive_path:
            continue
        src_row = by_archive_path[src_path]
        saved = src_row["byte_size"] - min_row["byte_size"]
        gz_saved = src_row["gzip_bytes"] - min_row["gzip_bytes"]
        if saved <= 0:
            continue
        pairs.append({
            "source": src_row["path"],
            "minified": min_row["path"],
            "package": package,
            "group": group,
            "source_bytes": src_row["byte_size"],
            "minified_bytes": min_row["byte_size"],
            "bytes_saved": saved,
            "saving_fraction": _round(saved / src_row["byte_size"]),
            "gzip_source_bytes": src_row["gzip_bytes"],
            "gzip_minified_bytes": min_row["gzip_bytes"],
            "gzip_saving_bytes": gz_saved,
            "gzip_survival_fraction": _round(gz_saved / saved),
        })

    manifest = {
        **spec,
        "tarball": tarball_url(package, version),
        "sha256": fetched["sha256"],
        "css_file_count": len(files),
        "paired_file_count": len(pairs),
    }
    return manifest, files, pairs


def _reads_minified(row: dict, limits: dict) -> bool:
    """`css_minify_check.looks_minified` over a stored row's three signals."""
    return (row["bytes_per_line"] > limits["MINIFIED_BYTES_PER_LINE"]
            and row["comment_share"] < limits["MINIFIED_COMMENT_SHARE"]
            and row["indented_lines_first_400"] < limits["MINIFIED_MAX_INDENTED"])


def _misreads(files: list[dict], name: str, signal: str, limits: dict) -> dict:
    """Labelled files the classifier reads against their label, at the constant's value
    and at the best value the corpus allows with the other two constants held.

    The fewest is the corpus's answer and does not depend on the constant's value, so a
    re-measure cannot bless a constant that misreads more files than another value would.
    """
    def misread(trial: dict) -> int:
        return sum(_reads_minified(row, trial) != (row["label"] == "minified")
                   for row in files)
    values = sorted({row[signal] for row in files})
    counts = {value: misread({**limits, name: value})
              for value in (values[0] - 1, *values, values[-1] + 1)}
    fewest = min(counts.values())
    best = [value for value, count in counts.items() if count == fewest]
    return {"at_value": misread(limits), "fewest": fewest,
            "fewest_from_to": [best[0], best[-1]]}


def _constant_evidence(files: list[dict], pairs: list[dict],
                       limits: dict | None = None) -> dict:
    limits = limits or _RUNTIME
    bytes_per_line_limit = limits["MINIFIED_BYTES_PER_LINE"]
    comment_share_limit = limits["MINIFIED_COMMENT_SHARE"]
    max_indented = limits["MINIFIED_MAX_INDENTED"]
    savings_fraction = limits["MINIFICATION_SAVINGS_FRACTION"]
    wasted_bytes_warn = limits["WASTED_BYTES_WARN"]
    small_file_bytes = limits["SMALL_FILE_BYTES"]
    classifier = {name: limits[name] for name in CONSTANT_NAMES[:3]}
    bpl = [row["bytes_per_line"] for row in files]
    comments = [row["comment_share"] for row in files]
    indented = [row["indented_lines_first_400"] for row in files]
    sizes = [row["byte_size"] for row in files]
    savings = [row["saving_fraction"] for row in pairs]
    waste_rows = [{"package": row["package"],
                   "estimated_uncompressed_waste": (
                       row["byte_size"] * savings_fraction)}
                  for row in files if row["label"] == "source"]
    estimated_waste = [row["estimated_uncompressed_waste"] for row in waste_rows]
    small = [row for row in files if row["byte_size"] < small_file_bytes]
    small_packages = _package_names(small)
    changed = [row for row in files
               if row["bytes_per_line"] > bytes_per_line_limit
               and row["indented_lines_first_400"] < max_indented
               and row["comment_share"] >= comment_share_limit]
    savings_estimators = _estimators(pairs, "saving_fraction", "pairs")
    recommendation = round(savings_estimators["package_level"]["value"], 3)
    return {
        "MINIFIED_BYTES_PER_LINE": {
            "value": bytes_per_line_limit,
            "observed": _distribution(bpl),
            "files_either_side": _sides(bpl, bytes_per_line_limit, "greater"),
            "corpus_says": "retained; 165/174 minified and two source-labelled one-line files cross it",
            "classifier_misreads": _misreads(
                files, "MINIFIED_BYTES_PER_LINE", "bytes_per_line", classifier),
            "estimators": _estimators(files, "bytes_per_line", "files"),
        },
        "MINIFIED_COMMENT_SHARE": {
            "value": comment_share_limit,
            "observed": _distribution(comments),
            "files_either_side": _sides(comments, comment_share_limit, "less"),
            "classification_changed_by_conjunct": {
                "count": len(changed),
                "minified": sum(row["label"] == "minified" for row in changed),
                "source": sum(row["label"] == "source" for row in changed),
                "paths": [row["path"] for row in changed],
            },
            "corpus_says": "retained; report the conjunct's observed effect, not discrimination it lacks",
            "set_by": "judgement",
            "classifier_misreads": _misreads(
                files, "MINIFIED_COMMENT_SHARE", "comment_share", classifier),
            "estimators": _estimators(files, "comment_share", "files"),
        },
        "MINIFIED_MAX_INDENTED": {
            "value": max_indented,
            "observed": _distribution(indented),
            "files_either_side": _sides(indented, max_indented, "less"),
            "corpus_says": "retained as an arbitrary point in the observed safe band",
            "classifier_misreads": _misreads(
                files, "MINIFIED_MAX_INDENTED", "indented_lines_first_400", classifier),
            "estimators": _estimators(files, "indented_lines_first_400", "files"),
        },
        "MINIFICATION_SAVINGS_FRACTION": {
            "value": savings_fraction,
            "observed": _distribution(savings),
            "pairs_either_side": _sides(savings, savings_fraction, "greater"),
            "corpus_says": "median of per-package paired-file medians, rounded to three decimal places",
            "recommended_value": recommendation,
            "estimators": savings_estimators,
        },
        "WASTED_BYTES_WARN": {
            "value": wasted_bytes_warn,
            "observed_estimated_uncompressed_waste": _distribution(estimated_waste),
            "files_either_side": _sides(estimated_waste, wasted_bytes_warn, "greater"),
            "corpus_says": "retained; aggregate and package-level gzip survival show that this is uncompressed, not visitor-paid, waste",
            "set_by": "judgement",
            "estimators": _estimators(
                waste_rows, "estimated_uncompressed_waste", "source files"),
            "gzip_survival_estimators": _estimators(
                pairs, "gzip_survival_fraction", "pairs"),
        },
        "SMALL_FILE_BYTES": {
            "value": small_file_bytes,
            "observed": _distribution(sizes),
            "files_either_side": _sides(sizes, small_file_bytes, "less"),
            "corpus_says": (
                f"retained after identifying {len(small)} sub-2KB files from "
                f"{len(small_packages)} packages and their packaging conventions"),
            "set_by": "judgement",
            "estimators": _estimators(files, "byte_size", "files"),
        },
    }


def build_report() -> dict:
    manifest, files, pairs = [], [], []
    failures = []
    for spec in PACKAGES:
        try:
            package_row, package_files, package_pairs = _measure_package(spec)
        except Exception as exc:
            print(f"dropping {spec['package']}@{spec['version']}: {exc}", file=sys.stderr)
            failures.append({**spec, "error": str(exc)[:240]})
            continue
        manifest.append(package_row)
        files.extend(package_files)
        pairs.extend(package_pairs)
    if not manifest or not files or not pairs:
        raise RuntimeError("the fetched corpus did not produce packages, CSS files and pairs")

    small = [row for row in files
             if row["byte_size"] < _RUNTIME["SMALL_FILE_BYTES"]]
    gzip_survival = [row["gzip_survival_fraction"] for row in pairs]
    saving = [row["saving_fraction"] for row in pairs]
    total_saved = sum(row["bytes_saved"] for row in pairs)
    total_gzip_saved = sum(row["gzip_saving_bytes"] for row in pairs)
    for row in manifest:
        row["css_file_share"] = _round(row["css_file_count"] / len(files))
        row["paired_file_share"] = _round(row["paired_file_count"] / len(pairs))
    report = {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "method": {
            "labels": "filename ends .min.css or -min.css; source otherwise",
            "pairs": "matching source and minified stems in the same tarball directory",
            "percentiles": "linear interpolation over sorted observations",
            "corpus_estimator": "median of per-package medians; packages have equal weight",
            "gzip": "Python gzip level 9 with mtime=0",
        },
        "manifest": manifest,
        "fetch_failures": failures,
        "counts": {
            "packages": len(manifest),
            "css_files": len(files),
            "pairs": len(pairs),
            "groups": {group: sum(row["group"] == group for row in files)
                       for group in ("A", "B")},
            "labels": {label: sum(row["label"] == label for row in files)
                       for label in ("minified", "source")},
        },
        "signal_distributions": _split_distributions(files),
        "constants": _constant_evidence(files, pairs),
        "pair_statistics": {
            "bytes_saved_fraction": _distribution(saving),
            "gzip_survival_fraction": _distribution(gzip_survival),
            "by_group": {
                group: {
                    "bytes_saved_fraction": _distribution([
                        row["saving_fraction"] for row in pairs if row["group"] == group]),
                    "gzip_survival_fraction": _distribution([
                        row["gzip_survival_fraction"] for row in pairs
                        if row["group"] == group]),
                }
                for group in ("A", "B")
            },
            "by_package": {
                package: {
                    "bytes_saved_fraction": _distribution([
                        row["saving_fraction"] for row in pairs
                        if row["package"] == package]),
                    "gzip_survival_fraction": _distribution([
                        row["gzip_survival_fraction"] for row in pairs
                        if row["package"] == package]),
                }
                for package in _package_names(pairs)
            },
            "aggregate": {
                "bytes_saved": total_saved,
                "gzip_bytes_saved": total_gzip_saved,
                "gzip_survival_fraction": _round(total_gzip_saved / total_saved),
            },
        },
        "small_file_behavior": {
            "count": len(small),
            "labels": {label: sum(row["label"] == label for row in small)
                       for label in ("minified", "source")},
            "by_package": {
                package: {
                    "count": sum(row["package"] == package for row in small),
                    "share": _round(sum(row["package"] == package for row in small)
                                    / len(small)),
                }
                for package in _package_names(small)
            },
            "classifier": {"minified": sum(row["classifier_minified"] for row in small),
                           "unminified": sum(not row["classifier_minified"] for row in small)},
            "label_matches_classifier": sum(
                row["classifier_minified"] == (row["label"] == "minified") for row in small),
            "paths": [row["path"] for row in small],
        },
        "files": files,
        "pairs": pairs,
    }
    return report


def write_report() -> int:
    report = build_report()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {REPORT}: {report['counts']['packages']} packages, "
          f"{report['counts']['css_files']} CSS files, {report['counts']['pairs']} pairs")
    return 0


def _manifest_identity(rows: list[dict]) -> list[dict]:
    return [{key: row.get(key) for key in ("package", "version", "group")} for row in rows]


def check_report(constants_to_check: dict) -> int:
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
    constants = report.get("constants")
    if not isinstance(constants, dict):
        print("calibration report has no constants", file=sys.stderr)
        return 1
    signal_distributions = report.get("signal_distributions", {})
    pair_statistics = report.get("pair_statistics", {})
    if (not signal_distributions
            or any("by_package" not in distribution
                   for distribution in signal_distributions.values())
            or "by_package" not in pair_statistics):
        print("calibration report has no package-level distributions", file=sys.stderr)
        return 1

    print("by_package corpus shares:")
    for row in report.get("manifest", []):
        print(f"  {row['package']}: files={row['css_file_count']} "
              f"({row.get('css_file_share', 0):.3%}); "
              f"pairs={row['paired_file_count']} "
              f"({row.get('paired_file_share', 0):.3%})")
    print("by_package pair medians:")
    for package, distributions in pair_statistics["by_package"].items():
        saving = distributions["bytes_saved_fraction"]
        survival = distributions["gzip_survival_fraction"]
        print(f"  {package}: saving={saving['p50']}; "
              f"gzip_survival={survival['p50']}; pairs={saving['count']}")
    print("by_package file-signal medians:")
    for signal, distribution in signal_distributions.items():
        summaries = []
        for package, labels in distribution["by_package"].items():
            labelled = ",".join(
                f"{label}={values.get('p50', 'n/a')}"
                for label, values in labels.items())
            summaries.append(f"{package}[{labelled}]")
        print(f"  {signal}: {'; '.join(summaries)}")

    try:
        recomputed = _constant_evidence(report["files"], report["pairs"], constants_to_check)
        reproduced = all(_reads_minified(row, constants_to_check) == row["classifier_minified"]
                         for row in report["files"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        print(f"calibration report has no usable files and pairs: {exc}", file=sys.stderr)
        return 1
    if not reproduced:
        print("the stored classifier answers do not follow from the three signals; mirror "
              "css_minify_check.looks_minified in _reads_minified and measure again",
              file=sys.stderr)
        return 1

    disagrees = False
    for name, value in constants_to_check.items():
        evidence = constants.get(name)
        if not isinstance(evidence, dict):
            print(f"calibration report has no {name}", file=sys.stderr)
            return 1
        estimators = evidence.get("estimators", {})
        pooled = estimators.get("pooled", {}).get("value")
        package_level = estimators.get("package_level", {}).get("value")
        if pooled is None or package_level is None:
            print(f"calibration report has no estimators for {name}", file=sys.stderr)
            return 1
        if evidence.get("value") != value:
            print(f"{name}: constant={value}; the report was measured under "
                  f"{evidence.get('value')}; agree=no — measure again")
            disagrees = True
            continue
        if evidence != recomputed[name]:
            print(f"{name}: constant={value}; the report's evidence does not follow from "
                  f"its stored files and pairs; agree=no")
            disagrees = True
            continue
        # Three kinds of basis, and only two of them are the corpus choosing a value.
        misreads = evidence.get("classifier_misreads")
        if evidence.get("set_by") == "judgement":
            agrees = True
            verdict = "set by judgement, not chosen by the corpus"
            if misreads:
                verdict += (f" (misreads {misreads['at_value']} labelled files; the fewest "
                            f"any value gives is {misreads['fewest']})")
        elif "recommended_value" in evidence:
            agrees = value == evidence["recommended_value"]
            verdict = (f"corpus={evidence['recommended_value']}; "
                       f"agree={'yes' if agrees else 'no'}")
        elif misreads:
            agrees = misreads["at_value"] == misreads["fewest"]
            low, high = misreads["fewest_from_to"]
            verdict = (f"misreads {misreads['at_value']} labelled files, the fewest any "
                       f"value gives is {misreads['fewest']} ({low} to {high}); "
                       f"agree={'yes' if agrees else 'no'}")
        else:
            print(f"calibration report gives no basis for {name}", file=sys.stderr)
            return 1
        print(f"{name}: constant={value}; {verdict}; pooled={pooled}; "
              f"package_level={package_level} — {evidence.get('corpus_says', '')}")
        disagrees |= not agrees
    return int(disagrees)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="compare the committed report with constants; no network")
    args = parser.parse_args()
    if args.check:
        return check_report(_offline_constants())
    _load_runtime()
    return write_report()


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
