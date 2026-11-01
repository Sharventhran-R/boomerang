"""Database-backed match persistence service for Boomerang (Phase 8.5).

Formalized in docs/matching_specification.md (Phase 8.1 & 8.5).
Replaces the temporary InMemoryMatchResultHandoff with durable PostgreSQL-backed
persistence.

Guarantees:
- Strict canonical report-pair validation (Missing report always in report_missing_id).
- Terminal lifecycle state protection (RESOLVED and CANCELLED/EXPIRED matches cannot
  be silently reactivated).
- Score >= 40 persistence policy: new candidate pairs scoring < 40 are not inserted;
  existing matches rescored < 40 transition to SUPPRESSED while preserving history.
- Concurrency-safe atomic upsert via PostgreSQL ON CONFLICT DO UPDATE with
  deterministic pair ordering and database-level terminal state guards.
- Atomic execution within the enclosing EventConsumer transaction boundary.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Match,
    MatchStatus,
    Report,
    ReportCategory,
    ReportStatus,
    ReportType,
)
from app.services.matching.models import MatchScoreResult
from app.services.matching.retrieval import MATCHING_RADIUS_METERS

logger = logging.getLogger(__name__)

SCORING_VERSION_V1: int = 1
PERSISTENCE_SCORE_THRESHOLD: float = 40.0


class MatchIntegrityError(ValueError):
    """Raised when candidate match pairs violate canonical or referential integrity."""


def serialize_explainability(result: MatchScoreResult) -> dict[str, Any]:
    """Serializes structured scoring breakdowns into JSONB-compatible dictionary."""
    return {
        "identity": {
            "score": result.identity.score,
            "category_score": result.identity.category_score,
            "brand_model_score": result.identity.brand_model_score,
            "title_noun_score": result.identity.title_noun_score,
            "matched_category": result.identity.matched_category,
            "matched_brand": result.identity.matched_brand,
            "matched_model": result.identity.matched_model,
            "matched_title_tokens": list(result.identity.matched_title_tokens),
            "is_other_cross_category": result.identity.is_other_cross_category,
            "other_confidence_eligible": result.identity.other_confidence_eligible,
        },
        "characteristics": {
            "score": result.characteristics.score,
            "matched_colors": list(result.characteristics.matched_colors),
            "conflicting_colors": list(result.characteristics.conflicting_colors),
            "matched_cases": list(result.characteristics.matched_cases),
            "matched_accessories": list(result.characteristics.matched_accessories),
            "matched_distinctive_marks": list(
                result.characteristics.matched_distinctive_marks
            ),
            "conflicting_marks": list(result.characteristics.conflicting_marks),
            "is_sparse": result.characteristics.is_sparse,
            "has_contradiction": result.characteristics.has_contradiction,
        },
        "distance": {
            "score": result.distance.score,
            "distance_meters": result.distance.distance_meters,
            "distance_km": result.distance.distance_km,
        },
        "time": {
            "score": result.time.score,
            "loss_time": (
                result.time.loss_time.isoformat()
                if result.time.loss_time is not None
                else None
            ),
            "found_time": (
                result.time.found_time.isoformat()
                if result.time.found_time is not None
                else None
            ),
            "delta_seconds": result.time.delta_seconds,
            "delta_hours": result.time.delta_hours,
            "delta_days": result.time.delta_days,
            "is_negative_delta": result.time.is_negative_delta,
            "is_missing_time": result.time.is_missing_time,
        },
        "ineligibility_reasons": list(result.ineligibility_reasons),
    }


class MatchPersistenceService:
    """PostgreSQL-backed persistence service implementing MatchResultHandoff."""

    def __init__(self, scoring_version: int = SCORING_VERSION_V1) -> None:
        self._scoring_version = scoring_version

    @property
    def scoring_version(self) -> int:
        return self._scoring_version

    async def record_matches(
        self,
        source_report: Report,
        results: list[MatchScoreResult],
        session: AsyncSession,
    ) -> None:
        """Persists scored match candidates into PostgreSQL.

        Enforces:
        - Canonical pair ordering: MISSING report is always report_missing_id.
        - Strict type validation: exactly one MISSING and one FOUND.
        - Score >= 40 threshold for new candidates; < 40 discards without DB insert.
        - Rescoring demotion: existing matches falling < 40 transition to SUPPRESSED.
        - Hard-filter disqualification: existing active matches no longer returned
          transition to DISQUALIFIED.
        - Terminal-state protection: RESOLVED matches cannot be reactivated.
        - Concurrency protection: verifies authoritative report statuses under
          row-level locks (FOR SHARE) and enforces DB-level conditional upsert.
        """
        source_id = source_report.id
        source_type = source_report.type

        # 1. Lock and fetch authoritative statuses for all involved reports
        all_candidate_ids = {res.candidate_id for res in results}
        all_report_ids = sorted(list({source_id} | all_candidate_ids))

        rep_stmt = (
            select(
                Report.id,
                Report.status,
                Report.type,
                Report.category,
                Report.created_by_user_id,
                Report.location,
            )
            .where(Report.id.in_(all_report_ids))
            .with_for_update(read=True)
            .order_by(Report.id)
        )
        rep_res = await session.execute(rep_stmt)
        authoritative_reports = {row.id: row for row in rep_res.all()}

        # Verify source report exists in DB
        if source_id not in authoritative_reports:
            logger.warning("Source report %s not found in database", source_id)
            return

        source_status = authoritative_reports[source_id].status

        # If source report is in a terminal lifecycle state, cascade and exit
        if source_status == ReportStatus.RESOLVED:
            logger.info(
                "Source report %s is RESOLVED; resolving existing matches.",
                source_id,
            )
            await self.resolve_matches_for_report(source_id, session)
            return
        elif source_status in (ReportStatus.CANCELLED, ReportStatus.EXPIRED):
            logger.info(
                "Source report %s is %s; disqualifying existing matches.",
                source_id,
                source_status,
            )
            await self.disqualify_matches_for_report(source_id, session)
            return
        elif source_status != ReportStatus.ACTIVE:
            logger.warning(
                "Source report %s has non-active status %s; skipping matching.",
                source_id,
                source_status,
            )
            return

        # 2. Query existing matches involving this source
        existing_stmt = select(
            Match.id,
            Match.report_missing_id,
            Match.report_found_id,
            Match.status,
            Match.composite_score,
        ).where(
            or_(
                Match.report_missing_id == source_id,
                Match.report_found_id == source_id,
            )
        )
        existing_res = await session.execute(existing_stmt)
        existing_matches = {
            (row.report_missing_id, row.report_found_id): row
            for row in existing_res.all()
        }

        # 3. Collect candidates and build upsert payloads
        to_upsert: list[dict[str, Any]] = []
        scored_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()

        now = func.now()

        for res in results:
            candidate_id = res.candidate_id

            # Validation: Self-match
            if source_id == candidate_id:
                raise MatchIntegrityError(
                    f"Self-match rejected: report {source_id} cannot match itself"
                )

            cand_report = authoritative_reports.get(candidate_id)
            if cand_report is None:
                logger.debug(
                    "Candidate report %s not found in authoritative records",
                    candidate_id,
                )
                continue

            # Validation: Opposite report types
            if cand_report.type == source_type:
                raise MatchIntegrityError(
                    f"Invalid match pair: reports {source_id} and {candidate_id} "
                    f"are both {source_type}"
                )

            # Determine canonical missing and found IDs based on source_report.type
            missing_id: uuid.UUID
            found_id: uuid.UUID
            if source_type == ReportType.MISSING:
                missing_id = source_id
                found_id = candidate_id
            elif source_type == ReportType.FOUND:
                missing_id = candidate_id
                found_id = source_id
            else:
                raise MatchIntegrityError(
                    f"Invalid source report type '{source_type}' for matching"
                )

            pair_key = (missing_id, found_id)
            scored_pairs.add(pair_key)
            existing = existing_matches.get(pair_key)

            # Terminal protection: if match is already RESOLVED, do not overwrite
            if existing is not None and existing.status == MatchStatus.RESOLVED:
                logger.debug(
                    "Skipping update for resolved match pair (%s, %s)",
                    missing_id,
                    found_id,
                )
                continue

            both_active = (
                source_status == ReportStatus.ACTIVE
                and cand_report.status == ReportStatus.ACTIVE
            )

            # If either report is not ACTIVE, the match cannot be ACTIVE
            if not both_active:
                if existing is not None:
                    # Determine terminal status
                    if cand_report.status == ReportStatus.RESOLVED:
                        term_status = MatchStatus.RESOLVED
                    else:
                        term_status = MatchStatus.DISQUALIFIED

                    if existing.status != term_status:
                        record: dict[str, Any] = {
                            "id": existing.id,
                            "report_missing_id": missing_id,
                            "report_found_id": found_id,
                            "status": term_status,
                            "composite_score": res.composite_score,
                            "score_identity": res.identity.score,
                            "score_characteristics": res.characteristics.score,
                            "score_distance": res.distance.score,
                            "score_time": res.time.score,
                            "raw_composite_score": res.raw_composite_score,
                            "contradiction_penalty": res.contradiction_penalty,
                            "classification": res.classification,
                            "alert_eligible": False,
                            "minimum_evidence_satisfied": (
                                res.minimum_evidence_satisfied
                            ),
                            "evidence_summary": res.evidence_summary,
                            "explainability_details": serialize_explainability(res),
                            "scoring_version": self._scoring_version,
                            "last_scored_at": now,
                            "created_at": now,
                            "updated_at": now,
                        }
                        to_upsert.append(record)
                continue

            # Both reports ARE genuinely ACTIVE:
            if existing is None:
                # Score >= 40 required to create a new match row
                if res.composite_score < PERSISTENCE_SCORE_THRESHOLD:
                    logger.debug(
                        "Discarding new candidate pair (%s, %s): score %.2f < %.2f",
                        missing_id,
                        found_id,
                        res.composite_score,
                        PERSISTENCE_SCORE_THRESHOLD,
                    )
                    continue
                match_status = MatchStatus.ACTIVE
            else:
                # Existing match with both reports ACTIVE:
                if res.composite_score < PERSISTENCE_SCORE_THRESHOLD:
                    # Demote to SUPPRESSED, preserving history & score breakdown
                    match_status = MatchStatus.SUPPRESSED
                else:
                    # Promotes back to ACTIVE (from ACTIVE, SUPPRESSED, or DISQUALIFIED)
                    match_status = MatchStatus.ACTIVE

            record = {
                "id": uuid.uuid4() if existing is None else existing.id,
                "report_missing_id": missing_id,
                "report_found_id": found_id,
                "status": match_status,
                "composite_score": res.composite_score,
                "score_identity": res.identity.score,
                "score_characteristics": res.characteristics.score,
                "score_distance": res.distance.score,
                "score_time": res.time.score,
                "raw_composite_score": res.raw_composite_score,
                "contradiction_penalty": res.contradiction_penalty,
                "classification": res.classification,
                "alert_eligible": res.alert_eligible,
                "minimum_evidence_satisfied": res.minimum_evidence_satisfied,
                "evidence_summary": res.evidence_summary,
                "explainability_details": serialize_explainability(res),
                "scoring_version": self._scoring_version,
                "last_scored_at": now,
                "created_at": now,
                "updated_at": now,
            }
            to_upsert.append(record)

        # 4. Sort batch deterministically by canonical key to prevent deadlocks
        to_upsert.sort(key=lambda r: (r["report_missing_id"], r["report_found_id"]))

        # 5. Execute atomic upsert with concurrency-safe database conditional guards
        if to_upsert:
            stmt = pg_insert(Match).values(to_upsert)
            upsert_stmt = stmt.on_conflict_do_update(
                constraint="uq_matches_missing_found",
                set_={
                    "composite_score": stmt.excluded.composite_score,
                    "score_identity": stmt.excluded.score_identity,
                    "score_characteristics": stmt.excluded.score_characteristics,
                    "score_distance": stmt.excluded.score_distance,
                    "score_time": stmt.excluded.score_time,
                    "raw_composite_score": stmt.excluded.raw_composite_score,
                    "contradiction_penalty": stmt.excluded.contradiction_penalty,
                    "classification": stmt.excluded.classification,
                    "alert_eligible": stmt.excluded.alert_eligible,
                    "minimum_evidence_satisfied": (
                        stmt.excluded.minimum_evidence_satisfied
                    ),
                    "evidence_summary": stmt.excluded.evidence_summary,
                    "explainability_details": stmt.excluded.explainability_details,
                    "scoring_version": stmt.excluded.scoring_version,
                    "last_scored_at": stmt.excluded.last_scored_at,
                    "updated_at": now,
                    "status": case(
                        (Match.status == MatchStatus.RESOLVED, MatchStatus.RESOLVED),
                        else_=stmt.excluded.status,
                    ),
                },
                where=text(
                    "matches.status != 'RESOLVED' AND ("
                    "excluded.status != 'ACTIVE' OR ("
                    "(SELECT r_m.status FROM reports r_m "
                    " WHERE r_m.id = matches.report_missing_id) = 'ACTIVE' AND "
                    "(SELECT r_f.status FROM reports r_f "
                    " WHERE r_f.id = matches.report_found_id) = 'ACTIVE'"
                    "))"
                ),
            )
            await session.execute(upsert_stmt)

        # 6. Reconcile existing matches not returned in scored_pairs.
        # Distinguish genuine hard-filter failures (distance > 5km, incompatible
        # category, non-active report status) from retrieval limit truncation.
        # A pair must NOT be disqualified merely because a retrieval limit was reached.
        unreturned_rows: list[Any] = [
            existing_row
            for pair_key, existing_row in existing_matches.items()
            if pair_key not in scored_pairs
            and existing_row.status in (MatchStatus.ACTIVE, MatchStatus.SUPPRESSED)
        ]

        if unreturned_rows:
            source_rec = authoritative_reports[source_id]
            source_loc = source_rec.location

            # Determine candidate report IDs for all unreturned matches
            unreturned_candidate_ids: set[uuid.UUID] = set()
            for r in unreturned_rows:
                cand_id = (
                    r.report_found_id
                    if r.report_missing_id == source_id
                    else r.report_missing_id
                )
                unreturned_candidate_ids.add(cand_id)

            # Query candidate report attributes and compute PostGIS distance to source
            distance_expr = (
                func.ST_Distance(Report.location, source_loc).label("distance_meters")
                if source_loc is not None
                else None
            )

            select_cols: list[Any] = [
                Report.id,
                Report.status,
                Report.type,
                Report.category,
                Report.created_by_user_id,
            ]
            if distance_expr is not None:
                select_cols.append(distance_expr)

            unret_stmt = select(*select_cols).where(
                Report.id.in_(list(unreturned_candidate_ids))
            )
            unret_res = await session.execute(unret_stmt)
            unret_map = {row.id: row for row in unret_res.all()}

            matches_to_disqualify: list[uuid.UUID] = []
            matches_to_resolve: list[uuid.UUID] = []

            for r in unreturned_rows:
                cand_id = (
                    r.report_found_id
                    if r.report_missing_id == source_id
                    else r.report_missing_id
                )
                cand_rec = unret_map.get(cand_id)

                if cand_rec is None:
                    # Candidate report was deleted
                    matches_to_disqualify.append(r.id)
                    continue

                if cand_rec.status == ReportStatus.RESOLVED:
                    matches_to_resolve.append(r.id)
                    continue
                elif cand_rec.status in (ReportStatus.CANCELLED, ReportStatus.EXPIRED):
                    matches_to_disqualify.append(r.id)
                    continue
                elif cand_rec.status != ReportStatus.ACTIVE:
                    matches_to_disqualify.append(r.id)
                    continue

                # Check same creator (HF-2)
                if (
                    source_rec.created_by_user_id is not None
                    and source_rec.created_by_user_id == cand_rec.created_by_user_id
                ):
                    matches_to_disqualify.append(r.id)
                    continue

                # Check Category Compatibility (HF-6):
                # Concrete categories must match unless one is OTHER.
                if (
                    source_rec.category != ReportCategory.OTHER
                    and cand_rec.category != ReportCategory.OTHER
                    and source_rec.category != cand_rec.category
                ):
                    logger.info(
                        "Match %s disqualified: category %s incompatible with %s",
                        r.id,
                        cand_rec.category,
                        source_rec.category,
                    )
                    matches_to_disqualify.append(r.id)
                    continue

                # Check Spatial Proximity (HF-4 & HF-5):
                dist_val: float | None = getattr(cand_rec, "distance_meters", None)
                if dist_val is None or dist_val > MATCHING_RADIUS_METERS:
                    logger.info(
                        "Match %s disqualified: distance %.1fm exceeds %.1fm limit",
                        r.id,
                        dist_val if dist_val is not None else -1.0,
                        MATCHING_RADIUS_METERS,
                    )
                    matches_to_disqualify.append(r.id)
                    continue

                # Candidate satisfied all hard filters:
                # Active, within 5km, compatible category, different user.
                # It was omitted solely due to retrieval limit / truncation.
                # Retain its current lifecycle status (ACTIVE or SUPPRESSED)!
                logger.debug(
                    "Match %s omitted due to retrieval limit; "
                    "hard filters satisfied (dist=%.1fm); retaining status %s.",
                    r.id,
                    dist_val,
                    r.status,
                )

            if matches_to_disqualify:
                disqualify_stmt = (
                    update(Match)
                    .where(
                        Match.id.in_(matches_to_disqualify),
                        Match.status != MatchStatus.RESOLVED,
                    )
                    .values(
                        status=MatchStatus.DISQUALIFIED,
                        alert_eligible=False,
                        updated_at=now,
                    )
                )
                await session.execute(disqualify_stmt)

            if matches_to_resolve:
                resolve_stmt = (
                    update(Match)
                    .where(
                        Match.id.in_(matches_to_resolve),
                        Match.status != MatchStatus.RESOLVED,
                    )
                    .values(
                        status=MatchStatus.RESOLVED,
                        alert_eligible=False,
                        updated_at=now,
                    )
                )
                await session.execute(resolve_stmt)

    async def resolve_matches_for_report(
        self, report_id: uuid.UUID, session: AsyncSession
    ) -> int:
        """Transitions all non-resolved matches involving this report to RESOLVED."""
        now = func.now()
        stmt = (
            update(Match)
            .where(
                or_(
                    Match.report_missing_id == report_id,
                    Match.report_found_id == report_id,
                ),
                Match.status != MatchStatus.RESOLVED,
            )
            .values(
                status=MatchStatus.RESOLVED,
                alert_eligible=False,
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        count = int(cast(CursorResult[Any], res).rowcount)
        logger.info(
            "Resolved %d active/suppressed matches for report %s", count, report_id
        )
        return count

    async def disqualify_matches_for_report(
        self,
        report_id: uuid.UUID,
        session: AsyncSession,
        reason: str = "report_inactive",
    ) -> int:
        """Transitions active matches involving this report to DISQUALIFIED."""
        now = func.now()
        stmt = (
            update(Match)
            .where(
                or_(
                    Match.report_missing_id == report_id,
                    Match.report_found_id == report_id,
                ),
                Match.status.in_([MatchStatus.ACTIVE, MatchStatus.SUPPRESSED]),
            )
            .values(
                status=MatchStatus.DISQUALIFIED,
                alert_eligible=False,
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        count = int(cast(CursorResult[Any], res).rowcount)
        logger.info(
            "Disqualified %d active matches for inactive report %s (reason: %s)",
            count,
            report_id,
            reason,
        )
        return count

    async def get_matches_for_report(
        self,
        report_id: uuid.UUID,
        session: AsyncSession,
        status: MatchStatus | None = None,
    ) -> list[Match]:
        """Queries match records involving the specified report."""
        conditions = [
            or_(
                Match.report_missing_id == report_id,
                Match.report_found_id == report_id,
            )
        ]
        if status is not None:
            conditions.append(Match.status == status)

        stmt = (
            select(Match)
            .where(*conditions)
            .order_by(Match.composite_score.desc(), Match.created_at.desc())
            .execution_options(populate_existing=True)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())
