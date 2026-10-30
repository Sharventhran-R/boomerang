"""Identity scoring engine for Boomerang Matching Engine (Phase 8.3).

Formalized in docs/matching_specification.md (Phase 8.1, Section 4.1).
Computes Signal I (Item Identity) using:
- Category alignment (40% of I)
- Brand and model token matching (40% of I)
- Core title noun alignment (20% of I)
"""

from __future__ import annotations

import re
from typing import Final

from app.db.models import Report, ReportCategory
from app.services.matching.models import IdentityBreakdown

# Words that should never count as brand, model, or core distinctive tokens
GENERIC_STOP_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "out",
        "please",
        "reward",
        "she",
        "so",
        "some",
        "someone",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "were",
        "with",
        "you",
        "your",
        "item",
        "thing",
        "things",
        "lost",
        "found",
        "missing",
        "stolen",
        "anyone",
        "looking",
        "somewhere",
        "anywhere",
        "help",
        "near",
    }
)

# Colors that belong to characteristics, never title nouns
TITLE_COLOR_WORDS: Final[frozenset[str]] = frozenset(
    {
        "black",
        "white",
        "red",
        "blue",
        "green",
        "yellow",
        "silver",
        "gold",
        "golden",
        "gray",
        "grey",
        "brown",
        "purple",
        "pink",
        "orange",
        "navy",
        "matte",
        "jet",
        "space",
        "rose",
        "beige",
        "tan",
        "clear",
        "transparent",
        "tuxedo",
        "titanium",
    }
)

# Curated reference brands across common report categories
KNOWN_BRANDS: Final[frozenset[str]] = frozenset(
    {
        # Electronics
        "apple",
        "samsung",
        "sony",
        "google",
        "dell",
        "lenovo",
        "hp",
        "asus",
        "acer",
        "bose",
        "nintendo",
        "playstation",
        "xbox",
        "kindle",
        "garmin",
        "fitbit",
        "canon",
        "nikon",
        "lg",
        "motorola",
        "oneplus",
        "xiaomi",
        "huawei",
        "anker",
        "beats",
        "sennheiser",
        "jbl",
        "logitech",
        "microsoft",
        "gopro",
        # Bags, Wallets & Clothing
        "bellroy",
        "coach",
        "gucci",
        "prada",
        "louis vuitton",
        "michael kors",
        "herschel",
        "samsonite",
        "tumi",
        "north face",
        "patagonia",
        "nike",
        "adidas",
        "puma",
        "lululemon",
        "zara",
        "uniqlo",
        "fossil",
        "ridge",
        # Jewelry & Watches
        "rolex",
        "omega",
        "casio",
        "g-shock",
        "seiko",
        "tissot",
        "cartier",
        "tiffany",
        "pandora",
        "swarovski",
        "tag heuer",
        # Vehicles
        "trek",
        "giant",
        "specialized",
        "cannondale",
        "honda",
        "toyota",
        "ford",
        "bmw",
        "subaru",
        "tesla",
        "yamaha",
        "brompton",
    }
)

# Key model identifiers and model series
KNOWN_MODELS: Final[frozenset[str]] = frozenset(
    {
        "iphone",
        "ipad",
        "macbook",
        "airpods",
        "airpods pro",
        "galaxy",
        "pixel",
        "thinkpad",
        "switch",
        "quietcomfort",
        "wh-1000xm4",
        "wh-1000xm5",
        "surface",
        "playstation 5",
        "ps5",
        "xbox series",
    }
)

# Implicit brand association for flagship models
MODEL_TO_BRAND: Final[dict[str, str]] = {
    "iphone": "Apple",
    "ipad": "Apple",
    "macbook": "Apple",
    "airpods": "Apple",
    "galaxy": "Samsung",
    "pixel": "Google",
    "thinkpad": "Lenovo",
    "switch": "Nintendo",
    "quietcomfort": "Bose",
    "wh-1000xm4": "Sony",
    "wh-1000xm5": "Sony",
    "playstation": "Sony",
    "ps5": "Sony",
    "surface": "Microsoft",
}

# Common core title nouns representing primary objects
CORE_TITLE_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "wallet",
        "keys",
        "keychain",
        "phone",
        "smartphone",
        "iphone",
        "ipad",
        "macbook",
        "airpods",
        "bag",
        "backpack",
        "purse",
        "handbag",
        "watch",
        "smartwatch",
        "jacket",
        "coat",
        "ring",
        "necklace",
        "bracelet",
        "passport",
        "id",
        "card",
        "license",
        "headphones",
        "earbuds",
        "laptop",
        "computer",
        "camera",
        "dog",
        "cat",
        "puppy",
        "kitten",
        "bicycle",
        "bike",
        "scooter",
        "glasses",
        "sunglasses",
        "umbrella",
        "airtag",
        "leather",
    }
)


def normalize_text_tokens(text: str) -> list[str]:
    """Normalizes text: lowers case, removes punctuation, splits on whitespace."""
    text_lower = text.lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text_lower)
    return [t for t in cleaned.split() if t]


def extract_matched_brand(text_a: str, text_b: str) -> str | None:
    """Finds matching known brand name mentioned in both texts."""
    lower_a = text_a.lower()
    lower_b = text_b.lower()
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", lower_a) and re.search(
            rf"\b{re.escape(brand)}\b", lower_b
        ):
            return brand.title()
    return None


def extract_matched_model(text_a: str, text_b: str) -> str | None:
    """Finds matching model names or multi-token model designations in both texts."""
    lower_a = text_a.lower()
    lower_b = text_b.lower()

    # 1. Check known model series first
    for model in sorted(KNOWN_MODELS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(model)}\b", lower_a) and re.search(
            rf"\b{re.escape(model)}\b", lower_b
        ):
            # Check for specific version suffix (e.g., "15 pro", "s23", "2nd gen")
            m_a = re.search(
                rf"\b{re.escape(model)}\s+([a-z0-9]+(?:\s+[a-z0-9]+)?)\b",
                lower_a,
            )
            m_b = re.search(
                rf"\b{re.escape(model)}\s+([a-z0-9]+(?:\s+[a-z0-9]+)?)\b",
                lower_b,
            )
            if m_a and m_b and m_a.group(1) == m_b.group(1):
                return f"{model.title()} {m_a.group(1).title()}"
            return model.title()

    # 2. Check monogram or initials overlap (e.g. monogram 'AM', initials AM)
    mono_a = re.search(r"(?:monogram|initials?)\s+['\"]?([a-z]{1,4})['\"]?", lower_a)
    mono_b = re.search(r"(?:monogram|initials?)\s+['\"]?([a-z]{1,4})['\"]?", lower_b)
    if mono_a and mono_b and mono_a.group(1) == mono_b.group(1):
        return f"Monogram {mono_a.group(1).upper()}"

    # 3. Check alphanumeric pattern model overlap (e.g. "qc45", "a2179", "wh1000xm4")
    tokens_a = set(normalize_text_tokens(text_a)) - GENERIC_STOP_WORDS
    tokens_b = set(normalize_text_tokens(text_b)) - GENERIC_STOP_WORDS
    alpha_num_overlap = [
        t
        for t in (tokens_a & tokens_b)
        if re.search(r"[a-z]", t) and re.search(r"[0-9]", t)
    ]
    if alpha_num_overlap:
        return alpha_num_overlap[0].upper()

    return None


def compute_identity_score(
    source: Report,
    candidate: Report,
) -> IdentityBreakdown:
    """Computes identity similarity score I in [0.0, 100.0].

    Components:
    - Category Alignment (40%):
      - Identical category: 40.0 pts.
      - OTHER vs OTHER: 40.0 pts.
      - OTHER vs specific category: 15.0 pts (fallback).
      - Incompatible concrete categories: 0.0 pts (and zeroes entire I).
    - Brand / Model Matching (40%):
      - Brand + Model match (or complete flagship model series): 40.0 pts.
      - Brand only match: 25.0 pts.
      - Generic model only match: 20.0 pts.
      - No brand/model evidence: 0.0 pts.
    - Core Title Noun Alignment (20%):
      - Extracted non-generic title nouns overlap up to 20.0 pts.

    Cross-Category Rule for OTHER:
    - If comparing OTHER with a specific category, requires I >= 60.0 to be eligible.

    Args:
        source: Source Report.
        candidate: Candidate Report.

    Returns:
        IdentityBreakdown with bounded score in [0.0, 100.0] and detailed signals.
    """
    # 1. Category Alignment (max 40.0)
    category_score: float = 0.0
    matched_category: str | None = None
    is_other_cross: bool = False

    if source.category == candidate.category:
        category_score = 40.0
        matched_category = source.category.value
    elif (
        source.category == ReportCategory.OTHER
        or candidate.category == ReportCategory.OTHER
    ):
        category_score = 15.0
        matched_category = "OTHER"
        is_other_cross = True
    else:
        # Incompatible concrete categories are strictly mutually exclusive
        return IdentityBreakdown(
            score=0.0,
            category_score=0.0,
            brand_model_score=0.0,
            title_noun_score=0.0,
            matched_category=None,
            matched_brand=None,
            matched_model=None,
            matched_title_tokens=[],
            is_other_cross_category=False,
            other_confidence_eligible=True,
        )

    # Combine title and description for comprehensive text matching
    source_full_text = f"{source.title} {source.description}"
    candidate_full_text = f"{candidate.title} {candidate.description}"

    # 2. Brand & Model Token Overlap (max 40.0)
    matched_brand = extract_matched_brand(source_full_text, candidate_full_text)
    matched_model = extract_matched_model(source_full_text, candidate_full_text)

    # Infer implicit brand from model if brand was not explicitly mentioned twice
    if matched_model and not matched_brand:
        model_lower = matched_model.lower()
        for mod_prefix, br_name in MODEL_TO_BRAND.items():
            if mod_prefix in model_lower:
                matched_brand = br_name
                break

    brand_model_score: float = 0.0
    if matched_brand and matched_model:
        brand_model_score = 40.0
    elif matched_model and " " in matched_model:
        # Multi-token specific model designation (e.g. "Iphone 15 Pro", "Airpods Pro")
        brand_model_score = 40.0
    elif matched_brand and not matched_model:
        brand_model_score = 25.0
    elif matched_model and not matched_brand:
        brand_model_score = 20.0
    else:
        brand_model_score = 0.0

    # 3. Core Title Noun Alignment (max 20.0)
    source_title_tokens = (
        set(normalize_text_tokens(source.title))
        - GENERIC_STOP_WORDS
        - TITLE_COLOR_WORDS
    )
    cand_title_tokens = (
        set(normalize_text_tokens(candidate.title))
        - GENERIC_STOP_WORDS
        - TITLE_COLOR_WORDS
    )

    # Filter to recognizable object nouns or substantive non-generic tokens
    matched_title_nouns = [
        t
        for t in (source_title_tokens & cand_title_tokens)
        if t in CORE_TITLE_NOUNS
        or (len(t) >= 4 and t not in GENERIC_STOP_WORDS and t not in TITLE_COLOR_WORDS)
    ]

    title_noun_score: float = 0.0
    if matched_title_nouns:
        if any(t in CORE_TITLE_NOUNS for t in matched_title_nouns):
            title_noun_score = 20.0
        else:
            title_noun_score = min(20.0, 10.0 * len(matched_title_nouns))

    # Total score bounded to [0.0, 100.0]
    total_score = min(100.0, category_score + brand_model_score + title_noun_score)

    # Cross-category OTHER rule: I >= 60.0 required
    other_confidence_eligible = (total_score >= 60.0) if is_other_cross else True

    return IdentityBreakdown(
        score=total_score,
        category_score=category_score,
        brand_model_score=brand_model_score,
        title_noun_score=title_noun_score,
        matched_category=matched_category,
        matched_brand=matched_brand,
        matched_model=matched_model,
        matched_title_tokens=matched_title_nouns,
        is_other_cross_category=is_other_cross,
        other_confidence_eligible=other_confidence_eligible,
    )
