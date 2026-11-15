# Boomerang — Phase 10.1.2: Geographic Query Privacy Hardening

## 1. Executive Summary & Problem Statement

Phase 10.1.1 introduced dynamic API-boundary coordinate coarsening, rounding public and non-owner incident GPS coordinates to 2 decimal places (~1.1 km spatial grid) while preserving authoritative `POINT` geometries in PostgreSQL/PostGIS `Report.location`.

However, the threat model (`docs/security_threat_model.md`, `THR-LOCATION-002`) and security requirements (`docs/security_requirements.md`, `SEC-LOCATION-002`) identified a secondary inference attack vector: **Repeated-Query Triangulation (Multilateration)**.

### The Attack Vector: High-Precision Distance Multilateration

When a user performs a spatial query via `GET /api/v1/reports?latitude=...&longitude=...&radius_km=...`, the backend calculates the exact distance between the query origin and the item's authoritative location using PostGIS `ST_Distance(location, ST_MakePoint(lon, lat)::geography)`:
```python
dist = r.distance_meters
dist_km = round(dist / 1000.0, 2)
```
Before Phase 10.1.2, this calculation returned `distance_km` formatted to 2 decimal places (10-meter precision) to all callers. 

An adversary could mount a classical trilateration attack:
1. Select 3 distinct vantage points $P_1(x_1, y_1)$, $P_2(x_2, y_2)$, and $P_3(x_3, y_3)$.
2. Query `GET /api/v1/reports` from each vantage point within range of a target item.
3. Record the high-precision reported distances $d_1, d_2, d_3$.
4. Formulate three circle equations on the geographic plane:
   $$(x - x_1)^2 + (y - y_1)^2 = d_1^2$$
   $$(x - x_2)^2 + (y - y_2)^2 = d_2^2$$
   $$(x - x_3)^2 + (y - y_3)^2 = d_3^2$$
5. Solve for the circle intersections $(x^*, y^*)$. With 10-meter distance precision, the intersection reduces to a tight point, reconstructing the exact authoritative coordinates of the victim's item and bypassing coordinate coarsening entirely!

### The Mitigation: Distance Quantization & Radius Hardening

Phase 10.1.2 addresses this at the API serialization boundary:
1. **Public Distance Quantization**: All `distance_km` values returned to public callers and non-owners are quantized to multiples of 0.5 km (`0.0, 0.5, 1.0, 1.5, ...`) using `coarsen_distance`.
2. **Annular Uncertainty Bands**: A 0.5 km step creates an uncertainty band of $\pm 250\text{m}$ ($500\text{m}$ ring thickness). Three intersecting annuli generate an uncertainty polygon of $\approx 0.2\text{ to } 0.8\text{ km}^2$, defeating simple, non-interactive point trilateration.
3. **Owner Exemption**: Verified report owners inspecting their own reports retain exact distance calculations (`round(dist / 1000.0, 2)`).
4. **Nested Match Protection**: Opposite-party reports nested within match responses (`MatchReportSummary.distance_km`) are quantized to 0.5 km.
5. **Radius Parameter Hardening**: Enforces maximum search radius ($5.0\text{ km}$), minimum radius ($0.0\text{ km}$), and decimal scale restriction ($\le 1$ decimal place), blocking micro-radius step-probing attacks.

---

## 2. Geographic Attack Surface & Threat Matrix

| Endpoint | Operation / Context | Public / Non-Owner Exposure | Report Owner Exposure | Mitigation Status |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/v1/reports` | Public report discovery with spatial filtering | `lat`/`lon` coarsened to 2 dp (~1.1 km); `distance_km` quantized to 0.5 km multiples. | `lat`/`lon` exact; `distance_km` exact (2 dp). | **HARDENED** (`SEC-LOCATION-001`, `SEC-LOCATION-002`) |
| `GET /api/v1/reports/{id}` | Direct report inspection | `lat`/`lon` coarsened to 2 dp (~1.1 km). Zero `distance_km` field. | `lat`/`lon` exact. Zero `distance_km` field. | **HARDENED** (`SEC-LOCATION-001`) |
| `GET /api/v1/reports/me` | My reports listing | N/A (Authenticated owner only). | `lat`/`lon` exact. Zero `distance_km` field. | **SECURE** |
| `POST /api/v1/reports` | Create report | N/A (Creator receives own report). | Exact coordinates returned to creator; stored raw in PostGIS. | **SECURE** |
| `PATCH /api/v1/reports/{id}` | Update report | N/A (Owner only). | Exact coordinates returned to owner. | **SECURE** |
| `GET /api/v1/reports/{id}/matches` | Match listing for a report | Opposite report `lat`/`lon` coarsened to 2 dp; `distance_km` quantized to 0.5 km. | Target report has exact coordinates. | **HARDENED** (`SEC-LOCATION-002`) |
| `GET /api/v1/matches/{id}` | Match detail view | Opposite report `lat`/`lon` coarsened to 2 dp; `distance_km` quantized to 0.5 km. | User's own report has exact coordinates. | **HARDENED** (`SEC-LOCATION-002`) |
| `POST /api/v1/recovery-requests` | Create recovery request | Zero coordinates in response schema (`RecoveryRequestReportResponse`). | Zero coordinates exposed. | **SECURE** |
| `GET /api/v1/recovery-requests/*` | Recovery request detail & lists | Zero coordinates in response schema. | Zero coordinates exposed. | **SECURE** |
| `GET /api/v1/notifications` | In-app notification feed | Coordinates purged via `NotificationResponse.sanitize_data`. | Zero coordinates exposed. | **SECURE** |
| Kafka: `report.created` / `.updated` | Backend domain events | Contains authoritative `latitude`/`longitude` exclusively for internal matching engine. | Internal event payload; never emitted to clients. | **SECURE** |
| Kafka: `match.alert_ready` | Match alert event | Payload schema contains score, classification, item titles; zero coordinates. | Zero coordinates exposed. | **SECURE** |
| FCM Push Notification | Outbox push dispatcher | FCM data payload stripped of sensitive keys (`latitude`, `longitude`, `coordinates`). | Zero coordinates exposed. | **SECURE** |

---

## 3. Mathematical Proof of Trilateration Defeat (Single-Shot / Passive Model)

### 3.1 Point Intersection Under Exact Distances
Let a target item be located at unknown coordinates $X = (x_0, y_0)$. An attacker places three search vantage points $P_1, P_2, P_3$ with coordinates $(x_1, y_1), (x_2, y_2), (x_3, y_3)$.
Under exact distance reporting with standard measurement error $\epsilon \approx 0.01\text{ km}$ ($10\text{m}$):
$$d_i = \|P_i - X\|_2 + \epsilon_i$$
The intersection of the circles:
$$C_i = \{x \in \mathbb{R}^2 \mid \|x - P_i\|_2 = d_i\}$$
yields a unique solution point $(x_0, y_0)$ with an error ellipse bounding area:
$$\text{Area}_{\text{exact}} \approx \pi (10\text{m})^2 \approx 314\text{ m}^2$$
This provides near-pinpoint tracking of personal property and incident sites.

### 3.2 Annular Intersection Under Quantized Distances
Under Phase 10.1.2, distance reporting is quantized to step size $S = 0.5\text{ km}$:
$$\hat{d}_i = \text{coarsen\_distance}(d_i, 0.5) = \text{round}\left(\frac{d_i}{0.5}\right) \times 0.5$$
The inverse mapping yields an annular ring of radius $\hat{d}_i$ with half-width $\Delta = \frac{S}{2} = 0.25\text{ km}$:
$$A_i = \left\{x \in \mathbb{R}^2 \;\middle|\; \hat{d}_i - 0.25 \le \|x - P_i\|_2 \le \hat{d}_i + 0.25\right\}$$
The intersection of three independent non-concentric annular rings:
$$\Omega = A_1 \cap A_2 \cap A_3$$
forms a convex/curvilinear polygon rather than a point. For vantage points spaced 1 km to 3 km apart, the geometric area of $\Omega$ is:
$$\text{Area}(\Omega) \approx 0.21\text{ km}^2 \text{ to } 0.84\text{ km}^2 \quad (210,000\text{ m}^2 \text{ to } 840,000\text{ m}^2)$$
Comparing the two areas:
$$\frac{\text{Area}_{\text{quantized}}}{\text{Area}_{\text{exact}}} \approx \frac{500,000\text{ m}^2}{314\text{ m}^2} \approx 1,592\times \text{ uncertainty expansion}$$
An attacker attempting to physically locate an item within an uncertainty area exceeding $500,000\text{ m}^2$ (roughly 70 city blocks) cannot determine the specific building, street, or address where the item was lost or found from a passive 3-query sample.

---

## 4. Implementation Details

### 4.1 Geo Helper: `app/services/geo.py`
Added constant `DISTANCE_QUANTIZATION_STEP_KM = 0.5` and pure function `coarsen_distance`:
```python
DISTANCE_QUANTIZATION_STEP_KM: float = 0.5


def coarsen_distance(
    distance_km: float,
    step_km: float = DISTANCE_QUANTIZATION_STEP_KM,
) -> float:
    """Quantize distance in kilometers to mitigate trilateration attacks.

    Non-owners and public callers receive distances snapped to the nearest 0.5 km
    boundary (e.g., 0.23 km -> 0.0 km, 0.35 km -> 0.5 km, 1.15 km -> 1.0 km).
    Multiples of 0.5 km have at most 1 decimal place, preventing floating-point
    representation artifacts in JSON responses.
    """
    if step_km <= 0:
        return distance_km
    quantized = round(float(distance_km) / step_km) * step_km
    return round(quantized, 1)
```

### 4.2 Report Service: `app/services/report.py`
In `ReportService.list_reports`, caller ownership is evaluated dynamically against the report creator:
```python
is_owner = (
    viewer_user_id is not None
    and r.created_by_user_id is not None
    and r.created_by_user_id == viewer_user_id
)

if is_owner:
    # Authenticated report owners receive exact distance (rounded to 2 decimal places)
    distance_km = round(dist / 1000.0, 2)
else:
    # Public and non-owner callers receive quantized distance (rounded to 0.5 km)
    distance_km = coarsen_distance(dist / 1000.0)
```
Crucially, PostGIS spatial operations remain uncompromised:
- Spatial filtering: `ST_DWithin(Report.location, center, radius_meters)` filters records on exact coordinates.
- Spatial ordering: `ORDER BY ST_Distance(Report.location, center)` ranks results by true proximity before pagination.
- Only the serialized `distance_km` field presented to the caller is quantized.

### 4.3 Match APIs: `app/api/matches.py`
In both `list_report_matches` and `get_match_detail`, nested opposite-party report summaries (`MatchReportSummary`) quantize `distance_km`:
```python
quantized_dist_km = coarsen_distance(dist_km) if dist_km is not None else None
```
This ensures that a user inspecting potential matches cannot reverse-engineer the other user's exact coordinates through candidate match distances.

### 4.4 Parameter Boundary Validation: `app/schemas/geo.py`
The `GeoSearchParams` schema enforces:
1. `radius_km` bounds: `ge=Decimal("0.0"), le=Decimal("5.0")` (rejecting queries > 5.0 km or negative radii).
2. Decimal places constraint: Maximum 1 decimal place (`scale <= 1`), rejecting fine-grained step queries such as `radius_km=1.234`.
3. Triplet requirement: `latitude`, `longitude`, and `radius_km` must all be supplied together or all omitted.

---

## 5. Kafka Event & Asynchronous Worker Privacy Boundary

An end-to-end audit verified that coordinates are strictly confined to internal backend processing:

1. **`report.created` and `report.updated` Domain Events**:
   - Contain authoritative `latitude` and `longitude` fields in `DomainEvent.data`.
   - Consumer: Solely `MatchingEventHandler` in the backend worker process.
   - Purpose: Real-time spatial indexing and candidate pair scoring.
   - Access: Purely internal Kafka topic (`boomerang.domain.events`); never routed to external gateways or client websockets.

2. **`match.alert_ready` Domain Event**:
   - Emitted when a candidate match achieves score $\ge 75$.
   - Payload: `match_id`, `missing_report_id`, `found_report_id`, `score`, `classification`, `item_title`.
   - Verified: Zero coordinates (`latitude`, `longitude`, `coordinates`) exist in the event model.

3. **In-App & FCM Notification Boundary**:
   - `NotificationResponse.sanitize_data` scrubs all keys matching `SENSITIVE_DATA_KEYS`:
     `{"fcm_token", "token", "latitude", "longitude", "coordinates", "verification_secret", "secret", "password", "pin"}`.
   - Client applications never receive raw coordinates in notification envelopes or payloads.

---

## 6. Rate Limiting Integration Hook (Phase 10.3 Architecture)

While 0.5 km quantization prevents mathematical trilateration from a passive 3-query sample, an active attacker issuing repeated queries can exploit remaining inference channels (see Section 9).

To neutralize automated search probing, Phase 10.1.2 establishes the integration hook for Phase 10.3 Rate Limiting (`SEC-QUOTA-001`):

```python
# Phase 10.3 Integration Contract: Geo-Query Quota Hook
# Key: f"quota:geo_query:{client_ip_or_user_id}"
# Limit: 30 geographic queries per minute for authenticated users; 10 per minute for anonymous callers.
# Scope: Applies specifically to endpoints with GeoSearchParams (GET /api/v1/reports with lat/lon/radius).
```

When Phase 10.3 implements the Redis token bucket middleware, the `GeoSearchParams` dependency will plug directly into the geo-specific rate limiter.

---

## 7. Verification & Test Coverage

### 7.1 Dedicated Hardening Test Suite: `tests/test_geo_privacy_hardening.py`
A comprehensive, standalone test suite containing 7 specialized tests was implemented:

1. **`test_coarsen_distance_quantization_steps`**: Verifies boundary quantization across 7 discrete distance points and checks clean float representations.
2. **`test_public_and_non_owner_distance_quantized`**: Asserts public receives $0.5\text{ km}$ while owner receives $0.35\text{ km}$.
3. **`test_nested_match_summary_quantized_distance`**: Verifies quantization on `MatchReportSummary.distance_km` in `/reports/{id}/matches` and `/matches/{id}`.
4. **`test_radius_parameter_bounds_and_decimals`**: Validates 422 responses for radius $> 5.0$, negative radius, $> 1$ decimal place, and incomplete triplets.
5. **`test_distance_sorting_preserves_quantization`**: Verifies results are sorted by true PostGIS geographic distance while all returned `distance_km` values are quantized to multiples of 0.5 km.
6. **`test_kafka_event_and_notification_privacy_boundaries`**: Asserts event schemas and `sanitize_data` strip sensitive coordinate keys.
7. **`test_repeated_query_triangulation_defeated`**: Simulates 3 vantage point queries around a target report ($1.27\text{ km}, 1.27\text{ km}, 0.00\text{ km}$) and asserts that all returned distances are quantized to $1.5\text{ km}$ and $0.0\text{ km}$.

### 7.2 Regression Suite Updates
- `tests/test_location_privacy.py`: Updated assertion on line 456 to assert `inside_item["distance_km"] == 0.5`.
- `tests/test_matching_api.py`: Updated assertion on line 208 to assert `opp["distance_km"] == 0.5`.

---

## 8. Product Compatibility Audit

An exhaustive audit of the Flutter client (`frontend/lib/services/map_config.dart`, `frontend/lib/services/report_repository.dart`) and UI test suites verified:

1. **Radius Values**:
   - `MapConfig.supportedRadiiKm = [0.5, 1.0, 2.0, 5.0]`
   - `MapConfig.defaultRadiusKm = 5.0`
   - All supported UI chips (500m, 1km, 2km, 5km) strictly satisfy the $[0.0, 5.0]$ boundary and have $\le 1$ decimal place.
2. **Client Parameter Construction**:
   - `ReportRepository` clamps requests via `radiusKm.clamp(0.1, 5.0)` and formats via `toStringAsFixed(1)`.
   - The backend constraint perfectly matches frontend parameter construction.
3. **Zero Functionality Restriction**:
   - No valid discovery, mapping, or item search functionality is unintentionally restricted.
   - Note on Wide-Area Discovery: Users in low-density or rural areas seeking items $> 5.0\text{ km}$ away must shift their map anchor point, which aligns with Boomerang's hyper-local community discovery architecture.

---

## 9. Final Adversarial Review: Remaining Inference Channels & Exposure

A rigorous adversarial security audit was conducted against the uncommitted implementation. Four reproducible inference channels were analyzed, mathematically modeled, and codified into a dedicated adversarial test suite: `tests/test_geo_privacy_adversarial.py`.

### 9.1 Channel 1: Exact-Distance Ordering & Relative Proximity Inversion (`ORDER BY distance`)

#### The Attack Mechanism:
`GET /api/v1/reports?sort=distance` orders SQL rows using `ORDER BY ST_Distance(Report.location, search_point) ASC` before pagination. Even though the serialized JSON output shows `distance_km = 0.5` for all nearby items, the database ranks them by their authoritative, uncoarsened proximity.

If an attacker targets Report A at $(x_A, y_A)$ and identifies or introduces a reference/decoy Report B at $(x_B, y_B)$:
- Moving search origin $P$ south of both items causes $dist(P, A) < dist(P, B)$, returning `[A, B]`.
- Moving search origin $P$ north of both items causes $dist(P, B) < dist(P, A)$, returning `[B, A]`.
- As $P$ crosses the perpendicular bisector hyperplane between A and B, the order inverts.
- An attacker can binary search on probe latitude $P_{\text{lat}}$ to isolate the exact latitude where the relative order flips. At this point, $dist(P, A) = dist(P, B)$, recovering a linear constraint on A's true location. With two reference points, the intersection of two bisectors reconstructs A's exact location with sub-meter precision.

#### Empirical Test:
`test_adversarial_distance_order_inversion_bisector_recovery` placed Report A at `(32.0000, 32.0000)` and Decoy B at `(32.0010, 32.0000)`. In 12 binary search queries between `31.9980` and `32.0030`, the test isolated the midpoint latitude `32.0005` to within $0.00002$ degrees ($< 2\text{ meters}$)!

---

### 9.2 Channel 2: Radius Membership Attacks (`ST_DWithin` Oracle)

#### The Attack Mechanism:
The spatial filter `func.ST_DWithin(Report.location, search_point, radius_meters)` acts as a pure boolean oracle:
$$\text{Is } \|X_{\text{target}} - P\|_2 \le r \quad \implies \quad \text{target\_id} \in \text{response.items}$$
While `radius_km` is constrained to $\le 1$ decimal place ($0.1, 0.2, ..., 5.0$), probe coordinates `latitude` and `longitude` in `GeoSearchParams` accept arbitrary floating-point precision (6+ decimal places).

An attacker does not need `distance_km` at all:
1. Fix `radius_km = 1.0` ($1000\text{m}$) and fix probe longitude.
2. Binary search on probe latitude. If the target appears in `items`, probe is within 1000m; if absent, probe is outside 1000m.
3. In $\approx 14$ queries ($\log_2(1000\text{m} / 0.1\text{m}) \approx 14$), the attacker isolates the exact boundary latitude $P_{\text{bound}}$ where $dist(P_{\text{bound}}, X_{\text{target}}) = 1000.0\text{ meters}$.
4. True target latitude is immediately recovered: $lat_{\text{target}} = lat_{\text{bound}} + \frac{1000\text{m}}{\text{meters\_per\_degree}}$.

#### Empirical Test:
`test_adversarial_boundary_membership_bisection_attack` placed a target report at `(33.500000, 33.500000)`. In 14 queries at `radius_km = 1.0`, the bisection located the southern boundary at `33.491017` and reconstructed the target's latitude within $15\text{ meters}$!
**Finding**: Radius parameter validation alone does *not* prevent bisection attacks because probe coordinates $(lat, lon)$ have unconstrained resolution.

---

### 9.3 Channel 3: Quantization Step Transition Probing (`coarsen_distance`)

#### The Attack Mechanism:
`coarsen_distance` rounds `dist_km / 0.5`. This introduces sharp transition boundaries at:
$$\text{Thresholds: } 0.250\text{ km}, 0.750\text{ km}, 1.250\text{ km}, 1.750\text{ km}, ...$$
When a probe moves continuously along a line, `distance_km` jumps from `0.5` to `1.0` at the exact point where true distance crosses $750.0\text{ meters}$.
By binary searching for the coordinate where this step occurs, an attacker identifies a probe point with an *exact, unquantized distance of $750.0\text{ meters}$*. Three such transition points re-enable classical trilateration circles with exact radii $r = 750\text{m}$.

#### Empirical Test:
`test_adversarial_quantization_step_transition_attack` placed a report at `(34.000000, 34.000000)`. In 10 queries, the bisection located the `0.5 -> 1.0` step transition latitude, isolating the exact $750\text{m}$ contour within $15\text{ meters}$.

---

### 9.4 Channel 4: Pagination Offset & Rank Leakage

#### The Attack Mechanism:
When multiple reports exist in a search area, pagination (`page`, `page_size=1`) exposes the exact rank of an item ordered by `ST_Distance`.
As the search probe moves, items transition across page boundaries (e.g. from Page 1 to Page 2), revealing rank shifts and confirming proximity changes without direct distance values.

#### Empirical Test:
`test_adversarial_pagination_rank_leakage` placed two reports and verified that shifting the search probe caused items to swap between Page 1 and Page 2.

---

## 10. Adversarial Test Results & Execution Summary

| Test File | Test Identifier | Channel Tested | Result | Duration |
| :--- | :--- | :--- | :--- | :--- |
| `tests/test_geo_privacy_adversarial.py` | `test_adversarial_distance_order_inversion_bisector_recovery` | `ORDER BY distance` Bisector Inversion | **PASSED** | 1.8s |
| `tests/test_geo_privacy_adversarial.py` | `test_adversarial_boundary_membership_bisection_attack` | `ST_DWithin` Oracle Bisection | **PASSED** | 1.9s |
| `tests/test_geo_privacy_adversarial.py` | `test_adversarial_quantization_step_transition_attack` | Step Boundary $750\text{m}$ Contour Probing | **PASSED** | 1.4s |
| `tests/test_geo_privacy_adversarial.py` | `test_adversarial_pagination_rank_leakage` | Pagination Rank Shifting | **PASSED** | 0.9s |
| `tests/test_geo_privacy_hardening.py` | 7 Hardening Verification Tests | Quantization, Ownership, Radius, Sorting | **PASSED** | 5.5s |
| **Combined Geo Privacy Suite** | **11 Total Tests** | **Comprehensive Hardening + Adversarial** | **11 PASSED** | **11.52s** |

---

## 11. Architectural Verdict: Is Further Remediation Necessary?

### Honest Security Conclusion:
**YES. Distance quantization and radius bounds alone do NOT completely prevent location inference by an active adversary issuing repeated queries.**

- **What Phase 10.1.2 Successfully Solves**:
  It completely defeats *passive, opportunistic, single-shot* trilateration. An attacker or scraping bot recording standard API responses from 3 vantage points cannot solve circle intersection equations because the distances are quantized to 500m bands ($\approx 1,592\times$ uncertainty expansion).
- **What Remains Exposed**:
  An *active* adversary who can issue 10–20 automated queries with arbitrary probe coordinates can still exploit:
  1. `ST_DWithin` presence/absence bisection (recovers location to ~15m in 14 queries).
  2. Quantization step transitions (recovers exact 750m circles in 10 queries).
  3. `ORDER BY distance` relative ranking (recovers perpendicular bisectors in 12 queries).

### Mandatory Next Steps (Phases 10.3 & Beyond):
1. **Phase 10.3 Geographic Query Rate Limiting (`SEC-QUOTA-001`) [MANDATORY]**:
   All repeated bisection attacks require executing 10 to 30 rapid, dense spatial queries from sliding probe coordinates. Implementing a strict Redis token-bucket quota (e.g. 10 geographic queries/min for anonymous callers, 30/min for authenticated users) breaks the $O(\log N)$ bisection loop, making automated boundary searching prohibitively slow and operationally detectable.
2. **Future Consideration: Probe Coordinate Grid Snapping**:
   In Phase 10.4, consider snapping input `latitude` and `longitude` search parameters to 2 decimal places (~1.1 km grid) before executing PostGIS queries, preventing micro-stepping of search origins.
3. **Future Consideration: Bucketed Distance Sorting**:
   In Phase 10.4, order public distance queries by quantized bucket (`ORDER BY round(distance_col / 500.0) ASC, created_at DESC`) so items within the same 500m bucket do not leak relative distance ranking.

---

## 12. Exact Uncommitted Git Status

Working tree status across Phase 10.1.2 changes:

```
 M .agents/AGENT_MEMORY.md
 M app/api/matches.py
 M app/services/geo.py
 M app/services/report.py
 M docs/phase_10_1_1_gps_privacy_remediation.md
 M tests/test_location_privacy.py
 M tests/test_matching_api.py
?? docs/phase_10_1_2_geographic_query_privacy.md
?? tests/test_geo_privacy_adversarial.py
?? tests/test_geo_privacy_hardening.py
```

### Detailed Summary of Working-Tree Modifications:
1. **`app/services/geo.py`**:
   - Added `DISTANCE_QUANTIZATION_STEP_KM = 0.5`.
   - Added pure helper function `coarsen_distance(distance_km: float, step_km: float = 0.5) -> float`.
2. **`app/services/report.py`**:
   - In `list_reports`: Report owners receive exact distance (`round(dist / 1000.0, 2)`), while public and non-owner callers receive quantized distance (`coarsen_distance(dist / 1000.0)`).
   - Authoritative PostGIS filtering (`ST_DWithin`) and order-by sorting remain unchanged.
3. **`app/api/matches.py`**:
   - In `list_report_matches` and `get_match_detail`: Nested opposite-party report summaries (`MatchReportSummary.distance_km`) are quantized using `coarsen_distance`.
4. **`tests/test_location_privacy.py`**:
   - Updated assertion on line 456 to assert `inside_item["distance_km"] == 0.5`.
5. **`tests/test_matching_api.py`**:
   - Updated assertion on line 208 to assert `opp["distance_km"] == 0.5`.
6. **`tests/test_geo_privacy_hardening.py`**:
   - New 7-test suite for Phase 10.1.2 mitigations.
7. **`tests/test_geo_privacy_adversarial.py`**:
   - New 4-test adversarial review suite proving remaining inference channels (`ORDER BY distance`, `ST_DWithin` bisection, step transitions, pagination).
8. **`.agents/AGENT_MEMORY.md`**:
   - Updated Production-Readiness checklist and Session Log.
9. **`docs/phase_10_1_2_geographic_query_privacy.md`**:
   - Comprehensive documentation deliverable including the full adversarial review.
