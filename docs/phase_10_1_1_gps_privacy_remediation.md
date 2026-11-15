# Boomerang — Phase 10.1.1: Emergency GPS Privacy Audit & Remediation Report

**Date:** November 15, 2026  
**Status:** Completed & Production Verified  
**Scope:** Physical Missing & Found Items Subsystem  
**Reference Threats:** `THR-LOCATION-001`, `THR-MATCH-001`, `SEC-PRIVACY-001`

---

## 1. Executive Summary & Original Vulnerability Claim

During Phase 10.1 Threat Modelling, a critical privacy risk (`THR-LOCATION-001`) was identified:
> *Potential exposure of exact incident GPS coordinates through Boomerang's public discovery and candidate matching APIs.*

Exact raw GPS coordinates recorded during incident report creation (e.g., loss of keys or phone at a residence, workplace, or private venue) could enable malicious actors to harvest high-precision locations, stalk report creators, or triangulate private residences down to sub-metre accuracy.

Phase 10.1.1 was commissioned to conduct an emergency audit to:
1. Prove whether exact coordinate leakage exists across the codebase without assumptions.
2. Determine the precise privacy boundaries across all endpoints and data flows.
3. Remediate the exposure using the smallest safe fix while preserving PostGIS spatial filtering, matching precision, and client compatibility without requiring destructive or complex database migrations.
4. Establish comprehensive automated regression tests.

---

## 2. Audit Findings & Empirical Verification

### 2.1 Tracing Results Across Application Subsystems

| Subsystem / Endpoint | Authentication State | Authorization Check | Location Field Exposed | Empirical Audit Verdict |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/v1/reports` | Optional (`get_optional_current_user`) | Public / Any caller | Raw incident `latitude` & `longitude` | **CONFIRMED VULNERABLE (CRITICAL)**: Unauthenticated callers and non-owners received exact raw GPS coordinates. |
| `GET /api/v1/reports/{id}` | Optional (`get_optional_current_user`) | Public / Any caller | Raw incident `latitude` & `longitude` | **CONFIRMED VULNERABLE (CRITICAL)**: Anyone knowing or iterating a report ID received exact raw GPS coordinates. |
| `GET /api/v1/reports/me` | Required (`get_current_user`) | Owner only (`user_id == current_user.id`) | Raw incident `latitude` & `longitude` | **LEGITIMATE (LOW RISK)**: Owner legitimately inspects their own report. |
| `POST /api/v1/reports` | Required (`get_current_user`) | Creator creating own report | Raw incident `latitude` & `longitude` | **LEGITIMATE (LOW RISK)**: Creator receives their own submitted coordinates. |
| `PATCH /api/v1/reports/{id}` | Required (`get_current_user`) | Owner only (`created_by_user_id == current_user.id`) | Raw incident `latitude` & `longitude` | **LEGITIMATE (LOW RISK)**: Owner receives their updated coordinates. |
| `GET /api/v1/reports/{id}/matches` | Required (`get_current_user`) | Report owner only | `opposite_report.latitude`, `opposite_report.longitude` | **CONFIRMED VULNERABLE (HIGH)**: Exposes opposite party's exact raw incident coordinates before contact/handshake. |
| `GET /api/v1/matches/{id}` | Required (`get_current_user`) | Participant in match only | Both `report_missing` and `report_found` coordinates | **CONFIRMED VULNERABLE (HIGH)**: Both parties received each other's exact coordinates. |
| `GET /api/v1/recovery-requests/*` | Required (`get_current_user`) | Requester or Recipient | None (`RecoveryRequestReportResponse`) | **DISPROVED (NO VULNERABILITY)**: Schema serializes only `id`, `title`, `type`, `category`, `status`. Zero coordinate fields exist. |
| `GET /api/v1/notifications/*` & FCM | Required (`get_current_user`) | Target user only | None (Defensively stripped) | **DISPROVED (NO VULNERABILITY)**: `NotificationResponse.sanitize_data` actively purges location and coordinate keys. |

---

## 3. Existing Location Architecture & Database Schema Analysis

### 3.1 Single Spatial Column in PostgreSQL
In `app/db/models.py`, the `Report` table defines exactly one spatial column:
```python
location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
```
- Spatial GiST indexing is enabled automatically on `location`.
- PostGIS functions (`ST_DWithin`, `ST_Distance`) evaluate distances against this single column.
- There are no separate pre-existing `location_fuzzed` or `discovery_anchor` columns in the database.

### 3.2 Flutter Client Architecture
In `frontend/lib/models/report_model.dart`:
- `ReportModel` parses `latitude` and `longitude` as nullable doubles:
  ```dart
  latitude: (json['latitude'] as num?)?.toDouble(),
  longitude: (json['longitude'] as num?)?.toDouble(),
  ```
- Markers on `MapScreen` and cards on `HomeScreen` render directly at `report.latitude` and `report.longitude`.
- Flutter map markers handle coarsened coordinates (e.g., `37.77`, `-122.42`) natively without schema changes, parse failures, or UI regressions.

---

## 4. Root Cause Analysis

1. **Direct Projection of Authoritative Spatial Data**:
   `app/services/report.py` projected raw `ST_Y` and `ST_X` from `Report.location` directly into `report.latitude` and `report.longitude` without distinguishing between the report owner and public or third-party callers.
2. **Missing Differential Privacy Serialization**:
   FastAPI serialization routes returned the underlying model's exact coordinates indiscriminately to all callers via Pydantic schemas (`ReportResponse`, `ReportListResponse`, `MatchReportSummary`).
3. **Premature Location Sharing in Match Candidate Feeds**:
   `app/api/matches.py` joined the opposite party's report directly and populated `MatchReportSummary` with raw coordinates before any mutual consent or recovery handshake.

---

## 5. Remediation Design & Implementation

### 5.1 Privacy Boundary Definition
1. **Public Default**: Coarsened to 2 decimal places ($\approx 1.1\text{ km}$ resolution). Unauthenticated callers and authenticated non-owners receive deterministic coarsened coordinates snapped to a $\approx 1.1\text{ km}$ grid.
2. **Owner Retention**: Report creators retain access to their own authoritative, exact coordinates on `GET /reports/{id}`, `GET /reports/me`, `POST /reports`, `PATCH /reports/{id}`, and in match detail views for their own report.
3. **Opposite-Party Protection**: In match feeds and match details, opposite-party reports serialize only coarsened coordinates.
4. **Spatial Integrity**: PostGIS spatial queries (`ST_DWithin`, `ST_Distance`) and candidate matching algorithms continue to use authoritative `Report.location`.

### 5.2 Zero-Migration Justification
Adding a redundant `location_fuzzed` column to the database was deliberately rejected:
- It would introduce database desynchronization risks upon report location updates.
- It would require an Alembic schema migration and backfilling existing records.
- Dynamic serialization at the API boundary provides instantaneous, zero-downtime protection, strictly respects caller authorization, and preserves the single source of truth in PostgreSQL/PostGIS.

### 5.3 Files Modified & Added

1. **`app/services/geo.py` (New)**:
   - Implemented `coarsen_coordinate(lat: float, lon: float, precision_decimals: int = 2) -> tuple[float, float]`.
   - Snaps coordinates deterministically to 2 decimal places ($\approx 1.1\text{ km}$ precision).

2. **`app/services/report.py` (Modified)**:
   - Added `viewer_user_id: uuid.UUID | None = None` parameter to `list_reports`.
   - Dynamically evaluates ownership: if `viewer_user_id == r.created_by_user_id`, exact coordinates are preserved; otherwise, `coarsen_coordinate` is applied.

3. **`app/api/reports.py` (Modified)**:
   - `list_my_reports`: Passes `viewer_user_id=current_user.id`.
   - `list_reports`: Passes `viewer_user_id=current_user.id` when `mine=True` or `current_user.id if current_user else None` for public search.
   - `get_report`: Dynamically coarsens coordinates if `current_user is None or report.created_by_user_id != current_user.id`.

4. **`app/api/matches.py` (Modified)**:
   - `list_report_matches`: Coarsens `opposite_report` coordinates using `coarsen_coordinate`.
   - `get_match_detail`: Symmetrically coarsens the opposite report while preserving exact coordinates for the caller's own report (`owns_missing` vs `owns_found`).

5. **`tests/test_location_privacy.py` (New)**:
   - Added 5 comprehensive test suites covering 12 distinct privacy and spatial integrity assertions.

---

## 6. Verification Results

### 6.1 Automated Test Execution
- **Location Privacy Test Suite (`tests/test_location_privacy.py`)**:
  - `test_anonymous_and_non_owner_coarsening_on_reports`: PASSED
  - `test_mixed_ownership_report_listing`: PASSED
  - `test_match_endpoints_location_privacy`: PASSED
  - `test_recovery_and_notifications_zero_location_exposure`: PASSED
  - `test_postgis_search_remains_authoritative_with_coarsened_output`: PASSED
- **Full Backend Pytest Suite**: 333 tests passed in 176.84s (100% pass rate).
- **Type Checking**: `mypy --strict` passed across all 88 source files with 0 errors.
- **Code Formatting & Linting**: `ruff check .` and `ruff format --check .` passed cleanly across all 98 files.
- **Frontend Quality**: `flutter analyze` reported 0 issues across all Flutter source files.
- **Frontend Location & Map Tests**: 43 widget and location integration tests passed cleanly.

---

## 7. Remaining Privacy Risks & Recommendations

1. **Trilateration via Multiple Geo-Queries**:
   - While exact coordinates are coarsened to $\approx 1.1\text{ km}$ and `radius_km` queries are bounded, a persistent adversary executing automated queries across overlapping circular radii could attempt trilateration if `distance_km` is exposed with high precision.
   - *Recommendation for Phase 10.3*: Round `distance_km` to the nearest $0.5\text{ km}$ for non-owners, and enforce IP-based rate limiting on geo-queries (`SEC-QUOTA-001`).
2. **Mutual Consent Handshake**:
   - Physical meetups or return locations should remain coordinated exclusively through the recovery handshake mechanism or designated community safe-drop locations rather than raw coordinate exchange.

---

## 8. Final Verdict

- **Vulnerability Status**: **CONFIRMED & REMEDIATED**
- **Public Report Exposure**: Eliminated (snapped to $\approx 1.1\text{ km}$ grid).
- **Match Opponent Exposure**: Eliminated (coarsened prior to handshake).
- **PostGIS Search & Matching**: Fully preserved on authoritative database geometry.
- **API & Client Compatibility**: 100% backward compatible (no schema breakage).

