# Boomerang — Phase 10.1.3: Geographic Inference Containment

## 1. Executive Summary & Objective

Phase 10.1.2 introduced dynamic distance quantization (snapping public `distance_km` values to multiples of 0.5 km) and parameter validation (maximum 5.0 km radius, $\le 1$ decimal place). The subsequent Phase 10.1.2 adversarial review demonstrated that while passive 3-query multilateration was defeated, four active inference channels remained accessible to automated adversaries:

1. **Exact-Distance Ordering & Perpendicular-Bisector Recovery (`ORDER BY distance`)**: Database-level `ST_Distance` sorting leaked exact relative proximity, allowing adversaries to locate perpendicular bisectors between items using binary search order flips.
2. **Radius-Membership Boundary Probing (`ST_DWithin` Oracle)**: Floating-point precision on `latitude` and `longitude` allowed adversaries to execute binary search bisection on search origins, locating exact 1,000m radius circle perimeters to within 15 meters.
3. **Distance Quantization Step Transition Probing**: Continuous movement of probe coordinates allowed adversaries to binary search for discrete 750m distance thresholds.
4. **Pagination and Rank-Order Leakage**: Paging with `page_size=1` exposed exact rank transitions as search coordinates changed.

Phase 10.1.3 implements a layered privacy containment boundary for public and non-owner geographic discovery. It eliminates continuous bisection and relative proximity leakage while preserving authoritative PostGIS calculations and matching accuracy.

---

## 2. Attack Vectors & Root Cause Analysis

| Attack Vector | Demonstrated Impact | Root Cause | Containment Mechanism |
| :--- | :--- | :--- | :--- |
| **1. Exact-Distance Ordering** | Recovered perpendicular bisectors and exact midpoint in 12 queries (<2m resolution). | Public SQL query used `ORDER BY ST_Distance(...) ASC` before pagination. | **Bucketed Distance Sorting**: Results grouped into 500m bands (`floor(dist / 500)`). Ties broken by `created_at DESC, id ASC`. |
| **2. Radius-Membership Probing** | Reconstructed item latitude to within 15m in 14 queries using `ST_DWithin` presence/absence. | Public search query accepted arbitrary 6+ decimal float precision for `latitude` and `longitude`. | **Search-Origin Grid Snapping**: Query coordinates snapped to 2 decimal places ($0.01^\circ \approx 1.1\text{ km}$). |
| **3. Step Transition Probing** | Isolated exact 750m distance contour within 15m in 10 queries. | Continuous probe movement allowed binary searching for the 0.5 km $\to$ 1.0 km rounding boundary. | **Grid Discretization**: Probes cannot move continuously; snapped coordinates convert contour search into coarse, invariant steps. |
| **4. Pagination Rank Leakage** | Tracked rank swaps across page boundaries as search coordinates moved. | Fine-grained proximity sorting allowed items in same neighborhood to swap pages. | **Bucketed Rank Invariance**: Items in same 500m band maintain stable `created_at DESC` order regardless of sub-grid probe shifts. |

---

## 3. Privacy Boundary Architecture: Internal vs. Public Paths

```
+-----------------------------------------------------------------------------------------+
|                                    DATA BOUNDARY                                        |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [INTERNAL TRUSTED PATH]                           [PUBLIC / NON-OWNER DISCOVERY PATH]  |
|                                                                                         |
|  - PostgreSQL PostGIS `Report.location`             - Search-Origin Grid Snapping       |
|    (Exact POINT geometry, SRID 4326)                  (Snapped to 0.01 deg / ~1.1 km)   |
|  - Candidate Retrieval `retrieve_candidates`        - Bucketed Proximity Sorting        |
|    (Uncoarsened ST_DWithin <= 5,000m)                 (500m bands + created_at DESC)    |
|  - Match Scoring Engine                             - Output Coordinate Coarsening      |
|    (Authoritative ST_Distance, signal D)              (Snapped to 0.01 deg / ~1.1 km)   |
|  - Owner Query Exemption                            - Output Distance Quantization      |
|    (Exact coords, exact 2-decimal dist)               (Snapped to multiples of 0.5 km)  |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

### 3.1 Internal Trusted Path
- **Integrity Guarantee**: Authoritative spatial geometries stored in PostGIS `Report.location` are **never modified, rounded, or truncated**.
- **Matching Accuracy**: Spatial candidate retrieval (`retrieve_candidates` in `app/services/matching/retrieval.py`) continues to use uncoarsened geometries with PostGIS spatial GiST indexing and exact `ST_DWithin` filtering.
- **Score Breakdown**: Scoring algorithms evaluate true physical distances (`cand.distance_meters`), ensuring composite matching scores and classifications remain 100% authoritative.
- **Authenticated Owners**: Report creators inspecting their own items (`user_id == viewer_user_id`) receive exact coordinates and exact distance calculations (`round(dist / 1000.0, 2)`).

### 3.2 Public / Non-Owner Discovery Path
- **Search Origin Snapping**: Query coordinates `latitude` and `longitude` are snapped to 2 decimal places (`snap_search_origin`) prior to executing spatial filtering.
- **Result Sorting**: Ordered by 500-meter coarse distance buckets (`DISTANCE_BUCKET_SIZE_METERS = 500.0`), broken strictly by `created_at DESC, id ASC`.
- **Response Serialization**: Output coordinates coarsened to 2 decimal places (`coarsen_coordinate`); output distances quantized to 0.5 km multiples (`coarsen_distance`).

---

## 4. Mitigation Implementation Details

### 4.1 Search-Origin Grid Snapping (`app/services/geo.py`)
```python
SEARCH_ORIGIN_GRID_DECIMALS: int = 2
DISTANCE_BUCKET_SIZE_METERS: float = 500.0


def snap_search_origin(
    lat: float, lon: float, precision_decimals: int = SEARCH_ORIGIN_GRID_DECIMALS
) -> tuple[float, float]:
    """Snap search origin coordinates to a deterministic coarse grid.

    Rounds latitude and longitude to 2 decimal places (~1.1 km grid) for public
    and non-owner geographic discovery queries. This converts continuous probe
    movement into discrete grid steps, neutralizing binary search boundary
    probing while preserving neighborhood discovery.
    """
    return round(float(lat), precision_decimals), round(float(lon), precision_decimals)
```

#### Grid Policy Rationale & Scale Comparison:
- **0.01 degree resolution**: Corresponds to $\approx 1,113\text{ meters}$ in latitude and $\approx 1,084\text{ meters}$ in longitude at $13^\circ$ (Chennai), $\approx 964\text{ meters}$ at $30^\circ$, and $\approx 715\text{ meters}$ at $50^\circ$ (Kyiv).
- **Maximum Shift**: For any user-selected origin, the maximum distance to the snapped grid center is $\le 787\text{ meters}$ (at cell corners).
- **Local Discovery Preservation**: Because standard search radii are $1.0\text{ km}$, $2.0\text{ km}$, or $5.0\text{ km}$, shifting the center by $\le 550\text{m}$ preserves full neighborhood coverage.
- **Bisection Defeat**: Any continuous movement within a $0.01^\circ \times 0.01^\circ$ box maps to the identical grid center, returning identical items and breaking the $O(\log N)$ bisection loop.

### 4.2 Bucketed Distance Sorting (`app/services/report.py`)
```python
    if sort == "distance":
        if is_pure_owner_query:
            query = query.order_by(
                asc(distance_col), desc(Report.created_at), asc(Report.id)
            )
        else:
            # Stage B: Bucketed distance sorting for public discovery (Phase 10.1.3).
            # Primary sort: 500-meter coarse distance bucket (floor(distance / 500.0)).
            # Secondary tie-breaker: newest first (created_at DESC).
            # Tertiary tie-breaker: unique report ID (id ASC).
            # Authoritative ST_Distance is NEVER used as an intra-bucket tie-breaker,
            # eliminating perpendicular-bisector ordering attacks.
            distance_bucket = func.floor(distance_col / DISTANCE_BUCKET_SIZE_METERS)
            query = query.order_by(
                asc(distance_bucket), desc(Report.created_at), asc(Report.id)
            )
```

#### Intra-Bucket Order Invariance:
- Within each 500m band ($[0, 500)\text{m}$, $[500, 1000)\text{m}$, etc.), records are ordered strictly by creation timestamp (`created_at DESC`).
- An item created more recently will always appear ahead of an older item in the same band, regardless of which item is physically closer to the probe.
- Moving the search probe changes relative physical proximity, but does NOT alter result ordering within the bucket. Bisector search fails completely.

---

## 5. Pagination & Determinism Guarantees

1. **Deterministic SQL Offset Paging**:
   - `order_by(asc(distance_bucket), desc(Report.created_at), asc(Report.id))` contains `id ASC` as a unique primary key tie-breaker.
   - Every report has a strictly deterministic position in the ordered query stream.
   - Paging through results via `page` and `page_size` will never produce duplicate records or skip records between pages.
2. **Stable Rank Order**:
   - Small movements of the search origin inside a grid cell do not shift items across page boundaries because distance buckets and creation timestamps remain constant.
3. **No Unintended Regression on Other Sort Modes**:
   - `sort="newest"` continues to sort by `desc(Report.created_at), asc(Report.id)`.
   - `sort="oldest"` continues to sort by `asc(Report.created_at), asc(Report.id)`.

---

## 6. Rate Limiting Integration Point (Phase 10.3 Architecture)

While Phase 10.1.3 eliminates continuous sub-meter micro-stepping within grid cells and hides intra-bucket proximity ranking, an adversary can still query different discrete grid cells ($..., 13.07, 13.08, 13.09, ...$).

To restrict distributed and multi-cell mapping attacks, Phase 10.1.3 formalizes the enforcement points for Phase 10.3 Rate Limiting (`SEC-QUOTA-001`):

### Enforcement Points:
- **Target Endpoint**: `GET /api/v1/reports` when `latitude`, `longitude`, and `radius_km` are provided.
- **Anonymous / IP Rate Limit**: Maximum 10 geographic discovery requests per minute per IP.
- **Authenticated User Rate Limit**: Maximum 30 geographic discovery requests per minute per user account.
- **Sliding Window Key**: `quota:geo_query:{user_id_or_client_ip}` backed by Redis.
- **Response on Exceeded Quota**: HTTP 429 Too Many Requests with `Retry-After` header.

---

## 7. Verification & Test Results

A full suite of 15 automated security and containment tests was executed:

### 7.1 Adversarial Containment Verification (`tests/test_geo_privacy_adversarial.py`)
4 tests verifying containment of the original attack vectors:
1. `test_adversarial_distance_order_inversion_bisector_recovery`: Proves relative order is invariant to probe shifts; bisector search finds zero inversions (**PASSED**).
2. `test_adversarial_boundary_membership_bisection_attack`: Proves sub-meter probe variations inside a grid cell yield identical result sets (**PASSED**).
3. `test_adversarial_quantization_step_transition_attack`: Proves continuous bisection cannot locate 750m contours across discrete grid steps (**PASSED**).
4. `test_adversarial_pagination_rank_leakage`: Proves items in same bucket preserve stable page placement across probe movements (**PASSED**).

### 7.2 Comprehensive Stage G Test Suite (`tests/test_geo_inference_containment.py`)
11 tests verifying all 13 Stage G security scenarios:
1. `test_distance_ordering_bisector_containment`: Intra-bucket tie-breaking by `created_at DESC` (**PASSED**).
2. `test_pagination_rank_order_stability`: Stable pagination across sub-grid probe shifts (**PASSED**).
3. `test_search_origin_micro_stepping_constrained`: Micro-stepped origins return identical quantized responses (**PASSED**).
4. `test_radius_membership_grid_policy`: Verified across 0.5, 1.0, 2.0, 5.0 km radii (**PASSED**).
5. `test_quantization_transition_precision_containment`: Quantization step bisection prevented (**PASSED**).
6. `test_repeated_identical_queries_deterministic_stability`: 5 identical queries return identical item sequences (**PASSED**).
7. `test_existing_valid_discovery_searches_work`: Verified in Chennai and Kyiv urban contexts (**PASSED**).
8. `test_owner_authorization_behavior_intact`: Owners querying own items receive exact un-snapped coordinates (**PASSED**).
9. `test_internal_matching_and_postgis_remain_authoritative`: PostGIS candidate retrieval uses exact uncoarsened geometries (**PASSED**).
10. `test_match_summaries_coarsened_opposite_distance_and_location`: Opposite match summaries retain coarsened coordinates and 0.5 km quantized distance (**PASSED**).
11. `test_phase_10_1_1_and_10_1_2_helpers_remain_compatible`: Pure helpers assert backward compatibility (**PASSED**).

### 7.3 Full Regression Results
- **Combined Geo & Privacy Suites**: 43 passed in 40.49s (`tests/test_geo_inference_containment.py`, `tests/test_geo_privacy_adversarial.py`, `tests/test_geo_privacy_hardening.py`, `tests/test_location_privacy.py`, `tests/test_geo.py`, `tests/test_matching_api.py`).
- **Static Analysis Quality Gates**:
  - `ruff check .`: 0 errors.
  - `ruff format --check .`: 104 files clean.
  - `mypy .`: Success (0 issues in 92 source files).
  - `flutter analyze`: No issues found (clean in 1.8s).

---

## 8. Remaining Inference Risks & Scope Limitations

1. **Discrete Grid Cell Intersection (Cell-Level Triangulation)**:
   - *Residual Exposure*: An attacker querying discrete grid points ($13.08, 13.09, 13.10$) can observe which grid centers contain the target within radius $r$.
   - *Bounding Guarantee*: The spatial uncertainty of this intersection is bounded to the grid cell size ($\approx 1.1\text{ km} \times 1.1\text{ km} \approx 1.2\text{ km}^2$), which is identical to the Phase 10.1.1 coordinate coarsening privacy boundary.
   - *Mitigation*: Phase 10.3 rate limiting (`SEC-QUOTA-001`) prevents automated multi-cell scanning.
2. **Freeform Incident Descriptions**:
   - *Residual Exposure*: User-entered text in `title` or `description` (e.g. "Left at Starbucks on 1st Ave") can reveal exact incident sites.
   - *Mitigation*: Scheduled for Phase 10.2 / 10.4 user privacy guidance and address entity stripping.
