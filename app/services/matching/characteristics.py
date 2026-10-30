"""Physical characteristics scoring for Boomerang Matching Engine (Phase 8.3).

Formalized in docs/matching_specification.md (Phase 8.1, Section 4.1 & 5).
Computes Signal C (Physical Characteristics) using:
- Color overlap and conflict detection
- Protective covers & accessories
- Distinctive markings, scratches, monograms, and stickers
- Anti-sparse description guards (descriptions < 15 chars capped at C <= 20)
- Contradiction detection (conflicts cap C at 0-10 and trigger composite deduction)
"""

from __future__ import annotations

import re
from typing import Final

from app.db.models import Report
from app.services.matching.models import CharacteristicsBreakdown

# Color tokens and common color compounds
KNOWN_COLORS: Final[tuple[str, ...]] = (
    "matte black",
    "jet black",
    "space gray",
    "space grey",
    "navy blue",
    "dark blue",
    "rose gold",
    "neon green",
    "golden",
    "gold",
    "silver",
    "black",
    "white",
    "red",
    "blue",
    "navy",
    "green",
    "yellow",
    "gray",
    "grey",
    "brown",
    "purple",
    "pink",
    "orange",
    "beige",
    "tan",
    "clear",
    "transparent",
    "tuxedo",
)

# Primary body and coat colors where mismatches indicate direct contradiction
PRIMARY_BODY_COLORS: Final[frozenset[str]] = frozenset(
    {
        "golden",
        "gold",
        "black",
        "white",
        "brown",
        "yellow",
        "neon green",
        "silver",
        "purple",
        "pink",
        "orange",
    }
)

# Common protective covers, cases, and materials
KNOWN_CASES: Final[tuple[str, ...]] = (
    "clear silicone case",
    "silicone case",
    "clear case",
    "leather case",
    "leather strap",
    "leather wallet",
    "leather",
    "otterbox case",
    "otterbox",
    "wallet case",
    "clear cover",
    "case",
    "cover",
    "sleeve",
    "folio",
    "bumper",
)

# Accessories attached to items
KNOWN_ACCESSORIES: Final[tuple[str, ...]] = (
    "leather strap",
    "red collar",
    "blue collar",
    "strap",
    "keychain",
    "carabiner",
    "charm",
    "lanyard",
    "collar",
    "pop socket",
    "screen protector",
    "cable",
    "tag",
)

# Unique physical markings, damage, or customizations
DISTINCTIVE_MARK_PATTERNS: Final[tuple[str, ...]] = (
    r"monogram\s+['\"]?([a-z0-9]+)['\"]?",
    r"initials?\s+['\"]?([a-z0-9]+)['\"]?",
    r"engrav(?:ed|ing)\s+['\"]?([a-z0-9\s]+)['\"]?",
    r"spider[-\s]man\s+sticker",
    r"sticker[s]?",
    r"scratch(?:es|ed)?",
    r"cracked\s+screen",
    r"broken\s+corner",
    r"dent(?:s|ed)?",
    r"white\s+paws",
    r"rhinestone",
)


def _extract_colors(text: str) -> set[str]:
    """Extracts normalized color descriptors from text."""
    lower = text.lower()
    found: set[str] = set()
    for color in KNOWN_COLORS:
        pattern = rf"\b{re.escape(color)}\b"
        if re.search(pattern, lower):
            # Normalize synonyms
            norm = "gray" if color == "grey" else color
            norm = "black" if norm in ("matte black", "jet black") else norm
            norm = "blue" if norm in ("navy blue", "dark blue", "navy") else norm
            found.add(norm)
    return found


def _extract_cases(text: str) -> set[str]:
    """Extracts normalized case/cover/material descriptors from text."""
    lower = text.lower()
    found: set[str] = set()
    for case in KNOWN_CASES:
        pattern = rf"\b{re.escape(case)}\b"
        if re.search(pattern, lower):
            norm = "clear case" if "clear" in case else case
            found.add(norm)
    return found


def _extract_accessories(text: str) -> set[str]:
    """Extracts accessory terms from text."""
    lower = text.lower()
    found: set[str] = set()
    for acc in KNOWN_ACCESSORIES:
        pattern = rf"\b{re.escape(acc)}\b"
        if re.search(pattern, lower):
            found.add(acc)
    return found


def _extract_distinctive_marks(text: str) -> set[str]:
    """Extracts unique distinctive marks, initials, monograms, or wear."""
    lower = text.lower()
    found: set[str] = set()

    # Check monogram or initials (e.g. monogram 'AM', initials AM)
    init_match = re.search(r"(?:monogram|initials?)\s+['\"]?([a-z]{1,4})['\"]?", lower)
    if init_match:
        found.add(f"initials_{init_match.group(1)}")

    for pat in DISTINCTIVE_MARK_PATTERNS:
        m = re.search(pat, lower)
        if m:
            clean_term = re.sub(r"[^a-z0-9]", "_", m.group(0).strip())
            found.add(clean_term)

    return found


def compute_characteristics_score(
    source: Report,
    candidate: Report,
) -> CharacteristicsBreakdown:
    """Computes physical characteristics score C in [0.0, 100.0].

    Rules & Evidence Contributions:
    - Color Overlap: +30.0 pts.
    - Case/Cover/Material Overlap: +25.0 pts.
    - Accessory Overlap: +20.0 pts.
    - Distinctive Mark/Monogram Overlap: +35.0 pts.
    - Neutral Missing: Missing attributes do not penalize down to zero, but award 0 pts.

    Anti-Sparse Guard:
    - Descriptions shorter than 15 characters or fewer than 3 tokens cap C <= 20.0.

    Contradiction Detection:
    - Conflicting primary colors (e.g. Golden vs Black) cap C <= 10.0.
    - Conflicting marks (e.g. sticker vs clean case / no stickers) cap C <= 0.0.
    - Triggers has_contradiction = True, which applies 25 pt composite deduction.

    Args:
        source: Source Report.
        candidate: Candidate Report.

    Returns:
        CharacteristicsBreakdown with bounded score in [0.0, 100.0].
    """
    source_text = f"{source.title} {source.description}".lower()
    cand_text = f"{candidate.title} {candidate.description}".lower()

    # 1. Anti-sparse check
    s_desc = source.description.strip()
    c_desc = candidate.description.strip()
    is_sparse = (
        len(s_desc) < 15
        or len(c_desc) < 15
        or len(s_desc.split()) < 3
        or len(c_desc.split()) < 3
    )

    # 2. Extract characteristics
    s_colors = _extract_colors(source_text)
    c_colors = _extract_colors(cand_text)

    s_cases = _extract_cases(source_text)
    c_cases = _extract_cases(cand_text)

    s_accessories = _extract_accessories(source_text)
    c_accessories = _extract_accessories(cand_text)

    s_marks = _extract_distinctive_marks(source_text)
    c_marks = _extract_distinctive_marks(cand_text)

    # 3. Detect matching attributes
    matched_colors = sorted(s_colors & c_colors)
    matched_cases = sorted(s_cases & c_cases)
    matched_accessories = sorted(s_accessories & c_accessories)
    matched_marks = sorted(s_marks & c_marks)

    # 4. Detect contradictions
    conflicting_colors: list[str] = []
    conflicting_marks: list[str] = []
    has_contradiction = False

    # Primary coat / body color conflict (e.g. Golden vs Black)
    s_primary = s_colors & PRIMARY_BODY_COLORS
    c_primary = c_colors & PRIMARY_BODY_COLORS
    if s_primary and c_primary and not (s_primary & c_primary):
        has_contradiction = True
        conflicting_colors = [f"{sorted(s_primary)} vs {sorted(c_primary)}"]
    elif s_colors and c_colors and not matched_colors:
        # General color conflict when zero colors overlap
        non_clear_s = s_colors - {"clear", "transparent"}
        non_clear_c = c_colors - {"clear", "transparent"}
        if non_clear_s and non_clear_c:
            has_contradiction = True
            conflicting_colors = [f"{sorted(non_clear_s)} vs {sorted(non_clear_c)}"]

    # Mark conflict: e.g. "no stickers" / "clean case" vs "sticker"
    s_has_sticker = any("sticker" in m for m in s_marks)
    c_has_sticker = any("sticker" in m for m in c_marks)
    s_clean = "no sticker" in source_text or "clean case" in source_text
    c_clean = "no sticker" in cand_text or "clean case" in cand_text

    if (s_has_sticker and c_clean) or (c_has_sticker and s_clean):
        has_contradiction = True
        conflicting_marks = ["sticker vs clean/no stickers"]

    # 5. Compute raw positive score
    score: float = 0.0
    if matched_colors:
        score += 30.0
    if matched_cases:
        score += 25.0
    if matched_accessories:
        score += 20.0
    if matched_marks:
        score += 35.0

    # 6. Apply caps (contradictions and anti-sparse)
    if conflicting_marks:
        score = min(score, 0.0)
    elif conflicting_colors:
        score = min(score, 10.0)
    elif is_sparse:
        score = min(score, 20.0)

    # Final clamp to [0.0, 100.0]
    final_score = max(0.0, min(100.0, score))

    return CharacteristicsBreakdown(
        score=final_score,
        matched_colors=matched_colors,
        conflicting_colors=conflicting_colors,
        matched_cases=matched_cases,
        matched_accessories=matched_accessories,
        matched_distinctive_marks=matched_marks,
        conflicting_marks=conflicting_marks,
        is_sparse=is_sparse,
        has_contradiction=has_contradiction,
    )
