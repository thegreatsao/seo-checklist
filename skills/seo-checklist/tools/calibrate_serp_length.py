#!/usr/bin/env python3
"""Measure character-count SERP thresholds against installed font metrics.

    python3 tools/calibrate_serp_length.py
    python3 tools/calibrate_serp_length.py --check

The default command reads local font files and rewrites the dated report. The check
command reads only that committed artifact and the literal runtime constants; it does
not read fonts or use the network. Pixel budgets and the Arial stand-in are declared
inputs, not measurements: Google publishes neither its rendering budget nor a promise
to render Arial, so a wrong input produces a wrong derived character capacity.

``fonttools`` is deliberately a tools-only dependency. No audit imports it: this tool
uses it to produce a committed JSON artifact, while the runtime continues to read four
plain integer constants and keeps its three runtime dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

from calibration_common import literal_constants


HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "serp-length.json")

FONT_FILES = (
    {"name": "Arial", "path": "/System/Library/Fonts/Supplemental/Arial.ttf"},
    {"name": "Verdana", "path": "/System/Library/Fonts/Supplemental/Verdana.ttf"},
    {"name": "Georgia", "path": "/System/Library/Fonts/Supplemental/Georgia.ttf"},
    {"name": "Times New Roman",
     "path": "/System/Library/Fonts/Supplemental/Times New Roman.ttf"},
)

# Fixed input, not a finding: relative English A-Z frequencies, in percent. Keeping
# the table here makes the composition calculation reproducible without a corpus or
# network request. The values sum to 99.999 because the source percentages are rounded.
ENGLISH_LETTER_FREQUENCY = {
    "a": 8.167, "b": 1.492, "c": 2.782, "d": 4.253, "e": 12.702,
    "f": 2.228, "g": 2.015, "h": 6.094, "i": 6.966, "j": 0.153,
    "k": 0.772, "l": 4.025, "m": 2.406, "n": 6.749, "o": 7.507,
    "p": 1.929, "q": 0.095, "r": 5.987, "s": 6.327, "t": 9.056,
    "u": 2.758, "v": 0.978, "w": 2.360, "x": 0.150, "y": 1.974,
    "z": 0.074,
}

# These are composition assumptions, not observations. They expose how much a
# character proxy changes when the same character count uses different glyph shapes.
COMPOSITION_MIXES = (
    {"name": "lowercase_heavy_prose", "lowercase": 0.84,
     "uppercase": 0.00, "space": 0.16},
    {"name": "ordinary_title_case", "lowercase": 0.79,
     "uppercase": 0.05, "space": 0.16},
    {"name": "all_caps", "lowercase": 0.00,
     "uppercase": 1.00, "space": 0.00},
)

# Widely reported third-party observations, not Google-published limits.
SURFACES = (
    {"name": "desktop_title", "budget_pixels": 600, "font_size_pixels": 20},
    {"name": "desktop_description", "budget_pixels": 920,
     "font_size_pixels": 14},
    {"name": "mobile_description", "budget_pixels": 680,
     "font_size_pixels": 14},
)

CONSTANT_NAMES = (
    "TITLE_MIN_CHARS", "TITLE_MAX_CHARS", "META_MIN_CHARS", "META_MAX_CHARS")
EXTREME_STRING_LENGTH = 60
SELECTION_RULE = "ordinary composition in Arial"
SELECTION_FONT = "Arial"
SELECTION_MIX = "ordinary_title_case"


def _round(value: float) -> float:
    return round(value, 6)


def _offline_constants() -> dict[str, int]:
    """Read literal constants without importing article_seo or its dependencies."""
    return literal_constants(os.path.join(SCRIPTS, "article_seo.py"),
                             set(CONSTANT_NAMES), "could not read SERP constants: {missing}")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _advance_factory(font, font_size: int):
    cmap = font.getBestCmap()
    metrics = font["hmtx"].metrics
    units_per_em = font["head"].unitsPerEm

    def advance(character: str) -> float:
        glyph = cmap.get(ord(character))
        if glyph is None:
            raise RuntimeError(f"font has no glyph for {character!r}")
        return metrics[glyph][0] / units_per_em * font_size

    return advance


def _weighted_letter_width(advance, uppercase: bool) -> float:
    total = sum(ENGLISH_LETTER_FREQUENCY.values())
    return sum(
        advance(letter.upper() if uppercase else letter) * frequency
        for letter, frequency in ENGLISH_LETTER_FREQUENCY.items()
    ) / total


def _pixels_per_character(advance, mix: dict) -> float:
    lowercase = _weighted_letter_width(advance, uppercase=False)
    uppercase = _weighted_letter_width(advance, uppercase=True)
    return (mix["lowercase"] * lowercase
            + mix["uppercase"] * uppercase
            + mix["space"] * advance(" "))


def _raw_spread(font, size: int) -> dict:
    advance = _advance_factory(font, size)
    rows = [{"glyph": glyph, "width_pixels": advance(glyph)}
            for glyph in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    narrowest = min(rows, key=lambda row: (row["width_pixels"], row["glyph"]))
    widest = max(rows, key=lambda row: (row["width_pixels"], row["glyph"]))
    return {
        "font_size_pixels": size,
        "glyph_domain": "ASCII letters A-Z and a-z; spaces excluded",
        "fixed_string_length": EXTREME_STRING_LENGTH,
        "narrowest": {
            "glyph": narrowest["glyph"],
            "glyph_width_pixels": _round(narrowest["width_pixels"]),
            "fixed_string": narrowest["glyph"] * EXTREME_STRING_LENGTH,
            "fixed_string_width_pixels": _round(
                narrowest["width_pixels"] * EXTREME_STRING_LENGTH),
        },
        "widest": {
            "glyph": widest["glyph"],
            "glyph_width_pixels": _round(widest["width_pixels"]),
            "fixed_string": widest["glyph"] * EXTREME_STRING_LENGTH,
            "fixed_string_width_pixels": _round(
                widest["width_pixels"] * EXTREME_STRING_LENGTH),
        },
        "width_ratio": _round(widest["width_pixels"] / narrowest["width_pixels"]),
    }


def _measure_font(spec: dict, constants: dict, TTFont) -> dict:
    path = spec["path"]
    font = TTFont(path, lazy=False)
    try:
        measurements = {}
        for surface in SURFACES:
            advance = _advance_factory(font, surface["font_size_pixels"])
            by_mix = {}
            for mix in COMPOSITION_MIXES:
                pixels_per_character = _pixels_per_character(advance, mix)
                by_mix[mix["name"]] = {
                    "pixels_per_character": _round(pixels_per_character),
                    "characters_budget_holds": math.floor(
                        surface["budget_pixels"] / pixels_per_character),
                    "constant_widths_pixels": {
                        name: _round(value * pixels_per_character)
                        for name, value in constants.items()
                    },
                }
            measurements[surface["name"]] = {
                "budget_pixels": surface["budget_pixels"],
                "font_size_pixels": surface["font_size_pixels"],
                "composition_mixes": by_mix,
            }
        return {
            "name": spec["name"],
            "path": path,
            "sha256": _sha256(path),
            "units_per_em": font["head"].unitsPerEm,
            "measurements": measurements,
            "raw_glyph_spread": {
                f"{size}px": _raw_spread(font, size) for size in (20, 14)
            },
        }
    finally:
        font.close()


def build_report() -> dict:
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError(
            "fonttools is required only to generate this calibration report") from exc

    constants = _offline_constants()
    fonts = [_measure_font(spec, constants, TTFont) for spec in FONT_FILES]
    arial = next(row for row in fonts if row["name"] == SELECTION_FONT)
    title_measurement = arial["measurements"]["desktop_title"][
        "composition_mixes"][SELECTION_MIX]
    meta_measurement = arial["measurements"]["desktop_description"][
        "composition_mixes"][SELECTION_MIX]
    mobile_measurement = arial["measurements"]["mobile_description"][
        "composition_mixes"][SELECTION_MIX]
    caps_measurement = arial["measurements"]["desktop_title"][
        "composition_mixes"]["all_caps"]
    verdana = next(row for row in fonts if row["name"] == "Verdana")
    verdana_description_capacity = verdana["measurements"][
        "desktop_description"]["composition_mixes"][SELECTION_MIX][
            "characters_budget_holds"]

    def decision_alternatives(surface: str) -> dict:
        return {
            "capacities_by_mix_in_arial": {
                mix["name"]: arial["measurements"][surface][
                    "composition_mixes"][mix["name"]]["characters_budget_holds"]
                for mix in COMPOSITION_MIXES
            },
            "capacities_for_ordinary_composition_by_font": {
                font["name"]: font["measurements"][surface][
                    "composition_mixes"][SELECTION_MIX]["characters_budget_holds"]
                for font in fonts
            },
        }

    recommendations = {
        "TITLE_MAX_CHARS": title_measurement["characters_budget_holds"],
        "META_MAX_CHARS": meta_measurement["characters_budget_holds"],
    }
    return {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "inputs": {
            "pixel_budgets": {
                "status": "assumed_input_not_google_published",
                "weakest_link": (
                    "If a reported pixel budget is wrong, every character capacity "
                    "derived from it is wrong."),
                "surfaces": {row["name"]: row["budget_pixels"] for row in SURFACES},
            },
            "font_stand_in": {
                "status": "assumed_input_not_google_font",
                "primary": "Arial",
                "sensitivity_fonts": [row["name"] for row in FONT_FILES[1:]],
            },
            "english_letter_frequency": {
                "status": "declared_input_not_finding",
                "name": "fixed English A-Z frequency percentages embedded in calibrate_serp_length.py",
                "percentages": ENGLISH_LETTER_FREQUENCY,
            },
            "composition_mixes": {
                row["name"]: {key: row[key]
                              for key in ("lowercase", "uppercase", "space")}
                for row in COMPOSITION_MIXES
            },
            "font_sizes_pixels": {
                row["name"]: row["font_size_pixels"] for row in SURFACES
            },
        },
        "method": {
            "glyph_width": "horizontal advance from the font hmtx table, scaled by unitsPerEm",
            "mix_width": "frequency-weighted letter advance combined with declared case and space shares",
            "capacity": "floor(pixel budget / pixels per character)",
            "kerning": "not applied; the proxy uses individual glyph advances",
            "extreme_string": (
                f"{EXTREME_STRING_LENGTH} repetitions of the narrowest or widest "
                "ASCII letter glyph"),
        },
        "selection_rule": SELECTION_RULE,
        "constants": {
            name: {
                "value": value,
                "recommended_value": recommendations.get(name, value),
                "basis": "measured" if name in recommendations else "convention",
            }
            for name, value in constants.items()
        },
        "calibration_decisions": {
            "TITLE_MAX_CHARS": {
                "font": SELECTION_FONT,
                "mix": SELECTION_MIX,
                "surface": "desktop_title",
                "capacity": recommendations["TITLE_MAX_CHARS"],
                "alternatives": decision_alternatives("desktop_title"),
            },
            "META_MAX_CHARS": {
                "font": SELECTION_FONT,
                "mix": SELECTION_MIX,
                "surface": "desktop_description",
                "capacity": recommendations["META_MAX_CHARS"],
                "alternatives": decision_alternatives("desktop_description"),
                "limitation": (
                    f"Verdana at ordinary composition holds about "
                    f"{verdana_description_capacity} description characters; a "
                    "lower-capacity rendering font than Arial would therefore make "
                    f"even the calibrated {recommendations['META_MAX_CHARS']}-character "
                    "bound permissive."),
            },
            "minimums": (
                "Pixel budgets establish truncation ceilings, not editorial minimums; "
                "TITLE_MIN_CHARS and META_MIN_CHARS remain explicit conventions."),
            "mobile": (
                "Reported as sensitivity evidence only; no threshold is calibrated "
                "to the mobile description budget in this change."),
        },
        "findings": {
            "arial_title": {
                "ordinary_title_case_pixels_per_character": title_measurement[
                    "pixels_per_character"],
                "characters_budget_holds": title_measurement[
                    "characters_budget_holds"],
                "title_max_width_pixels": title_measurement[
                    "constant_widths_pixels"]["TITLE_MAX_CHARS"],
                "next_character_count": constants["TITLE_MAX_CHARS"] + 1,
                "next_character_count_width_pixels": _round(
                    (constants["TITLE_MAX_CHARS"] + 1)
                    * title_measurement["pixels_per_character"]),
            },
            "arial_description": {
                "ordinary_composition_pixels_per_character": meta_measurement[
                    "pixels_per_character"],
                "desktop_characters_budget_holds": meta_measurement[
                    "characters_budget_holds"],
                "mobile_characters_budget_holds": mobile_measurement[
                    "characters_budget_holds"],
                "prior_165_width_pixels": _round(
                    165 * meta_measurement["pixels_per_character"]),
                "prior_165_desktop_budget_overshoot_fraction": _round(
                    (165 * meta_measurement["pixels_per_character"] - 920) / 920),
                "prior_advice_155_width_pixels": _round(
                    155 * meta_measurement["pixels_per_character"]),
                "prior_advice_155_desktop_budget_overshoot_fraction": _round(
                    (155 * meta_measurement["pixels_per_character"] - 920) / 920),
            },
            "arial_all_caps": {
                "pixels_per_character": caps_measurement["pixels_per_character"],
                "sixty_character_width_pixels": _round(
                    60 * caps_measurement["pixels_per_character"]),
            },
            "font_sensitivity": {
                "desktop_title_capacity_range": [
                    min(row["measurements"]["desktop_title"]["composition_mixes"]
                        ["ordinary_title_case"]["characters_budget_holds"]
                        for row in fonts),
                    max(row["measurements"]["desktop_title"]["composition_mixes"]
                        ["ordinary_title_case"]["characters_budget_holds"]
                        for row in fonts),
                ],
                "desktop_description_capacity_range": [
                    min(row["measurements"]["desktop_description"]["composition_mixes"]
                        [SELECTION_MIX]["characters_budget_holds"]
                        for row in fonts),
                    max(row["measurements"]["desktop_description"]["composition_mixes"]
                        [SELECTION_MIX]["characters_budget_holds"]
                        for row in fonts),
                ],
                "verdana_ordinary_description_capacity": verdana_description_capacity,
                "arial_is_bracketed": True,
                "wider_than_arial": "Verdana",
                "narrower_than_arial": "Times New Roman",
            },
        },
        "fonts": fonts,
    }


def write_report() -> int:
    report = build_report()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {REPORT}: {len(report['fonts'])} fonts, "
          f"{len(COMPOSITION_MIXES)} mixes, {len(SURFACES)} surfaces")
    for name in ("TITLE_MAX_CHARS", "META_MAX_CHARS"):
        row = report["constants"][name]
        print(f"{name}: constant={row['value']}; measured={row['recommended_value']}")
    return 0


def check_report() -> int:
    try:
        with open(REPORT, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable calibration report: {exc}", file=sys.stderr)
        return 1

    expected_inputs = report.get("inputs", {})
    input_agrees = (
        expected_inputs.get("pixel_budgets", {}).get("surfaces")
        == {row["name"]: row["budget_pixels"] for row in SURFACES}
        and expected_inputs.get("english_letter_frequency", {}).get("percentages")
        == ENGLISH_LETTER_FREQUENCY
        and expected_inputs.get("composition_mixes")
        == {row["name"]: {key: row[key]
                          for key in ("lowercase", "uppercase", "space")}
            for row in COMPOSITION_MIXES}
    )
    if not input_agrees:
        print("calibration report was produced from different declared inputs",
              file=sys.stderr)
        return 1

    constants = _offline_constants()
    report_constants = report.get("constants", {})
    failed = False
    for name in CONSTANT_NAMES:
        expected = report_constants.get(name, {}).get("value")
        actual = constants[name]
        agrees = actual == expected
        print(f"{name}: constant={actual}; report={expected}; "
              f"agree={'yes' if agrees else 'no'}")
        failed |= not agrees
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="compare the committed report with constants; no fonts or network")
    args = parser.parse_args()
    return check_report() if args.check else write_report()


if __name__ == "__main__":
    sys.exit(main())
