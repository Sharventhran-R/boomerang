"""Boomerang Missing/Found Matching Engine services.

Phase 8.2: Candidate retrieval via spatial PostGIS queries.
Phase 8.3: Deterministic, explainable match scoring engine.
"""

from app.services.matching.characteristics import compute_characteristics_score
from app.services.matching.distance import compute_distance_score
from app.services.matching.identity import compute_identity_score
from app.services.matching.models import (
    CharacteristicsBreakdown,
    DistanceBreakdown,
    IdentityBreakdown,
    MatchScoreResult,
    ScoreClassification,
    TimeBreakdown,
)
from app.services.matching.retrieval import (
    DEFAULT_CANDIDATE_LIMIT,
    MATCHING_RADIUS_METERS,
    MAX_CANDIDATE_LIMIT,
    CandidateMatch,
    retrieve_candidates,
)
from app.services.matching.scorer import score_candidate, score_candidates
from app.services.matching.time import compute_time_score

__all__ = [
    # Phase 8.2 Retrieval
    "DEFAULT_CANDIDATE_LIMIT",
    "MATCHING_RADIUS_METERS",
    "MAX_CANDIDATE_LIMIT",
    "CandidateMatch",
    "retrieve_candidates",
    # Phase 8.3 Scoring Models & Classifications
    "ScoreClassification",
    "IdentityBreakdown",
    "CharacteristicsBreakdown",
    "DistanceBreakdown",
    "TimeBreakdown",
    "MatchScoreResult",
    # Phase 8.3 Scorers
    "compute_identity_score",
    "compute_characteristics_score",
    "compute_distance_score",
    "compute_time_score",
    "score_candidate",
    "score_candidates",
]
