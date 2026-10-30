"""Unit and integration tests for Phase 8.3 Match Scoring Engine.

Tests all criteria specified in Phase 8.3 requirements and matching spec:
- Identity scoring (categories, brand/model, title nouns, stop words, OTHER)
- Characteristics scoring (colors, cases, accessories, marks, anti-sparse)
- Distance scoring (linear decay formula, boundary values, negative clamping)
- Time scoring (causality delta, brackets, negative deltas, neutral missing)
- Composite scoring & alert eligibility (weighting, penalties, bands)
- Specification benchmark cases TC-01 through TC-07
- Explainability output structure
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import Report, ReportCategory, ReportStatus, ReportType
from app.services.matching import (
    CandidateMatch,
    ScoreClassification,
    compute_characteristics_score,
    compute_distance_score,
    compute_identity_score,
    compute_time_score,
    score_candidate,
    score_candidates,
)

_TIME_SENTINEL = object()


def _make_report(
    report_type: ReportType = ReportType.MISSING,
    title: str = "Test Report Title",
    description: str = "A detailed test report description with enough words.",
    category: ReportCategory = ReportCategory.ELECTRONICS,
    event_time: datetime | None | object = _TIME_SENTINEL,
    report_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    status: ReportStatus = ReportStatus.ACTIVE,
    latitude: float = 37.7749,
    longitude: float = -122.4194,
) -> Report:
    """Helper to create an in-memory Report instance for unit testing."""
    actual_event_time: datetime | None
    if event_time is _TIME_SENTINEL:
        actual_event_time = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    else:
        actual_event_time = event_time  # type: ignore[assignment]

    rep = Report(
        id=report_id or uuid.uuid4(),
        created_by_user_id=user_id or uuid.uuid4(),
        type=report_type,
        title=title,
        description=description,
        category=category,
        event_time=actual_event_time,
        status=status,
    )
    setattr(rep, "latitude", latitude)
    setattr(rep, "longitude", longitude)
    return rep


# ==============================================================================
# 1. Identity Scoring Tests
# ==============================================================================


def test_exact_category_alignment() -> None:
    """Identical concrete categories award full 40.0 category points."""
    r1 = _make_report(category=ReportCategory.ELECTRONICS)
    r2 = _make_report(category=ReportCategory.ELECTRONICS)
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.category_score == 40.0
    assert breakdown.matched_category == "ELECTRONICS"
    assert not breakdown.is_other_cross_category


def test_incompatible_concrete_categories() -> None:
    """Different concrete categories receive 0.0 category points."""
    r1 = _make_report(category=ReportCategory.PET)
    r2 = _make_report(category=ReportCategory.ELECTRONICS)
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.category_score == 0.0
    assert breakdown.matched_category is None


def test_brand_and_model_token_overlap() -> None:
    """Matching brand and model from text awards full 40.0 brand/model points."""
    r1 = _make_report(
        title="Lost iPhone 15 Pro",
        description="Left my Apple iPhone 15 Pro on the cafe table.",
    )
    r2 = _make_report(
        title="Found iPhone 15 Pro",
        description="Found an Apple iPhone 15 Pro smartphone outside.",
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.matched_brand == "Apple"
    assert "Iphone 15 Pro" in (breakdown.matched_model or "")
    assert breakdown.brand_model_score == 40.0
    assert breakdown.score == 100.0  # 40 cat + 40 brand/model + 20 title noun


def test_brand_only_and_model_only() -> None:
    """Brand-only awards 25.0 pts; model-only awards 20.0 pts."""
    # Brand only: Sony headphones vs Sony camera
    r1 = _make_report(
        title="Lost Sony headphones",
        description="Black Sony over-ear headphones.",
    )
    r2 = _make_report(
        title="Found Sony gear",
        description="Found Sony electronics in the park.",
    )
    b_brand = compute_identity_score(r1, r2)
    assert b_brand.matched_brand == "Sony"
    assert b_brand.matched_model is None
    assert b_brand.brand_model_score == 25.0

    # Model only: alphanumeric model identifier without brand
    r3 = _make_report(
        title="Lost laptop A2179",
        description="Silver laptop A2179 left on train.",
    )
    r4 = _make_report(
        title="Found laptop A2179",
        description="A silver laptop A2179 found on seat.",
    )
    b_model = compute_identity_score(r3, r4)
    assert b_model.matched_model == "A2179"
    assert b_model.matched_brand is None
    assert b_model.brand_model_score == 20.0


def test_core_title_noun_alignment() -> None:
    """Matching primary title nouns awards full 20.0 title points."""
    r1 = _make_report(
        title="Navy leather wallet",
        description="Dark blue folding wallet with cards.",
        category=ReportCategory.WALLET,
    )
    r2 = _make_report(
        title="Brown leather wallet found",
        description="Found wallet with several store cards inside.",
        category=ReportCategory.WALLET,
    )
    breakdown = compute_identity_score(r1, r2)
    assert "wallet" in breakdown.matched_title_tokens
    assert breakdown.title_noun_score == 20.0


def test_generic_words_do_not_create_false_evidence() -> None:
    """Generic words award 0 brand/model/title points."""
    r1 = _make_report(
        title="Lost item please help",
        description="I lost my thing somewhere near the station, reward.",
        category=ReportCategory.OTHER,
    )
    r2 = _make_report(
        title="Found item anyone looking",
        description="Found a lost thing near the bus stop please contact.",
        category=ReportCategory.OTHER,
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.brand_model_score == 0.0
    assert breakdown.title_noun_score == 0.0
    assert breakdown.matched_brand is None
    assert breakdown.matched_model is None
    # Only OTHER category score (40)
    assert breakdown.score == 40.0


def test_missing_identity_information_is_neutral() -> None:
    """Reports with missing brand and model remain neutral."""
    r1 = _make_report(
        title="Lost backpack",
        description="Lost plain everyday backpack.",
        category=ReportCategory.BAG,
    )
    r2 = _make_report(
        title="Found backpack",
        description="Found a regular school backpack.",
        category=ReportCategory.BAG,
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.category_score == 40.0
    assert breakdown.brand_model_score == 0.0
    assert breakdown.title_noun_score == 20.0
    assert breakdown.score == 60.0


def test_other_matches_other_category() -> None:
    """OTHER matching OTHER receives full 40.0 category points."""
    r1 = _make_report(
        category=ReportCategory.OTHER,
        title="Lost acoustic guitar",
        description="Wooden acoustic guitar in soft black gig bag.",
    )
    r2 = _make_report(
        category=ReportCategory.OTHER,
        title="Found guitar",
        description="Found guitar left behind.",
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.category_score == 40.0
    assert not breakdown.is_other_cross_category
    assert breakdown.other_confidence_eligible


def test_other_cross_category_confidence_below_60() -> None:
    """OTHER vs specific category with I < 60 is flagged ineligible."""
    r1 = _make_report(
        category=ReportCategory.OTHER,
        title="Found electronic device",
        description="Found some device on the bench.",
    )
    r2 = _make_report(
        category=ReportCategory.ELECTRONICS,
        title="Lost Sony headphones",
        description="Lost Sony WH-1000XM4 noise cancelling headphones.",
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.is_other_cross_category
    # Category score is 15.0 fallback, no brand/model overlap -> I < 60.0
    assert breakdown.score < 60.0
    assert not breakdown.other_confidence_eligible


def test_other_cross_category_confidence_at_least_60() -> None:
    """OTHER vs specific category with strong brand overlap satisfies I >= 60."""
    r1 = _make_report(
        category=ReportCategory.OTHER,
        title="Found Apple iPad Pro",
        description="Found an Apple iPad Pro tablet left on the seat.",
    )
    r2 = _make_report(
        category=ReportCategory.ELECTRONICS,
        title="Lost Apple iPad Pro",
        description="Lost Apple iPad Pro 11-inch with cracked glass.",
    )
    breakdown = compute_identity_score(r1, r2)
    assert breakdown.is_other_cross_category
    # 15 category + 40 brand/model + 20 title noun = 75.0 >= 60.0
    assert breakdown.score >= 60.0
    assert breakdown.other_confidence_eligible


# ==============================================================================
# 2. Characteristics Scoring Tests
# ==============================================================================


def test_matching_colors_score() -> None:
    """Overlapping color descriptors award +30.0 points."""
    r1 = _make_report(description="Matte black folding bicycle with silver handles.")
    r2 = _make_report(description="Found black commuter bicycle in the alley.")
    breakdown = compute_characteristics_score(r1, r2)
    assert "black" in breakdown.matched_colors
    assert breakdown.score >= 30.0
    assert not breakdown.has_contradiction


def test_conflicting_colors_cap_and_contradiction() -> None:
    """Direct color contradiction caps C at 10 and sets contradiction."""
    r1 = _make_report(description="Neon green sports backpack with hydration pack.")
    r2 = _make_report(description="Jet black nylon backpack found near the gym.")
    breakdown = compute_characteristics_score(r1, r2)
    assert breakdown.has_contradiction
    assert breakdown.conflicting_colors
    assert breakdown.score <= 10.0


def test_matching_cases_and_accessories() -> None:
    """Matching cases (+25 pts) and accessories (+20 pts) accumulate points."""
    r1 = _make_report(
        description="Phone in clear silicone case with attached leather strap."
    )
    r2 = _make_report(
        description="Found device in clear case with a worn leather strap attached."
    )
    breakdown = compute_characteristics_score(r1, r2)
    assert "clear case" in breakdown.matched_cases
    assert "leather strap" in breakdown.matched_accessories
    assert breakdown.score >= 45.0
    assert not breakdown.has_contradiction


def test_distinctive_mark_matching() -> None:
    """Matching monograms or unique markings award +35.0 points."""
    r1 = _make_report(
        title="Navy wallet monogram 'AM'",
        description="Leather wallet with monogram 'AM' embossed on the corner.",
    )
    r2 = _make_report(
        title="Found leather wallet",
        description="Dark blue leather wallet with initials AM on the inside flap.",
    )
    breakdown = compute_characteristics_score(r1, r2)
    assert any("initials_am" in m for m in breakdown.matched_distinctive_marks)
    assert breakdown.score >= 35.0


def test_conflicting_mark_cap_and_contradiction() -> None:
    """Conflicting markings caps C at 0 and sets contradiction."""
    r1 = _make_report(
        description="Laptop with large Spider-Man sticker on the back cover."
    )
    r2 = _make_report(
        description="Clean case, no stickers, completely unmarked exterior."
    )
    breakdown = compute_characteristics_score(r1, r2)
    assert breakdown.has_contradiction
    assert breakdown.conflicting_marks
    assert breakdown.score <= 0.0


def test_sparse_descriptions_cap_at_20() -> None:
    """Descriptions under 15 characters cap C <= 20.0."""
    r1 = _make_report(
        title="Lost keys",
        description="Lost keys",  # 9 characters (< 15)
        category=ReportCategory.KEYS,
    )
    r2 = _make_report(
        title="Found keys",
        description="Found a set of keys on sidewalk.",
        category=ReportCategory.KEYS,
    )
    breakdown = compute_characteristics_score(r1, r2)
    assert breakdown.is_sparse
    assert breakdown.score <= 20.0


def test_missing_characteristics_remain_neutral() -> None:
    """When neither report mentions physical features, score is 0 with no conflict."""
    r1 = _make_report(
        description="Lost item around 4pm yesterday afternoon on 5th street."
    )
    r2 = _make_report(description="Found item on the sidewalk around 5pm yesterday.")
    breakdown = compute_characteristics_score(r1, r2)
    assert breakdown.score == 0.0
    assert not breakdown.has_contradiction
    assert not breakdown.is_sparse


def test_multiple_matching_physical_characteristics() -> None:
    """Multiple matching characteristics accumulate cleanly."""
    r1 = _make_report(
        description="Black phone in clear silicone case with carabiner attached."
    )
    r2 = _make_report(
        description="Black smartphone with clear case and carabiner clip."
    )
    breakdown = compute_characteristics_score(r1, r2)
    assert "black" in breakdown.matched_colors
    assert "clear case" in breakdown.matched_cases
    assert "carabiner" in breakdown.matched_accessories
    # 30 (color) + 25 (case) + 20 (accessory) = 75.0
    assert breakdown.score == 75.0


# ==============================================================================
# 3. Distance Scoring Tests
# ==============================================================================


def test_distance_scoring_benchmarks() -> None:
    """Verifies linear decay formula across 0km, 2.5km, 5km, and beyond."""
    # 0.0 km -> 100.0
    d0 = compute_distance_score(0.0)
    assert d0.score == 100.0
    assert d0.distance_km == 0.0

    # 1.0 km -> 80.0
    d1 = compute_distance_score(1000.0)
    assert d1.score == 80.0
    assert d1.distance_km == 1.0

    # 2.5 km -> 50.0
    d25 = compute_distance_score(2500.0)
    assert d25.score == 50.0
    assert d25.distance_km == 2.5

    # 5.0 km boundary -> exactly 0.0
    d50 = compute_distance_score(5000.0)
    assert d50.score == 0.0
    assert d50.distance_km == 5.0

    # > 5.0 km -> 0.0
    d60 = compute_distance_score(6000.0)
    assert d60.score == 0.0
    assert d60.distance_km == 6.0


def test_distance_scoring_negative_and_clamping() -> None:
    """Unexpected negative distances are clamped gracefully to 100.0."""
    dn = compute_distance_score(-100.0)
    assert dn.score == 100.0
    assert dn.distance_meters == 0.0
    assert dn.distance_km == 0.0


# ==============================================================================
# 4. Incident-Time Scoring Tests
# ==============================================================================


def test_time_scoring_gradual_negative_boundaries() -> None:
    """Verifies delta < -24h (T=0), delta=-24h (T=0), -12h (T=50), 0 (T=100)."""
    base_loss = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    # -48h -> T = 0.0
    t_neg48 = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss - timedelta(hours=48),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_neg48.score == 0.0
    assert t_neg48.is_negative_delta
    assert t_neg48.delta_hours == -48.0
    assert not t_neg48.is_missing_time

    # -24h boundary -> T = 0.0 (100 * (-24 + 24) / 24 = 0)
    t_neg24 = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss - timedelta(hours=24),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_neg24.score == 0.0
    assert t_neg24.is_negative_delta
    assert t_neg24.delta_hours == -24.0

    # -12h midpoint -> T = 50.0 (100 * (-12 + 24) / 24 = 50)
    t_neg12 = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss - timedelta(hours=12),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_neg12.score == 50.0
    assert t_neg12.is_negative_delta
    assert t_neg12.delta_hours == -12.0

    # 0h boundary -> T = 100.0
    t_zero = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss,
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_zero.score == 100.0
    assert not t_zero.is_negative_delta
    assert t_zero.delta_seconds == 0.0


def test_time_scoring_gradual_positive_interpolation() -> None:
    """Verifies 7d, 14d, 30d, 60d, 90d, 105d, 120d, 150d interpolation."""
    base_loss = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    # 7d -> T = 100.0
    t_7d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=7),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_7d.score == 100.0
    assert t_7d.delta_days == 7.0

    # 14d -> T = 100 - 80 * (7 / 83) ≈ 93.253012
    t_14d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=14),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    expected_14d = 100.0 - 80.0 * 7.0 / 83.0
    assert abs(t_14d.score - expected_14d) < 1e-5
    assert t_14d.delta_days == 14.0

    # 30d -> T = 100 - 80 * (23 / 83) ≈ 77.831325
    t_30d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=30),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    expected_30d = 100.0 - 80.0 * 23.0 / 83.0
    assert abs(t_30d.score - expected_30d) < 1e-5
    assert t_30d.delta_days == 30.0

    # 60d -> T = 100 - 80 * (53 / 83) ≈ 48.915663
    t_60d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=60),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    expected_60d = 100.0 - 80.0 * 53.0 / 83.0
    assert abs(t_60d.score - expected_60d) < 1e-5
    assert t_60d.delta_days == 60.0

    # 90d boundary -> T = 100 - 80 * (83 / 83) = 20.0
    t_90d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=90),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert abs(t_90d.score - 20.0) < 1e-5
    assert t_90d.delta_days == 90.0

    # 105d midpoint in 90-120d -> T = 20 * (15 / 30) = 10.0
    t_105d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=105),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert abs(t_105d.score - 10.0) < 1e-5
    assert t_105d.delta_days == 105.0

    # 120d boundary -> T = 20 * (0 / 30) = 0.0
    t_120d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=120),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_120d.score == 0.0
    assert t_120d.delta_days == 120.0

    # 150d beyond 120d -> T = 0.0
    t_150d = compute_time_score(
        source_event_time=base_loss,
        candidate_event_time=base_loss + timedelta(days=150),
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_150d.score == 0.0
    assert t_150d.delta_days == 150.0


def test_time_scoring_missing_timestamps_and_directions() -> None:
    """Verifies missing times and bidirectional invariance."""
    t_loss = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    t_found = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    # Missing missing-report time
    t_miss_missing = compute_time_score(
        source_event_time=None,
        candidate_event_time=t_found,
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_miss_missing.score == 50.0
    assert t_miss_missing.is_missing_time
    assert t_miss_missing.loss_time is None
    assert t_miss_missing.found_time == t_found

    # Missing found-report time
    t_miss_found = compute_time_score(
        source_event_time=t_loss,
        candidate_event_time=None,
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_miss_found.score == 50.0
    assert t_miss_found.is_missing_time
    assert t_miss_found.loss_time == t_loss
    assert t_miss_found.found_time is None

    # Bidirectional direction 1: source MISSING, candidate FOUND
    dir1 = compute_time_score(
        source_event_time=t_loss,
        candidate_event_time=t_found,
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    # Bidirectional direction 2: source FOUND, candidate MISSING
    dir2 = compute_time_score(
        source_event_time=t_found,
        candidate_event_time=t_loss,
        source_type=ReportType.FOUND,
        candidate_type=ReportType.MISSING,
    )
    assert dir1.score == dir2.score == 100.0
    assert dir1.delta_seconds == dir2.delta_seconds == 172800.0
    assert dir1.loss_time == dir2.loss_time == t_loss
    assert dir1.found_time == dir2.found_time == t_found


def test_time_scoring_timezone_handling() -> None:
    """Verifies timezone-aware offsets and validation rejection of naive timestamps."""
    from datetime import timezone

    import pytest

    # Timezone-aware with different UTC offsets (UTC vs UTC-5)
    tz_est = timezone(timedelta(hours=-5))
    loss_utc = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    found_est = datetime(
        2026, 10, 20, 12, 0, tzinfo=tz_est
    )  # 12:00 EST = 17:00 UTC (delta = +2h)

    t_aware = compute_time_score(
        source_event_time=loss_utc,
        candidate_event_time=found_est,
        source_type=ReportType.MISSING,
        candidate_type=ReportType.FOUND,
    )
    assert t_aware.score == 100.0
    assert t_aware.delta_hours == 2.0

    # Naive timestamp handling: raises ValueError
    naive_dt = datetime(2026, 10, 20, 15, 0)
    with pytest.raises(ValueError, match="must be timezone-aware"):
        compute_time_score(
            source_event_time=naive_dt,
            candidate_event_time=found_est,
            source_type=ReportType.MISSING,
            candidate_type=ReportType.FOUND,
        )

    with pytest.raises(ValueError, match="must be timezone-aware"):
        compute_time_score(
            source_event_time=loss_utc,
            candidate_event_time=naive_dt,
            source_type=ReportType.MISSING,
            candidate_type=ReportType.FOUND,
        )


# ==============================================================================
# 5. Composite Scoring & Eligibility Tests
# ==============================================================================


def test_composite_score_formula_and_weights() -> None:
    """Verifies S_raw = 0.30*I + 0.30*C + 0.25*D + 0.15*T."""
    r_missing = _make_report(
        report_type=ReportType.MISSING,
        title="Lost Apple iPhone 15 Pro",
        description="Black phone in clear silicone case with carabiner clip.",
        category=ReportCategory.ELECTRONICS,
        event_time=datetime(2026, 10, 28, 10, 0, tzinfo=UTC),
    )
    r_found = _make_report(
        report_type=ReportType.FOUND,
        title="Found Apple iPhone 15 Pro",
        description="Black phone in clear silicone case with carabiner clip.",
        category=ReportCategory.ELECTRONICS,
        event_time=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
    )
    cand = CandidateMatch(report=r_found, distance_meters=0.0)
    result = score_candidate(r_missing, cand)

    assert result.identity.score == 100.0
    assert result.characteristics.score == 75.0  # color 30 + case 25 + acc 20
    assert result.distance.score == 100.0
    assert result.time.score == 100.0

    # 30 + 22.5 + 25 + 15 = 92.5
    assert result.raw_composite_score == 92.5
    assert result.composite_score == 92.5
    assert result.classification == ScoreClassification.HIGH_PRIORITY
    assert result.alert_eligible


def test_contradiction_deducts_25_points_from_composite() -> None:
    """Contradiction penalty subtracts 25.0 points and disqualifies alert."""
    r_missing = _make_report(
        report_type=ReportType.MISSING,
        title="Lost iPhone 15 Pro",
        description="Neon green case on my iPhone 15 Pro.",
        category=ReportCategory.ELECTRONICS,
    )
    r_found = _make_report(
        report_type=ReportType.FOUND,
        title="Found iPhone 15 Pro",
        description="Jet black case on an iPhone 15 Pro.",
        category=ReportCategory.ELECTRONICS,
    )
    cand = CandidateMatch(report=r_found, distance_meters=500.0)
    result = score_candidate(r_missing, cand)

    assert result.characteristics.has_contradiction
    assert result.contradiction_penalty == 25.0
    assert (
        result.composite_score
        == result.raw_composite_score - result.contradiction_penalty
    )
    assert not result.alert_eligible
    assert any("contradictory" in r.lower() for r in result.ineligibility_reasons)


def test_classification_bands() -> None:
    """Verifies classification bands: HIGH, POSSIBLE, LOW, DISQUALIFIED."""
    r_m = _make_report(
        report_type=ReportType.MISSING,
        title="Lost Apple iPhone 15 Pro",
        description="Black phone in clear silicone case.",
    )
    r_f = _make_report(
        report_type=ReportType.FOUND,
        title="Found Apple iPhone 15 Pro",
        description="Black phone in clear case.",
    )
    res_high = score_candidate(r_m, CandidateMatch(report=r_f, distance_meters=500.0))
    assert res_high.composite_score >= 80.0
    assert res_high.classification == ScoreClassification.HIGH_PRIORITY

    # Disqualified / Suppressed: incompatible category and high distance
    r_unrelated = _make_report(
        report_type=ReportType.FOUND,
        title="Found gym bag",
        description="Old blue gym bag left in locker.",
        category=ReportCategory.BAG,
    )
    res_disq = score_candidate(
        r_m, CandidateMatch(report=r_unrelated, distance_meters=4500.0)
    )
    assert res_disq.composite_score < 40.0
    assert res_disq.classification == ScoreClassification.DISQUALIFIED


def test_alert_identity_guard_50() -> None:
    """Proximity and time alone cannot alert without identity evidence I >= 50."""
    r_m = _make_report(
        report_type=ReportType.MISSING,
        title="Lost thing",
        description="Lost something near the store yesterday.",
        category=ReportCategory.OTHER,
    )
    r_f = _make_report(
        report_type=ReportType.FOUND,
        title="Found item",
        description="Found something near the store yesterday.",
        category=ReportCategory.ELECTRONICS,
    )
    cand = CandidateMatch(report=r_f, distance_meters=0.0)
    result = score_candidate(r_m, cand)

    assert result.identity.score < 50.0
    assert not result.alert_eligible
    assert any("identity score" in r.lower() for r in result.ineligibility_reasons)


def test_minimum_evidence_alternatives() -> None:
    """Verifies the three minimum evidence alternatives for alerting."""
    # 1. Alternative A: Brand/Model with I >= 70
    r_a1 = _make_report(
        report_type=ReportType.MISSING,
        title="Lost Apple iPhone",
        description="Lost phone.",
    )
    r_a2 = _make_report(
        report_type=ReportType.FOUND,
        title="Found Apple iPhone",
        description="Found phone.",
    )
    res_a = score_candidate(r_a1, CandidateMatch(report=r_a2, distance_meters=0.0))
    assert res_a.identity.score >= 70.0
    assert res_a.minimum_evidence_satisfied

    # 2. Alternative B: At least 2 physical characteristics with C >= 60
    r_b1 = _make_report(
        report_type=ReportType.MISSING,
        title="Lost backpack",
        description="Navy blue backpack with a clear cover and leather strap.",
        category=ReportCategory.BAG,
    )
    r_b2 = _make_report(
        report_type=ReportType.FOUND,
        title="Found backpack",
        description="Navy blue backpack with a clear cover and leather strap.",
        category=ReportCategory.BAG,
    )
    res_b = score_candidate(r_b1, CandidateMatch(report=r_b2, distance_meters=0.0))
    assert res_b.characteristics.score >= 60.0
    assert res_b.minimum_evidence_satisfied

    # 3. Alternative C: Distinctive unique mark confirmed
    r_c1 = _make_report(
        report_type=ReportType.MISSING,
        title="Lost wallet monogram 'AM'",
        description="Leather wallet with monogram 'AM'.",
        category=ReportCategory.WALLET,
    )
    r_c2 = _make_report(
        report_type=ReportType.FOUND,
        title="Found wallet",
        description="Leather wallet with initials AM embossed.",
        category=ReportCategory.WALLET,
    )
    res_c = score_candidate(r_c1, CandidateMatch(report=r_c2, distance_meters=0.0))
    assert len(res_c.characteristics.matched_distinctive_marks) >= 1
    assert res_c.minimum_evidence_satisfied


def test_high_composite_score_with_insufficient_evidence_must_not_alert() -> None:
    """Proximity/time alone without brand/model/mark cannot alert."""
    r_m = _make_report(
        report_type=ReportType.MISSING,
        title="Lost keys",
        description="Lost standard set of house keys on sidewalk.",
        category=ReportCategory.KEYS,
    )
    r_f = _make_report(
        report_type=ReportType.FOUND,
        title="Found keys",
        description="Found a set of house keys on sidewalk.",
        category=ReportCategory.KEYS,
    )
    cand = CandidateMatch(report=r_f, distance_meters=0.0)
    result = score_candidate(r_m, cand)

    assert not result.alert_eligible
    assert not result.minimum_evidence_satisfied


def test_batch_scoring_helper() -> None:
    """score_candidates scores a list of candidates cleanly."""
    r_source = _make_report(report_type=ReportType.MISSING, title="Lost iPhone")
    cand1 = CandidateMatch(
        report=_make_report(report_type=ReportType.FOUND, title="Found iPhone"),
        distance_meters=200.0,
    )
    cand2 = CandidateMatch(
        report=_make_report(report_type=ReportType.FOUND, title="Found Android"),
        distance_meters=500.0,
    )
    results = score_candidates(r_source, [cand1, cand2])
    assert len(results) == 2
    assert results[0].candidate_id == cand1.candidate.id
    assert results[1].candidate_id == cand2.candidate.id


# ==============================================================================
# 6. Benchmark Reference Cases (docs/matching_specification.md Section 8.2)
# ==============================================================================


def test_benchmark_tc01_ideal_true_match() -> None:
    """TC-01: Ideal True Match (iPhone 15 Pro, clear case, 0.3 km, 1 hr)."""
    t_loss = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)
    t_found = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)  # 1 hour later

    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Black iPhone 15 Pro in clear case",
        description="Apple iPhone 15 Pro in clear silicone case.",
        category=ReportCategory.ELECTRONICS,
        event_time=t_loss,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="iPhone 15 Pro black titanium found on bench",
        description="Black iPhone 15 Pro with clear case.",
        category=ReportCategory.ELECTRONICS,
        event_time=t_found,
    )
    cand = CandidateMatch(report=found, distance_meters=300.0)  # 0.3 km
    res = score_candidate(missing, cand)

    assert res.composite_score >= 85.0
    assert res.classification == ScoreClassification.HIGH_PRIORITY
    assert res.alert_eligible
    assert res.minimum_evidence_satisfied


def test_benchmark_tc02_true_match_with_unique_mark() -> None:
    """TC-02: True Match with Unique Mark (Bellroy wallet monogram AM)."""
    t_loss = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    t_found = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)  # 24 hours later

    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Navy Bellroy leather wallet, monogram 'AM'",
        description="Dark blue Bellroy wallet with monogram 'AM' embossed.",
        category=ReportCategory.WALLET,
        event_time=t_loss,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="Leather wallet, dark blue, initials AM inside",
        description="Dark blue leather wallet with initials AM inside.",
        category=ReportCategory.WALLET,
        event_time=t_found,
    )
    cand = CandidateMatch(report=found, distance_meters=1200.0)  # 1.2 km
    res = score_candidate(missing, cand)

    assert res.composite_score >= 80.0
    assert res.classification == ScoreClassification.HIGH_PRIORITY
    assert res.alert_eligible
    assert any(
        "initials_am" in m for m in res.characteristics.matched_distinctive_marks
    )


def test_benchmark_tc03_nearby_unrelated_items() -> None:
    """TC-03: Nearby Unrelated Items (Wallet vs Bag, 0.1 km -> Mismatch)."""
    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Black leather wallet with cards",
        description="Lost black folding wallet with credit cards.",
        category=ReportCategory.WALLET,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="Black nylon gym bag with shoes",
        description="Found black gym bag containing shoes.",
        category=ReportCategory.BAG,
    )
    cand = CandidateMatch(report=found, distance_meters=100.0)  # 0.1 km
    res = score_candidate(missing, cand)

    assert res.identity.category_score == 0.0
    assert res.identity.score == 0.0
    assert not res.alert_eligible
    assert res.classification in (
        ScoreClassification.DISQUALIFIED,
        ScoreClassification.LOW_CONFIDENCE,
    )


def test_benchmark_tc04_identical_item_far_apart_in_time() -> None:
    """TC-04: Identical Item Far Apart in Time (AirPods Pro, 5 months apart)."""
    t_loss = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    t_found = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # >90 days -> T=10

    missing = _make_report(
        report_type=ReportType.MISSING,
        title="White AirPods Pro 2nd Gen",
        description="Lost white AirPods Pro in case.",
        category=ReportCategory.ELECTRONICS,
        event_time=t_loss,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="AirPods Pro 2nd Gen white case",
        description="Found AirPods Pro 2nd Gen charging case on bench.",
        category=ReportCategory.ELECTRONICS,
        event_time=t_found,
    )
    cand = CandidateMatch(report=found, distance_meters=500.0)  # 0.5 km
    res = score_candidate(missing, cand)

    assert res.time.score == 0.0  # >120 days -> T = 0.0
    assert 50.0 <= res.composite_score <= 75.0
    assert not res.alert_eligible


def test_benchmark_tc05_sparse_incomplete_descriptions() -> None:
    """TC-05: Sparse Incomplete Descriptions ('Lost keys' -> Alert = False)."""
    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Lost keys",
        description="Lost keys",  # Sparse (<15 chars)
        category=ReportCategory.KEYS,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="Found a set of keys",
        description="Found a set of keys on sidewalk.",
        category=ReportCategory.KEYS,
    )
    cand = CandidateMatch(report=found, distance_meters=400.0)
    res = score_candidate(missing, cand)

    assert res.characteristics.is_sparse
    assert res.characteristics.score <= 20.0
    assert not res.alert_eligible


def test_benchmark_tc06_missing_incident_time() -> None:
    """TC-06: Missing / Approximate Incident Time (Missing cat -> T=50)."""
    found = _make_report(
        report_type=ReportType.FOUND,
        title="Tuxedo cat with white paws",
        description="Found tuxedo cat with white paws.",
        category=ReportCategory.PET,
        event_time=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
    )
    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Black cat with white paws",
        description="Lost cat with white paws, unknown time.",
        category=ReportCategory.PET,
        event_time=None,  # Missing incident time
    )
    cand = CandidateMatch(report=found, distance_meters=800.0)
    res = score_candidate(missing, cand)

    assert res.time.score == 50.0  # Neutral default
    assert res.classification == ScoreClassification.POSSIBLE_MATCH


def test_benchmark_tc07_direct_color_contradiction() -> None:
    """TC-07: Direct Color Contradiction (Golden vs Black -> S < 45)."""
    missing = _make_report(
        report_type=ReportType.MISSING,
        title="Golden Retriever with red collar",
        description="Friendly golden retriever dog wearing a red collar.",
        category=ReportCategory.PET,
    )
    found = _make_report(
        report_type=ReportType.FOUND,
        title="Black Labrador with red collar",
        description="Found black labrador dog with red collar.",
        category=ReportCategory.PET,
    )
    cand = CandidateMatch(report=found, distance_meters=500.0)
    res = score_candidate(missing, cand)

    assert res.characteristics.has_contradiction
    assert res.contradiction_penalty == 25.0
    assert res.composite_score < 45.0
    assert not res.alert_eligible
