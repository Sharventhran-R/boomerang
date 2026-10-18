# Project Memory

## Current State
- Initialized Python backend setup with FastAPI, SQLAlchemy, PostgreSQL, PostGIS, aiokafka, and JWT authentication.
- Configured Ruff for linting and formatting.
- Configured mypy for strict type checking.
- Configured pytest for testing.

## Architectural Decisions
- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL, PostGIS, Pydantic v2.
- Messaging: Apache Kafka (aiokafka).
- Frontend: Flutter, Dart (to be implemented).
- Environment: Project-local `.venv`.
- Guardrails: Strict type checking, no untyped variables, minimal diffs, mandatory tests before task completion.
- Git: Git operations are strictly developer-controlled (the agent must never modify repository history or staging state).

## Session Log
- 2026-10-02: Initialized agentic workflow guardrails.
- 2026-10-02: Completed Phase 1 (Backend Infrastructure). 
  - Implemented FastAPI application with `/health` endpoint.
  - Setup PostgreSQL + PostGIS with `docker-compose.yml`.
  - Configured SQLAlchemy 2.x (async engine) and Alembic.
  - Environment variables set up with `.env` and `.env.example` via pydantic-settings.
  - Added `greenlet` dependency for async SQLAlchemy.
  - Formatted codebase and passed `ruff`, `mypy`, and `pytest`.
  - Known limitation: Docker is not currently available in the environment to verify PostgreSQL connectivity natively. Tests adapted to succeed via graceful fallback.
- 2026-10-06: Completed Phase 2 (Database Domain Model).
  - Created SQLAlchemy 2.x declarative models: User, Report, ReportImage, RecoveryRequest.
  - Consolidated MISSING and FOUND reports into a single `reports` table with a `type` enum.
  - Implemented PostGIS location mapping using `geoalchemy2.types.Geography(geometry_type="POINT", srid=4326)`.
  - Implemented recovery-request design using explicit `requester_id` and `recipient_id`.
  - Included lightweight verification field `verification_response` in `recovery_requests`.
  - Added constraints (reward >= 0, requester != recipient) and indexes.
  - Configured `alembic/env.py` to import models and generated migration `b3feb293d5d0_phase_2_domain_model.py`.
  - Created `tests/test_models.py` with graceful fallback skipping persistence assertions when Docker/PostGIS is unavailable.
  - Passed ruff, mypy, and pytest validations.
- 2026-10-06: Verified Phase 2 with Real PostgreSQL/PostGIS Instance.
  - Successfully ran `alembic downgrade -1` and `alembic upgrade head`.
  - Created test users, MISSING/FOUND reports with `POINT` location inserted and queried via PostGIS `ST_DWithin`.
  - Verified constraints successfully (Duplicate email rejection, negative reward rejection, self-recovery rejection, and foreign keys).
  - Verified recovery directions work appropriately without directionality assumptions.
  - Re-ran tests natively, resulting in 4 passing tests.
- 2026-10-06: Completed Phase 3 (Authentication & Authorization).
  - Created `UserSession` model for storing hashed refresh tokens.
  - Implemented JWT encoding/decoding using `PyJWT`.
  - Implemented secure password hashing using `argon2-cffi`.
  - Implemented authentication schemas (`UserCreate`, `UserLogin`, `Token`, `RefreshTokenRequest`).
  - Implemented API endpoints `/api/v1/auth/register`, `/login`, `/refresh`, `/logout`, and `/users/me`.
  - Added FastAPI dependencies for current user retrieval via JWT.
  - Formatted codebase, fixed typing, and created robust async integration tests using `httpx` (passing).
  - Advanced features like Email verification and MFA are intentionally deferred to future phases.
  - Next authorized phase: Phase 4 — Missing/Found Reports.
- 2026-10-07: Completed Phase 4 (Report Management + Basic Search + Images).
  - Implemented S3-compatible local object storage configuration using `aioboto3` (MinIO support).
  - Implemented report services (`create_report`, `list_reports`, `get_report_by_id`, `update_report`, `upload_report_image`, `delete_report_image`).
  - Solved complex PostGIS parsing errors by correctly utilizing `WKTElement(..., srid=4326)` and `func.ST_X/Y(Report.location.cast(Geometry))`.
  - Implemented secure report endpoints (`/api/v1/reports`) with route-level authorization (only creators can modify/upload/delete).
  - Added strict status transition constraints (e.g., ACTIVE -> RESOLVED/CANCELLED).
  - Configured `NullPool` in SQLAlchemy testing teardowns to resolve transaction rollback `InterfaceError`s.
  - Formatted codebase, fixed typing, and created robust async integration tests using `httpx` (all tests passing).
- 2026-10-07: Fixed MinIO Integration Tests.
  - Replaced `quay.io/minio/aistor/minio` (which required a license) with a free community MinIO image (`elestio/minio`).
  - Added real MinIO integration tests (`test_real_minio_image_upload`, `test_real_minio_image_delete`) that interact directly with the API and S3 bucket without mocking.
  - Reconfigured tests to check MinIO availability using `head_bucket` on the target bucket, properly failing on authentication/license errors but skipping gracefully only on genuine network unreachability.
  - Result: 17 integration tests passing. No skipped MinIO tests.
- 2026-10-08: Completed Phase 5.1 (Geospatial Query Foundation).
  - Implemented `GeoSearchParams` Pydantic model for geospatial validation (latitude, longitude, radius_km).
  - Configured radius bounds (0.0 to 5.0 km) and restricted precision to 1 decimal place.
  - Implemented cross-field consistency validation (all 3 must be provided together).
  - Integrated `get_geo_params` FastAPI dependency into `list_reports` endpoint.
  - Added `sort=distance` parameter validation ensuring it is only used with geographic coordinates.
  - Required robust FastAPI integration testing bypassing default Pydantic 500 errors when instantiated directly as dependency variables.
  - Re-verified database consistency ensuring `location` is strictly validated.
  - Next authorized phase: Phase 5.2. Do NOT implement Phase 6+ functionality.
- 2026-10-08: Completed Phase 5.2 (PostGIS Radius Filtering).
  - Extended `list_reports` service logic to ingest `GeoSearchParams` mapping coordinates.
  - Converted `radius_km` directly to `meters` safely supporting edge-cases up to precisely 0.0.
  - Replaced manual Python spatial validation relying fully on `ST_DWithin` database filtering (`func.ST_DWithin`).
  - Corrected GeoAlchemy2 interaction for distance computation by casting inputs strictly for safe PostGIS boundary indexing.
  - Constructed exact precise integration tests covering inside radius boundaries, exactly out-of-bounds, and extreme ranges.
  - Ensured spatial searching layers non-destructively alongside pagination, text searches, and explicit model conditions.
- 2026-10-08: Completed Phase 5.3 (PostGIS Distance Calculation).
  - Added `distance_km` computed property to `ReportResponse` schema.
  - Integrated `func.ST_Distance` calculation natively within PostGIS query for geographic spatial boundaries mapping to precise physical distance.
  - Included math handling distance translation seamlessly converting raw PostGIS output strictly from `meters` to `kilometers` bounded to exact 2-decimal rounded precision safely filtering exact overlapping matches (`0.00`).
  - Assured `distance_km` stays functionally removed (`None`) for traditional textual or category searches properly isolating spatial and index layers.
  - Developed and verified complex integration tests assessing output boundaries checking precise return outputs seamlessly over varying geographic ranges.
  - Intentionally deferred Phase 5.4 functionality (distance sorting).
- 2026-10-08: Completed Phase 5.4 (Search + Distance Sorting Integration).
  - Configured `sort=distance` parameter logic extending validation specifically mapping onto mandatory latitude/longitude/radius combinations effectively enforcing 422 validations precisely correctly when missing.
  - Implemented deep database tier SQL ordering `asc(distance_col), desc(Report.created_at), asc(Report.id)` safely structuring determinism avoiding pagination inconsistencies across equal ranges.
  - Structured ordering natively interacting securely within `.limit(page_size)` maintaining execution efficiency completely avoiding python level data ingestion sorting overheads securely via PostGIS `ST_Distance`.
  - Added deterministic tests asserting sorting boundary logic precisely (testing output order correctly mapping exactly distance calculations while asserting 5km out of bounds distances are excluded correctly).
  - Ensured original sort options (`newest`/`oldest`) run identically properly isolating logic paths securely.
- 2026-10-09: Completed Phase 5.5 (Final Testing & Verification).
  - Inspected the current state (git status, git diff) ensuring clean repository and adherence to guardrails.
  - Successfully ran automated quality checks: pytest (22 tests passed), Ruff linting/formatting, Mypy typecheck, and docker-compose configurations.
  - Verified StarletteDeprecationWarning from Pydantic `HTTP_422_UNPROCESSABLE_ENTITY` and modernized `app/api/reports.py`, `app/schemas/geo.py`, and `app/services/storage.py` to use `HTTP_422_UNPROCESSABLE_CONTENT`, resulting in a completely silent, warning-free test output.
  - Asserted that distance filters, PostGIS indexing `ST_DWithin`, and determinism `ST_Distance` order functionality behaves correctly via robust backend test suites covering inclusive boundary checks and missing parameter validations.
  - Confirmed Phase 5 is stable, properly bounded to geospatial backend integration, without spilling into Phase 6 implementations.
  - Phase 5.5 Follow-up: Addressed Code Review findings F-2 and F-3.
    - F-2: Fixed non-deterministic pagination for `newest`/`oldest` sort modes by adding `Report.id` as a secondary ASC sort key. Added `test_deterministic_sorting_newest_oldest` test isolating items using a UUID search tag and explicitly sharing a `created_at` timestamp.
    - F-3: Fixed decimal precision check rejecting equivalent float-scaled values (e.g. `1.10`) by adding `.normalize()` prior to evaluating exponent scale. Added trailing zero tests ensuring 0-5.0km scaling holds true under varying precisions.
    - F-1, F-4, F-5 consciously deferred as non-blocking issues for Phase 5 completion.
  - Next authorized phase: Phase 6 — Flutter Mobile + Web.
- 2026-10-10: Completed Phase 6.2 (Frontend Foundation).
  - Scaffolded Flutter web/mobile workspace in `frontend/`.
  - Created centralized dark `ThemeData` configuration mapping Stitch UI design tokens to Flutter native styles (`AppTheme`).
  - Defined explicit colors (MISSING, FOUND, Reward, etc.) preserving exact brand color-codes.
  - Standardized consistent spacing, 12px rounded borders, input styles, and button styles.
  - Replaced default counter app with a minimal Boomerang-branded placeholder verifying theme compatibility.
  - Successfully passed `flutter analyze` and `flutter test`.
- 2026-10-10: Completed Phase 6.3 (Home and Explore Map).
  - Built `HomeScreen` implementing the core search, filter buttons, category pills, and nearby reports feed mirroring Stitch HTML.
  - Built `MapScreen` implementing a non-interactive dark map placeholder safely isolating SDK dependencies, paired with floating search tools and a responsive `DraggableScrollableSheet` for nearby reports.
  - Constructed `MainNavScreen` integrating a persistent bottom navigation bar matching the design layout.
  - Engineered reusable widgets: `ReportCard`, `StatusLabel`, and `RewardLabel`.
  - Replaced deprecated `.withOpacity` methods with modern `.withValues(alpha:)` across the UI conforming strictly to Flutter 3.44.8 lint rules.
  - Passed all strict guardrails: zero backend modifications, mock data exclusively, formatting clear, 0 analyzer issues, successfully passed all widget tests.
- 2026-10-10: Completed Phase 6.3 UI Corrections.
  - Performed a UI consistency audit against the 14 Stitch exports (`ui_consistency_review.md`).
  - Added `google_fonts` dependency and configured centralized typography (Hanken Grotesk and Inter) in `AppTheme`.
  - Added responsive `ConstrainedBox(maxWidth: 600)` wrapper around `MainNavScreen` to prevent desktop viewport stretching while preserving mobile design ratios.
  - Integrated `BackdropFilter` and `ClipRRect` / `ClipOval` across floating map elements (search bar, top header, icons) and the bottom navigation bar to precisely match the glassmorphism aesthetic references.
  - Resolved `WidgetTester` font-fallback flex layout overflow issues by robustly wrapping text strings in `Flexible` and `Expanded` within `home_screen.dart` titles and action cards.
  - Successfully validated layout changes through static analysis and widget tests (`All tests passed!`).
- 2026-10-10: Completed Phase 6.3 Secondary Screens.
  - Scaffolded `SettingsScreen` and `RecoveryRequestsScreen` matching the visual layout and components of the Stitch exports.
  - Added navigation routing from `ProfileScreen` to `SettingsScreen` and `RecoveryRequestsScreen` via `Navigator.push`.
  - Conducted a comprehensive final UI consistency audit for the remaining 10 unimplemented/pending Stitch export screens and documented missing components/views in `ui_consistency_review.md`.
- 2026-10-11: Completed Phase 6.3 Stabilization.
  - Priority 1 (Layout): Fixed horizontal RenderFlex overflow in `settings_screen.dart` by constraining title/subtitle rows and header rows with `Expanded` / `Flexible`. Constrained `profile_screen.dart` user header badge with `Wrap` and stats rows with `Expanded`. Verified layout at 390px viewport.
  - Priority 2 (Navigation): Connected Home "Map View" action to switch to the Map tab. Wired My Reports' pending recovery banner to open `RecoveryRequestsScreen`. Wired Profile's "Browse All Incident Reports" to switch to the My Reports tab. Created `ChooseReportTypeScreen` (`choose_report_type_screen.dart`) as temporary entry point for "Report Missing" and "Report Found" cards.
  - Priority 3 (Search and Filters): Implemented stateful category chip selection in `HomeScreen` filtering mock reports by category. Connected search input to filter reports by title, category, description, and location. Made `RecoveryRequestsScreen` Received (2) and Sent (1) tabs switch selection state and render respective mock records.
  - Priority 4 (Report Actions and Feedback): Implemented `ReportDetailsScreen` (`report_details_screen.dart`) and wired My Reports' "View Details" and Home card taps to it. Configured non-misleading feedback for "Edit Report". Implemented mock confirmation dialogs for "Review & Accept" and "Decline" with updated local badges (`ACCEPTED (MOCK)` / `DECLINED (MOCK)`). Wired Profile "Terminate & Log Out" confirmation dialog and ensured 140px bottom padding clears floating navigation.
  - Verification: Added `frontend/test/stabilization_test.dart`. Formatted with `dart format .`, analyzed with `flutter analyze` (0 issues), and ran `flutter test` (all 8 tests passed). Verified live via Chrome DevTools MCP at 390x844 viewport.
- 2026-10-11: Installed Design Skills, Organized Agent System & Established Design Policy.
  - Installed three design resources at project scope (`.agents/skills/`):
    1. `design-taste-frontend` (`.agents/skills/design-taste-frontend/SKILL.md`): Verified official source `Leonxlnx/taste-skill`.
    2. `web-design-guidelines` (`.agents/skills/web-design-guidelines/SKILL.md`): Verified official source `vercel-labs/agent-skills` with local offline reference `references/guidelines.md`.
    3. `awesome-design` (`.agents/skills/awesome-design/SKILL.md`): Verified official source `EagleFandel/awesome-design` with 55+ design systems in Stitch format (`design-md/`).
  - Generated `skills-lock.json` locking verified sources and hashes.
  - Created `.agents/DESIGN_POLICY.md` formalizing design authority hierarchy, design tokens, Stitch mapping, and Flutter adaptation rules.
  - Updated `.agents/AGENTS.md` with frontend canonical commands, design policy links, and instructions for future agents.
- 2026-10-11: Completed UI Quality Refinement across Flutter frontend.
  - Multi-Skill Application: Applied `design-taste-frontend` for optical hierarchy, card border luminance, and spacing cadence; applied `web-design-guidelines` for accessibility attributes (`Semantics`, `Tooltip`), keyboard focus, interactive touch targets ($\ge 44\text{px}$), and dialog confirmations; referenced `awesome-design` for token consistency.
  - Bottom Navigation Defect Resolution: Fixed critical layout defect in `main_nav_screen.dart` where `ConstrainedBox` inside `_buildNavItem` caused `Center` to expand to the full 600px scaffold height, intercepting viewport taps. Added `widthFactor: 1.0, heightFactor: 1.0` and `constraints: BoxConstraints(maxHeight: 80)` to outer nav bar container.
  - Interactive Overlays & Workflows: Connected interactive district picker (`_showDistrictPicker`) and sort/filter modal sheet (`_showFilterSheet`) in `HomeScreen`; spatial mesh info and location picker in `MapScreen`; item claim/recovery confirmation dialog and discrepancy reporting dialog in `ReportDetailsScreen`.
  - Contrast & Card Hierarchy: Boosted card border contrast to `#2E3134` / `#2A2C2D` across `ReportCard`, `HomeScreen`, `ProfileScreen`, and `ChooseReportTypeScreen` against `#080909` background.
- 2026-10-11: Resolved Map Screen Nearby Reports Expansion Defect.
  - Root Cause: In `map_screen.dart`, `DraggableScrollableSheet` lacked a controller and programmatic toggle. The "Expand" label and drag handle were in a non-scrollable `Column` outside the `scrollController`, ignoring pointer drags. At initial size `0.16` and search bar at `bottom: 96`, the collapsed sheet was submerged behind the floating bottom navigation bar and search bar with zero interactive area.
  - Fix & Interactive Enhancements:
    1. Wired `DraggableScrollableController` (`_sheetController`) with `initState`/`dispose` lifecycle listener updating `_isSheetExpanded` state.
    2. Added `_toggleSheet()` smoothly animating between collapsed (`0.18`) and expanded (`0.60`).
    3. Wrapped drag handle and header row with `GestureDetector(onTap: _toggleSheet, onVerticalDragUpdate: ..., onVerticalDragEnd: ...)` enabling smooth vertical dragging and snap animations directly from the handle and header.
    4. Made "Expand" / "Collapse" an interactive button with dynamic label, icon (`expand_less` / `expand_more`), `Semantics`, and `Tooltip`.
    5. Connected floating filter button (`Icons.tune`) to `_toggleSheet()` matching the Stitch Explore Map reference (`toggleBottomSheet()`).
    6. Positioned floating search bar at `bottom: 148` cleanly above the collapsed peek header; sheet expands over the search bar when opened.
    7. Eliminated layout overflows at 390px viewport in `map_screen.dart` top header and `report_card.dart` status/reward/distance rows using `Expanded`, `Flexible`, and `Wrap`.
- 2026-10-11: Resolved Map Screen Bottom Controls Responsiveness & Overlap Defect.
  - Root Cause: Position-based stacking (`Positioned(bottom: 148)` for search bar and independent `DraggableScrollableSheet`) caused the sheet to overlap and obscure the search input and neighbouring icons (`Icons.tune`, `Icons.near_me`) upon expansion or viewport resize. Furthermore, edge-to-edge sheet stretching broke responsiveness on wide/desktop viewports.
  - Fix Architecture:
    1. Unified Layout Column: Placed `_buildFloatingSearchRow()` (search bar, filter icon, locate GPS icon) and `_buildNearbyReportsPanel()` into a single vertical `Column(mainAxisSize: MainAxisSize.min)` anchored at `Positioned(bottom: 0)` with `Align(alignment: Alignment.bottomCenter)` and `ConstrainedBox(constraints: BoxConstraints(maxWidth: 500))` with `bottom: 92` padding.
    2. Zero Overlap Guarantee: Because the search row and nearby reports panel are sequential children in a vertical `Column`, Flutter's layout engine guarantees they can never overlap under any viewport dimension or orientation.
    3. Responsive Animation: Replaced the fixed fraction sheet with an `AnimatedSize(duration: Duration(milliseconds: 300), curve: Curves.easeOutCubic)` expandable panel with a max-height scrollable list constraint (`maxHeight: 250`).
    4. Responsiveness on Desktop & Mobile: Panel and search controls are cleanly constrained to `maxWidth: 500` centered horizontally, aligning symmetrically with the floating bottom navigation bar.
    5. Interactive Triggers: Expand/collapse is toggled smoothly via the "Expand" / "Collapse" button, the drag handle tap/vertical drag, or the search bar's `Icons.tune` filter button.
  - Automated Verification:
    - Added responsive desktop test `Map screen search bar, neighbouring icons and nearby reports are responsive and do not overlap on desktop` in `test/stabilization_test.dart` at 1280x800 viewport.
    - `dart format .`: All 15 files formatted.
    - `flutter analyze`: 0 issues found.
    - `flutter test`: All 10 tests passed (including smoke, navigation, dialog, mobile, and responsive desktop tests).
    - Preserved zero Git write operations (manual git ownership retained by developer).
- 2026-10-11: Resolved Map Screen Alex Morgan Avatar Profile Routing.
  - Root Cause: In `map_screen.dart`, the Alex Morgan avatar button ('AL' circle in the top right header) was built as an inert `Container` without an interactive gesture detector or routing handler. Furthermore, `MapScreen` lacked an `onNavigateTab` callback from `main_nav_screen.dart`.
  - Fix Architecture:
    1. Added `final ValueChanged<int>? onNavigateTab;` to `MapScreen` constructor.
    2. Connected `MapScreen(onNavigateTab: (index) => setState(() => _currentIndex = index))` in `main_nav_screen.dart`.
    3. Implemented `_navigateToProfile()` in `_MapScreenState` switching to tab 4 (`ProfileScreen`), with fallback `Navigator.push` to `ProfileScreen` if instantiated standalone.
    4. Wrapped Alex Morgan avatar in `Semantics(button: true, label: 'Alex Morgan Profile. Tap to view profile')`, `Tooltip(message: 'Alex Morgan Profile')`, and `InkWell(onTap: _navigateToProfile)` with a 44x44 minimum touch target adhering to `web-design-guidelines`.
  - Automated Verification:
    - Added widget test `Map screen Alex Morgan avatar button navigates to Profile page` in `test/stabilization_test.dart`.
    - Formatted with `dart format .`, verified 0 issues with `flutter analyze`, and all 11 tests passed with `flutter test`. Zero Git write operations.
- 2026-10-11: Completed Full Monochromatic Redesign (Swiss Modernist Architectural Redesign).
  - Scope: Complete visual overhaul across all screens and widgets into a strict monochromatic black, white, and grayscale design system inspired by Swiss modernism, with zero color accents (no red, green, blue, gold, purple, or saturated highlights).
  - Design Direction & Philosophy:
    - Backgrounds: `#080808` (deep obsidian canvas) and `#0D0D0D`.
    - Layered Charcoal Surfaces: `#151515`, `#1C1C1C`, `#242424`.
    - Architectural Borders: `#303030` and `#3A3A3A`.
    - Typography & Telemetry: High-contrast Swiss-modernist typography (`Hanken Grotesk` display titles, `Inter` for data density and telemetry, monospaced coordinates).
    - Status Differentiation: Pure tonal contrast and typography—`MISSING` via `#F5F5F5` on `#202020` with alert indicator; `FOUND` via outlined `#A0A0A0` border on `#141414`.
    - Currency/Rewards: Pure monochrome currency notation (`§` / `$`) without gold or saturated badges.
    - Map Experience: Grayscale tactical coordinate painter (`TacticalMapPainter`), monochrome locator pins, radar grid overlay, and high-contrast telemetry controls.
  - Components & Screens Overhauled:
    1. `frontend/lib/theme.dart`: Strict monochrome palette, architectural 8px/4px corner tokens, crisp button/input themes, zero color accents.
    2. `frontend/lib/ui/widgets/status_label.dart`: Tonal high-contrast MISSING and FOUND labels, monochrome `RewardLabel` (`§`).
    3. `frontend/lib/ui/widgets/report_card.dart`: Monochromatic layout with architectural thumbnail frame, tracking, and border `#303030`.
    4. `frontend/lib/ui/screens/home_screen.dart`: Responsive desktop 2-column layout (`>= 840px`), Swiss-modernist telemetry headers, tactical search/filter bar, quick action cards, and mobile single-column feed.
    5. `frontend/lib/ui/screens/map_screen.dart`: Custom monochromatic tactical coordinate painter (`TacticalMapPainter`), custom monochrome map pins, split desktop layout (`>= 840px`), and collapsible mobile bottom sheet.
    6. `frontend/lib/ui/screens/choose_report_type_screen.dart`: Architectural step indicator (`01 // TYPE SELECT`), high-contrast option cards with telemetry badges, and bottom guidance banner.
    7. `frontend/lib/ui/screens/report_details_screen.dart`: Technical photo frame, crisp metadata table (`ITEM DETAILS & SPECS`), reporter verified badge, and monochrome high-contrast recovery actions.
    8. `frontend/lib/ui/screens/my_reports_screen.dart`: Segmented filter tabs (`All`, `Missing`, `Found`), active pending recovery banner, and report action sheets.
    9. `frontend/lib/ui/screens/recovery_requests_screen.dart`: Pending recovery requests, claimant verification badges, resolution action dialogs, and compact responsive padding.
    10. `frontend/lib/ui/screens/profile_screen.dart`: `AM` avatar, `VERIFIED MEMBER` badge, Swiss-modernist telemetry metrics grid (`2 Active Reports`, `1 Pending`, `12 Resolved`), account management, and session logout.
    11. `frontend/lib/ui/screens/settings_screen.dart`: Telemetry section cards, monochrome toggle switches, responsive layout (tested at 390px mobile viewport), and GNSS/storage controls.
    12. `frontend/lib/ui/screens/login_screen.dart`: Implemented from Stitch export `bd3073925cf34b1ab860362bae730567` in strict monochrome with security telemetry banner and high-contrast inputs.
    13. `frontend/lib/ui/screens/registration_screen.dart`: Implemented from Stitch export `325c904fe37c4927a3dcd8848df4cf58` in strict monochrome with password strength indicators and terms agreement.
    14. `frontend/lib/ui/screens/session_expired_screen.dart`: Implemented from Stitch export `ad0a7a2c83fe49e38176f2ad53275b35` in strict monochrome with warning telemetry and quick re-authentication.
    15. `frontend/lib/ui/screens/main_nav_screen.dart`: Responsive desktop sidebar (`240px`) and floating mobile bottom navigation bar (`76px` max height) with pure monochrome styling.
    16. `frontend/lib/main.dart`: LayoutBuilder integration adapting between desktop full-bleed (`>= 840px`) and centered mobile container (`maxWidth: 600px`).
  - Verification & Quality:
    - Code formatting: `cd frontend; dart format .` (all files formatted cleanly).
    - Static analysis: `cd frontend; flutter analyze` (0 issues found).
    - Unit & Widget Tests: `cd frontend; flutter test` (all 11 tests passed with 0 failures).
    - Git Safety: Complied with manual Git ownership rule; zero git write commands executed.
- 2026-10-11: Completed Mobile-First Redesign Correction.
  - Primary Target: Recomposed the entire application specifically for a modern smartphone viewport (390 × 844 px) as primary product; desktop layout retained strictly as secondary responsive adaptation.
  - Design & Navigation Architecture:
    - Replaced mobile floating overlay with docked 60px bottom navigation bar featuring 5 destinations: Home, Explore, Create (+ action), My Reports, Profile.
    - Ensured bottom bar does not obscure scrolling content (`extendBody: false` with SafeArea respect). Completely hides desktop sidebar on mobile widths (`< 900px`).
    - Stripped out desktop telemetry grids, bloated metrics panels, and complex split-views on mobile in favor of clean Swiss-modernist editorial typography and comfortable 44-48px touch targets.
  - Screen-by-Screen Mobile Recomposition:
    - `home_screen.dart`: Distinctive editorial heading, compact search and district selector with ellipsis truncation (resolved RenderFlex overflow at <= 358px), horizontal category chips, Missing/Found touch cards, and single-column feed of nearby reports.
    - `map_screen.dart`: Full-screen monochromatic tactical placeholder canvas (clearly represented as placeholder vector map), floating controls safely positioned, collapsible/expandable bottom sheet with nearby reports, and compact header (resolved 68px header overflow).
    - `choose_report_type_screen.dart`: Single-column touch cards for Missing Item vs. Found Item with step indicator (`01 // TYPE SELECT`) and forward flow.
    - `report_details_screen.dart`: Prominent item photo frame, status badge, metadata breakdown, and bottom action area.
    - `my_reports_screen.dart`: Segmented filter pills (`All`, `Missing`, `Found`), active pending recovery alert banner, single-column report list without oversized telemetry widgets.
    - `recovery_requests_screen.dart`: Clean `Received` and `Sent` tabs, clear item cards with verification guidance, and accessible accept/decline buttons.
    - `profile_screen.dart`: Mobile profile header (`Alex Morgan`, `AM`), `VERIFIED MEMBER` badge, `OPERATIONAL SUMMARY` 4-box stat row, quick navigation rows, and logout action.
    - `settings_screen.dart`: Grouped mobile settings cards, monochrome switches, and safe text wrapping.
    - `login_screen.dart`, `registration_screen.dart`, `session_expired_screen.dart`: Centered single-column mobile forms with accessible inputs, password toggles, and safe-area margins.
  - Visual Verification via Chrome DevTools MCP:
    - 390 × 844 px (Primary Smartphone): Captured and visually verified Home, Map (collapsed & expanded sheet), Choose Report Type, Report Details, My Reports, Recovery Requests, Profile, Settings, Session Expired, Login, and Registration. Zero layout overflows.
    - 360 × 800 px (Compact Smartphone): Verified clean layout with zero RenderFlex errors.
    - 430 × 932 px (Large Smartphone): Verified proportional responsive scaling and touch comfort.
    - 1280 × 800 px (Desktop Regression Check): Verified desktop sidebar and responsive container fallback intact without console errors.
  - Automated Quality & Testing:
    - `dart format .`: Formatted 18 Dart files.
    - `flutter analyze`: 0 issues found.
    - `flutter test`: 11 of 11 tests passed with 0 failures (`stabilization_test.dart` and `widget_test.dart`).
    - Git Safety: Zero git write commands executed. Ready for manual review and staging by developer.
- 2026-10-11: Completed Phase 6.4 (Report Creation and Local State).
  - Scope & Architecture:
    - Unified Domain Model (`report_model.dart`): Consolidated report model supporting `id`, `title`, `category`, `description`, `locationDescription`, `dateTime`, `status`, `reward`, `distance`, `timeAgo`, `photos`, and `isUserReport`.
    - Shared In-Memory Repository (`report_repository.dart`): Created `ChangeNotifier` singleton `ReportRepository` managing all active reports and user reports in-memory. Eliminates isolated hardcoded lists across screens. Pre-populated with baseline mock reports (REP-001 through REP-008). Supports reactive updates via `createReport` and `resetToDefault` for unit tests.
    - Mobile-First Creation Form (`create_report_screen.dart`): Implemented responsive, scrollable creation form featuring:
      - Independent MISSING / FOUND segmented type switcher.
      - Required fields: Item title, category picker modal, description, location input with quick presets, loss/discovery date & time picker.
      - Optional photos: Attachment simulation sheet with preset captures, preview thumbnails, and individual deletion.
      - Optional reward: Exclusively available for MISSING reports. Automatically hidden and cleared when switched to FOUND. Rejects negative reward values (`reward >= 0`). Includes quick preset buttons ($25, $50, $100, $250).
      - Duplicate submission prevention with loading indicator and disabled submit button during async simulation.
      - Confirmation feedback via SnackBar with immediate "View" action button linking directly to the new report details.
    - Screen Integration & Shared State Reactivity:
      - `choose_report_type_screen.dart`: Connected cards to initiate `CreateReportScreen` with appropriate initial status; returns smoothly to Home upon completion.
      - `home_screen.dart`: Subscribes directly to `ReportRepository.instance.reports`; newly created items appear at the top of the feed and filter properly.
      - `map_screen.dart`: Subscribes to `ReportRepository.instance.reports`; dynamic badge count (`18 items` baseline + created reports) and reflects items in the expandable nearby reports list.
      - `my_reports_screen.dart`: Subscribes to `ReportRepository.instance.userReports`; newly created reports appear under the user's active report tab.
    - Monochromatic Design Consistency:
      - Maintained strict Swiss-modernist palette (`#080808`, `#151515`, `#1C1C1C`, `#242424`, `#303030`, pure white `#FFFFFF` CTAs).
      - Completely avoided colorful accents, neon gradients, or colored status badges.
      - Responsive across mobile widths (360px, 390px, 430px) and desktop (>840px). Resolved narrow viewport button overflow in `my_reports_screen.dart` by adding `Flexible` text clipping.
  - Automated Quality & Testing:
    - New Phase 6.4 test suite (`test/phase_6_4_test.dart`): 9 comprehensive tests covering field validation, reward visibility & clearing, negative reward rejection, async submission & duplicate protection, multi-screen propagation (Home -> Map -> My Reports), Found reports without reward, and 360px/430px responsiveness.
    - Existing suites: `test/stabilization_test.dart` (10 tests) and `test/widget_test.dart` (1 test).
    - Overall test result: 20 of 20 tests passing (`flutter test`).
    - Static analysis: `flutter analyze` passed with 0 issues.
    - Formatting: `dart format .` completed cleanly across all Dart files.
  - Guardrails & Repository Safety:
    - Zero Git write operations performed. Ready for developer review and staging.
- 2026-10-12: Completed Phase 6.5 (FastAPI Backend Integration).
  - Scope & Architecture:
    - Connected Flutter frontend to FastAPI backend using exact existing REST contracts (`/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/logout`, `/api/v1/users/me`, `/api/v1/reports`, `/api/v1/reports/{id}`, `/api/v1/reports/{id}/images`).
    - API & Session Infrastructure:
      - `TokenStorage`: Platform-safe storage abstraction (`InMemoryTokenStorage` for runtime/tests, extensible for flutter_secure_storage).
      - `ApiClient`: Unified HTTP client supporting environment-based base URLs (`API_BASE_URL`, Android emulator `10.0.2.2:8000`, Desktop/Web `127.0.0.1:8000`), Bearer token auto-attachment, transparent 401 retry with access token refresh, multipart form data image upload, and structured FastAPI error extraction.
      - `AuthService`: Singleton session manager handling registration, login, refresh rotation, `/users/me` profile persistence, session recovery on launch, session termination, and unauthenticated state guards.
      - `ReportRepository`: Live API integration handling `/api/v1/reports` with server-side query filters, client-side creator isolation (`created_by_user_id` matching `currentUser.id` for `userReports`), UUID detail fetching, multipart image uploading, and test-isolated mock mode retention.
    - Screen Integrations:
      - `LoginScreen`: Wired to `AuthService.instance.login`, loading states, error banner display, and navigation callbacks.
      - `RegistrationScreen`: Wired to `AuthService.instance.register` and auto-login, validation, and error banner display.
      - `CreateReportScreen`: Integrated backend creation with float coordinates, optional reward restricted to MISSING reports, sequential multipart image upload, and duplicate-prevention state.
      - `HomeScreen`: Integrated live backend reports with pull-to-refresh, error retry card, and filter preservation.
      - `ReportDetailsScreen`: Integrated backend UUID fetch with loading spinner, error fallback, and telemetry coordinate display.
      - `MyReportsScreen`: Integrated current user filtering with "Authentication Required" prompt for guest operators.
      - `ProfileScreen`: Connected to `AuthService.instance.currentUser`, displaying verified status and two-step logout confirmation.
  - Automated Quality & Testing:
    - Comprehensive Phase 6.5 test suite (`test/phase_6_5_test.dart`): 27 tests covering registration, login, refresh rotation, transparent 401 retry, session restoration, backend model parsing, report listing & query filters, user-report filtering, UUID detail retrieval, sequenced image uploads, 422 validation, and full widget interactions.
    - All existing suites passing: `test/phase_6_4_test.dart` (9 tests), `test/stabilization_test.dart` (10 tests), `test/widget_test.dart` (1 test).
    - Full test suite: 47 of 47 tests passed (`flutter test`).
    - Static analysis: `flutter analyze` passed with 0 issues.
    - Formatting: `dart format .` verified with 0 formatting changes needed.
  - Guardrails & Repository Safety:
    - Strict adherence to manual Git ownership (zero Git write commands executed).
    - Preserved existing monochromatic Swiss-modernist design tokens (`#080808`, `#151515`, `#303030`).
    - Zero modifications to backend API contracts, database schemas, or migrations.
- 2026-10-13: Executed Phase 6.5 Live Integration Smoke Test.
  - Live Infrastructure Verification:
    - PostgreSQL 16 + PostGIS on `localhost:5432` verified and healthy (`SELECT 1`).
    - Alembic migrations verified at head (`491e9669403b`).
    - MinIO S3 object storage on `http://localhost:9000` initialized with `tracker-images` bucket.
    - FastAPI uvicorn daemon running on `http://127.0.0.1:8000`, `/health` returning `{"status": "ok", "database": "ok"}`.
  - Live API & Client Verification (PASS across all 10 checks):
    - Health check, user registration, JWT login, profile retrieval (`/api/v1/users/me`).
    - Missing report creation with float coordinates and reward, report listing with pagination.
    - Single report retrieval by UUID, multipart image upload to MinIO/S3, token refresh rotation, and logout session revocation.
  - Fixes Identified & Resolved:
    - Added `CORSMiddleware` to `app/main.py` allowing cross-origin requests from Flutter Web and local development clients.
    - Fixed image upload MIME type in `ApiClient.uploadMultipart` by passing `contentType: MediaType.parse(contentType)` via `http_parser`, resolving a backend 422 error caused by default `application/octet-stream`.
    - Added `ReportRepository.instance.configure()` in `frontend/lib/main.dart` to ensure live API mode on application launch.
  - Automated & Live Test Results:
    - Live Flutter integration test suite (`test/live_backend_smoke_test.dart`): 8 of 8 passed against real backend.
    - Full Flutter test suite (`flutter test`): 55 of 55 tests passed.
    - Static analysis: `flutter analyze` 0 issues; `dart format` cleanly formatted.
    - Backend test suite: `pytest tests/` 23 of 23 passed.
  - Repository Safety:
    - Zero Git write operations executed. Developer retains manual git ownership.
- 2026-10-13: Completed Phase 6.6 — Real Maps & Geolocation.
  - Scope: Replaced placeholder `TacticalMapPainter` with real `flutter_map` (CartoDB Dark Matter tiles), integrated backend report markers with grayscale status differentiation, implemented real GPS permissions & position retrieval via `LocationService` with manual map-based fallback, and connected radius discovery (`radius_km` 0.5–5.0 km, 1 decimal place) to the FastAPI PostGIS backend.
  - Architecture & Services Implemented:
    1. `MapConfig` (`frontend/lib/services/map_config.dart`): CartoDB Dark Matter tile layer configuration (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png`), OpenStreetMap & CARTO attribution, default viewport center `LatLng(50.4501, 30.5234)`, zoom boundaries 3.0 to 18.0, and supported discovery radii `[0.5, 1.0, 2.0, 5.0]`. No secret API keys required.
    2. `LocationService` (`frontend/lib/services/location_service.dart`): Device GPS geolocation using `geolocator`, comprehensive permission handling (`denied`, `permanentlyDenied`, `disabled`, `timeout`), mockable test instance injection, manual fallback coordinate placement (`setManualLocation`), and zero coordinate fabrication.
    3. `ReportRepository` (`frontend/lib/services/report_repository.dart`): Added radius search parameters (`latitude`, `longitude`, `radius_km`), strict serialization with 1 decimal place (`.toStringAsFixed(1)`), clamped radius within backend boundary (`0.1` to `5.0` km), automatic `sort='distance'` sorting when coordinates are active, and `clearGeoSearch()` capability.
    4. `MapScreen` (`frontend/lib/ui/screens/map_screen.dart`): Real `FlutterMap` canvas with `TileLayer`, `CircleLayer` displaying search radius, and `MarkerLayer` with monochromatic markers. Grayscale differentiation: Missing reports (`#151515`, `Icons.help_outline`, white border) vs Found reports (`#222222`, `Icons.check_circle_outline`, gray border). Marker tap displays preview card with direct navigation to `ReportDetailsScreen`. Integrated "Locate Me" GPS action, location permission warning bottom sheet with manual map placement fallback, radius selector chips (`0.5`, `1.0`, `2.0`, `5.0 km`), and filter chips (`All`, `Missing`, `Found`).
    5. `CreateReportScreen` (`frontend/lib/ui/screens/create_report_screen.dart`): Replaced static Kyiv presets with "Use GPS" position button and interactive "Pick on Map" bottom sheet modal (`FlutterMap`) with draggable coordinate confirmation and manual latitude/longitude input validation (-90..90, -180..180).
    6. Platform Configurations: Added `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, and `INTERNET` permissions to `frontend/android/app/src/main/AndroidManifest.xml`.
  - Testing & Quality Verification:
    - Dedicated Phase 6.6 test suite (`frontend/test/phase_6_6_test.dart`): 17 unit and widget tests covering MapConfig specifications, LocationService GPS/permissions/timeouts/manual anchor, ReportRepository geo radius parameter formatting and clamping, MapScreen real map rendering/markers/radius chips/preview card navigation/GPS locate/permission notices, and CreateReportScreen GPS & map picker integration.
    - Full Flutter test suite (`flutter test`): 72 of 72 tests passed (including `phase_6_4_test.dart`, `phase_6_5_test.dart`, `phase_6_6_test.dart`, `live_backend_smoke_test.dart`, `stabilization_test.dart`, `widget_test.dart`).
    - Static analysis: `flutter analyze` passed with 0 issues found.
- 2026-10-14: Completed Phase 6.7 — End-to-End Testing & Hardening.
  - Scope: Hardened and end-to-end verified the complete Missing/Found reporting and recovery-request workflows across Flutter, FastAPI, PostgreSQL/PostGIS, and MinIO.
  - Verified & Hardened Workflows:
    1. Real Application Flow: Registration, login, profile retrieval (`/api/v1/users/me`), report creation (Missing/Found), report listing with filters, report details by UUID, image upload to MinIO/S3, refresh token rotation, and clean logout. Verified live against running FastAPI daemon (10/10 PASS).
    2. Map Discovery & Geolocation: Real coordinates, Missing vs Found filtering, radius searches (0.1–5.0 km, 1 decimal place), and marker tap navigation to `ReportDetailsScreen`.
    3. Location Service Hardening: Graceful permission handling (denied, permanently denied, disabled, timeouts), zero coordinate fabrication, manual map placement fallback, and coordinate range validation (-90..90, -180..180).
    4. Recovery Request Independence: Verified finder/owner independence—finders can initiate handover contact on Missing reports without creating a Found report first; owners can claim Found items without creating a Missing report. Documented backend gap (SQLAlchemy `RecoveryRequest` model in `app/db/models.py` lacks mounted FastAPI endpoints in `app/main.py`; simulated via UI).
    5. Error Handling & Edge Cases: Negative reward defense-in-depth guard (`ArgumentError`), pagination metadata parsing (`totalReports`, `currentPage`, `pageSize`, `totalPages`), transparent 401 retry, 403 Forbidden handling, 404 fallback, 422 validation, empty states, and `NetworkException` handling.
    6. Rewards Policy: Optional rewards strictly restricted to Missing reports; Found reports discard rewards; zero payment processing, KYC, or identity verification introduced.
    7. CORS & Base URLs: Web vs Android (`10.0.2.2:8000`) configurations and local development base URLs verified.
  - Confirmed Defects & Architectural Fixes:
    1. `frontend/lib/ui/screens/create_report_screen.dart`: Fixed missing `reportId: created.id` parameter in `ReportDetailsScreen` constructor for SnackBar VIEW action.
    2. `frontend/lib/ui/screens/recovery_requests_screen.dart`: Fixed horizontal `RenderFlex` overflow (262px on mobile viewports) by wrapping request title and sender details in `Expanded` with ellipsis text overflow.
    3. `frontend/lib/services/report_repository.dart`: Added negative reward defense-in-depth check and pagination metadata getters (`totalReports`, `currentPage`, `pageSize`, `totalPages`).
    4. `frontend/test/phase_6_7_test.dart`: Created comprehensive 19-test suite across 6 groups covering all hardening requirements.
  - Automated Quality & Testing Results:
    - Phase 6.7 test suite (`test/phase_6_7_test.dart`): 19 of 19 passed.
    - Full Flutter test suite (`flutter test`): 91 of 91 tests passed across all 7 test files.
    - Static analysis: `flutter analyze` 0 issues.
    - Code formatting: `dart format .` cleanly formatted.
    - Backend test suite: `pytest tests/` 23 of 23 passed.
    - Backend lint & format: `ruff check` and `ruff format --check` 0 issues.
    - Backend typing: `mypy app tests` 0 issues in 23 files.
    - Live smoke test: 10 of 10 checks passed against local FastAPI daemon.
  - Guardrails & Repository Safety:
    - Zero Git write operations performed (manual git ownership retained by developer).
    - Preserved monochromatic Swiss-modernist design tokens (`#080808`, `#151515`, `#303030`).
- 2026-10-14: Completed Phase 6.8 — Release Preparation.
  - Scope: Resolved recovery-request persistence across the stack, hardened platform token storage, audited release readiness configurations, and performed comprehensive end-to-end regression and live smoke testing.
  - Recovery-Request Persistence & API Implementation:
    1. Reused existing `RecoveryRequest` SQLAlchemy model and migration `b3feb293d5d0_phase_2_domain_model.py` without duplicating models or creating unnecessary migrations.
    2. Implemented `app/schemas/recovery.py` with strict Pydantic v2 schemas: `CreateRecoveryRequest`, `UpdateRecoveryRequestStatus`, `RecoveryRequestResponse`, `RecoveryRequestListResponse`, and nested report/user response models.
    3. Implemented `app/services/recovery.py` with strict authorization logic:
       - Self-recovery prevention: returns 400 Bad Request if report owner initiates request on their own report.
       - Duplicate prevention: returns 409 Conflict if an active (`PENDING` or `ACCEPTED`) request already exists for that user and report.
       - Participant access: returns 403 Forbidden for third-party access to request details or status updates.
       - State machine enforcement: returns 422 Unprocessable Entity for invalid transitions (e.g. `PENDING` -> `COMPLETED`, transitions from terminal statuses `REJECTED`, `CANCELLED`, `COMPLETED`).
       - Recipient allowed transitions: `ACCEPTED`, `REJECTED`. Requester allowed transitions: `CANCELLED`.
       - Automatic resolution: transitioning a request to `COMPLETED` automatically marks the associated `Report.status` as `RESOLVED` in PostgreSQL.
    4. Implemented `app/api/recovery.py` mounting `POST /api/v1/recovery-requests`, `GET /api/v1/recovery-requests`, `GET /api/v1/recovery-requests/{id}`, and `PATCH /api/v1/recovery-requests/{id}` on FastAPI application in `app/main.py`.
    5. Added 6 comprehensive backend regression tests in `tests/test_recovery.py` covering Missing/Found report requests, self-report rejection, duplicate rejection, unauthorized access, and complete transition lifecycles.
  - Frontend Recovery Persistence & UI Integration:
    1. Created `frontend/lib/models/recovery_request_model.dart` for parsing and serializing recovery request DTOs.
    2. Created singleton `frontend/lib/services/recovery_repository.dart` managing live API calls (`createRecoveryRequest`, `loadRequests`, `updateRequestStatus`), local observable state, and fallback mock mode for unit tests.
    3. Connected `frontend/lib/ui/screens/report_details_screen.dart` to dispatch real requests via `RecoveryRepository.instance.createRecoveryRequest()`.
    4. Connected `frontend/lib/ui/screens/recovery_requests_screen.dart` to display real received and sent requests, dynamically count items per tab, and execute real status updates on Accept and Decline actions.
    5. Added 10 Flutter unit, widget, and integration tests in `frontend/test/phase_6_8_test.dart` covering model serialization, live API error handling, token storage fallback, and UI workflow integration.
  - Release Readiness & Security Hardening:
    1. Platform Token Storage: Replaced volatile in-memory storage default in `AuthService` with `SecurePlatformTokenStorage` utilizing `flutter_secure_storage` (Android Keystore, iOS Keychain, Windows DPAPI, Web IndexedDB/localStorage fallback). Documented web storage limitations explicitly.
    2. API & Environment Audits: Verified dynamic API base URL handling with mobile/emulator overrides (`10.0.2.2:8000` on Android, `localhost:8000` on Desktop/Web), CORS origin whitelisting in `app/core/config.py`, MinIO S3 credentials, database connection strings, and production structured error handling.
    3. Map Attribution: Verified `CartoDB Dark Matter / OpenStreetMap / CARTO` tile attribution in map widgets without claiming offline maps are supported.
    4. Scope Boundaries: Verified rewards apply strictly to Missing reports; zero payment processing, escrow, KYC, or identity verification introduced.
  - Automated Quality & Testing Results:
    - Backend test suite (`pytest tests/`): 29 of 29 passed.
    - Backend linter & formatter (`ruff check`, `ruff format --check`): 0 issues across all 27 files.
    - Backend type checker (`mypy .`): 0 issues across all 31 source files.
    - Frontend analysis (`flutter analyze`): 0 issues found.
    - Frontend formatting (`dart format .`): Clean (36 files, 0 changed).
    - Frontend test suite (`flutter test`): 101 of 101 passed across 8 test suites.
    - Live End-to-End Smoke Test (`scratch/live_recovery_smoke_test.py`): 16 of 16 assertions passed against live running PostgreSQL and FastAPI daemon.
  - Guardrails & Repository Safety:
    - Zero Git write operations performed (manual git ownership retained by developer).
    - Preserved monochromatic Swiss-modernist design tokens (`#080808`, `#151515`, `#303030`).
- 2026-10-15: Completed Manual Testing Remediation (Steps 1 to 5).
  - Step 1 — Unexpected data & identity:
    - Fixed desktop sidebar user identity unit in `main_nav_screen.dart` to dynamically bind to `AuthService.instance.currentUser` (name and email), removing hardcoded "Alex Morgan" and "Verified Member".
    - Fixed `ProfileScreen` in `profile_screen.dart` to dynamically calculate operational summary counts for active missing reports, resolved reports, and received/sent recovery requests from live repositories (`ReportRepository.instance.userReports`, `RecoveryRepository.instance.receivedRequests`, `RecoveryRepository.instance.sentRequests`), eliminating hardcoded "3 reports: 2 active missing, 1 resolved" and "2 received, 1 sent".
    - Removed mock report fallbacks from live authenticated mode in `ReportRepository.userReports` and `RecoveryRepository`, ensuring clean empty states for new accounts while isolating mock mode strictly to unit tests.
    - Updated backend `app/api/reports.py` and `app/api/deps.py` with `get_optional_current_user` to allow unauthenticated public discovery while enforcing authorization.
  - Step 2 — Map tile rendering:
    - Replaced CARTO dark tile endpoint in `MapConfig.tileUrl` with OpenStreetMap public raster tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`), eliminating "API KEY REQUIRED" watermarks without paid dependencies or embedded secrets.
    - Added `MapConfig.darkTileBuilder` applying an inverted luminance color filter matrix to render standard OSM tiles in sleek monochromatic dark mode.
    - Updated tile layer attribution to `© OpenStreetMap contributors`.
  - Step 3 — Coherent location-selection flow:
    - Removed hardcoded "Downtown Kyiv" selector across `HomeScreen` and `MapScreen`.
    - Created `GeocodingService` utilizing OpenStreetMap Nominatim search API with custom user agent and rate limiting.
    - Created `LocationSelectionSheet` modal allowing users to search places with autocomplete results, detect GPS position via `LocationService` (with explicit permission-denied / service-disabled messages), tap map to anchor coordinates, view active anchor label, and clear selection.
    - Synchronized active location state via observable `LocationService.instance` shared between `HomeScreen` and `MapScreen`.
  - Step 4 — Enforce 5 km nearby filtering:
    - Enforced default 5.0 km search radius across `HomeScreen` and `MapScreen` (`radius_km=5.0`, `sort=distance`).
    - Handled unanchored state on `HomeScreen` with a prompt card to select location rather than executing unbounded or arbitrary queries.
    - Handled empty nearby results with clear empty state indicators.
  - Step 5 — Verification & Regression Protection:
    - Added comprehensive regression test suite in `frontend/test/remediation_test.dart` (11 passing tests) covering sidebar identity, profile summary counts, empty states, live repository mock isolation, Nominatim place search, manual anchor synchronization, 5 km API query parameters, and OSM map tile configuration.
    - Updated legacy test expectations in `phase_6_6_test.dart`, `phase_6_7_test.dart`, `stabilization_test.dart`, and `widget_test.dart` to align with the remediation.
    - Verified: `flutter test` passed 104 out of 104 tests with 0 failures across all 8 suites.
    - Verified: `flutter analyze` reported 0 issues.
    - Verified: `dart format .` cleanly formatted.
    - Verified backend: `ruff check app tests` (0 errors), `ruff format --check app tests` (clean), `mypy app tests` (0 issues across 27 files).
    - Preserved repository safety: 0 Git write operations executed.
- 2026-10-15: Completed Backend Integration Test Verification.
  - Environment Diagnostics & Recovery:
    - Successfully verified Docker engine and Docker Compose stack: `tracker_db` (PostGIS 16-3.4 on port 5432) and `tracker_minio` (MinIO S3 on port 9000-9001) up and healthy.
    - Verified database migrations at head via `alembic upgrade head` with transactional DDL.
  - Full Backend Test Suite Execution:
    - Executed `pytest tests/ -v`: 29 passed out of 29 in 24.25s (0 failures, 0 errors, 0 skipped).
    - Tests verified: `test_auth.py` (5 tests), `test_geo.py` (5 tests), `test_main.py` (1 test), `test_models.py` (3 tests), `test_recovery.py` (6 tests), `test_reports.py` (9 tests).
  - Code Quality Verification:
    - `ruff check app tests`: All checks passed!
    - `ruff format --check app tests`: 27 files already formatted.
    - `mypy app tests`: Success: no issues found in 27 source files.
  - Live API End-to-End Verification:
    - Started live backend daemon on `http://127.0.0.1:8000`.
    - Executed `flutter test test/live_backend_smoke_test.dart`: 8 of 8 passed.
    - Executed automated live smoke verification covering `GET /health`, registration/login/me, Missing report creation, unauthenticated public discovery, 5 km geospatial radius filtering (positive nearby detection at 0.73 km vs negative out-of-range exclusion), duplicate/self-recovery rejection, received/sent listings, acceptance with contact info, and status completion automatically setting report to `RESOLVED`.
    - Cleanly terminated live test daemon.
  - Repository Safety:
    - Zero Git write operations performed. Existing uncommitted changes preserved.
- 2026-10-17: Completed Consolidated UI Remediation and Full Regression Verification.
  - Global Notification System (`AppToast`):
    - Created unified monochromatic toast notification widget `AppToast` in `frontend/lib/ui/widgets/app_toast.dart` replacing raw, inconsistent white banner SnackBars.
    - Designed with charcoal `#151515` background, subtle `#303030` border, readable `#F5F5F5` text, neutral monochrome icons, smooth slide/fade animations, horizontal swipe dismiss, close button, and non-blocking action callback.
    - Updated `AppTheme.darkTheme` with matching `SnackBarThemeData` and replaced all raw `ScaffoldMessenger.of(context).showSnackBar` calls across all 10 application screens and sheets.
  - Map Page Immediate Recentering & Location Sync:
    - Updated `MapScreen._onLocationChanged()` to immediately invoke `_mapController.move(anchor, targetZoom)` and reload nearby reports without requiring page refresh or tab re-navigation.
    - Preserved active map anchor across Home and Map tabs via `LocationService.instance`.
  - Dynamic Identity & Session Isolation:
    - Removed hardcoded "Alex Morgan", fake member badges, and placeholder IDs from live paths.
    - Bound `MainNavScreen` sidebar, avatar initials, `ProfileScreen` heading, and counts strictly to `AuthService.instance.currentUser` (with accurate 0 counts for fresh accounts).
    - Added `clearUserData()` to `ReportRepository` and `RecoveryRepository` invoked on `AuthService.logout()` to ensure complete state isolation between sessions.
  - Startup Auth Gate (`AppRoot`):
    - Implemented reactive `AppRoot` in `frontend/lib/main.dart` listening to `AuthService.instance`.
    - Fresh launch with no tokens boots to `LoginScreen()`; valid stored tokens restore authenticated session directly into `MainNavScreen()`; logout or expired sessions redirect immediately to `LoginScreen()`.
  - Verification & Quality:
    - Full Flutter test suite: 121 of 121 tests passed (100% pass rate across all suites including `phase_6_5_test.dart`, `remediation_test.dart`, `stabilization_test.dart`, `widget_test.dart`, and `live_backend_smoke_test.dart`).
    - Static analysis: `flutter analyze` reported 0 issues.
    - Code formatting: `dart format .` completed with 0 differences.
    - Full backend test suite: `pytest` passed 29 of 29 tests in 23.62s.
    - Backend linting, format check, and strict typing: `ruff check` (0 errors), `ruff format --check` (clean), `mypy` (0 errors across 27 files).
    - Live infrastructure: `tracker_db` (PostGIS 16-3.4) and `tracker_minio` Docker containers healthy; backend health check endpoint returning `{"status": "ok", "database": "ok"}`.
    - Repository safety: Complied with manual Git ownership rule; zero git write commands executed.
- 2026-10-17: Fixed Nearby Reports Location Anchor & Strict 5 km Radius Enforcement.
  - Root Cause Analysis:
    1. Unanchored Query Trigger: `HomeScreen.initState` unconditionally called `ReportRepository.instance.loadReports(latitude: null, longitude: null, radiusKm: null)` when `LocationService.instance.currentLocation` was null, querying the backend without geographic bounds and populating Home with 50 globally unfiltered reports.
    2. Unconditional Insertion on Report Creation: `ReportRepository.createReport` prepended newly created reports via `_reports.insert(0, finalReport); notifyListeners();` regardless of the active anchor or whether the report was within 5 km.
    3. UI Cache Leak: `HomeScreen._allReports` and `MapScreen._filteredReports` exposed `_reports` without asserting that a valid anchor was active.
  - Architecture & Data Flow Fixes:
    - Dedicated Repositories & State Separation:
      - `_reports` in `ReportRepository` now strictly contains nearby reports filtered for the active anchor.
      - User's created reports are preserved in `_userCreatedReports` and `_cachedReportsById`, ensuring they remain fully accessible in `MyReportsScreen` and `ReportDetailsScreen` without polluting the nearby feed.
      - `createReport`: In live mode, saves to `_cachedReportsById` and `_userCreatedReports`. Does not unconditionally insert into `_reports`. If an anchor is active, re-queries nearby reports with `radius_km=5.0`; if unanchored, calls `clearGeoSearch()`.
    - Unanchored Empty State Enforcement:
      - `HomeScreen` and `MapScreen` enforce that if `!LocationService.instance.hasLocation && !isMockMode`, zero nearby cards are rendered and the count displays `0 items`.
      - Displays monochrome empty state: "Select a location to see reports within 5 km." (Home) and "Select a location to see reports within 5.0 km." (Map collapsible panel).
    - Race Condition & Stale Response Protection:
      - Implemented `_requestSequence` counter in `ReportRepository`. Any slow in-flight response for an older anchor or query is discarded if `_requestSequence` has advanced.
      - In live mode, network failures clear stale reports and transition the UI to an explicit error/retry card instead of mock data.
    - PostGIS Spatial Filtering Before Pagination (Case 13):
      - Backend spatial queries (`ST_DWithin` on geography with 5.0 km radius) apply in SQL before `COUNT(*)` and before pagination (`OFFSET` / `LIMIT`), ensuring total matches reflect only geographically valid records.
  - Verification & Quality:
    - Full Flutter test suite: 132 of 132 tests passed (including 11 comprehensive regression tests in `test/nearby_location_anchor_test.dart`).
    - Flutter static analysis: `flutter analyze` reported 0 issues.
    - Dart formatting: `dart format --output=none --set-exit-if-changed .` clean (0 differences across 41 files).
    - Backend test suite: `pytest` passed 30 of 30 tests in 29.10s (including new spatial filtering before pagination & radius boundaries test in `tests/test_geo.py`).
    - Backend linting & typing: `ruff check` (0 errors), `ruff format --check` (27 files formatted), `mypy app tests` (0 errors across 27 files).
    - Repository safety: Complied with manual Git ownership rule; zero git write commands executed.
- 2026-10-18: Completed Phase 6 — Complete Location Selection and Map Discovery Upgrade.
  - Priority 1: Report Creation Location Selection (Missing & Found)
    - Created `ReportLocationPickerSheet` (`frontend/lib/ui/widgets/report_location_picker_sheet.dart`) providing 3 intuitive methods:
      - Method A (Search): Prominent search bar with debounced place autocomplete suggestions (querying OpenStreetMap Nominatim with local caching). Selecting a suggestion centers the map camera.
      - Method B (GPS): Explicit "Use My Current Location" button obtaining device position, moving the map camera, reverse-geocoding the address, and allowing pin refinement. Graceful error handling for denied/disabled GPS.
      - Method C (Manual Map Pinpointing): Interactive `FlutterMap` under a fixed center pin indicator. Panning moves the map beneath the pin; debounced reverse geocoding on movement stop resolves human-readable addresses while preserving exact coordinates on geocoding network failures.
    - Explicit Confirmation & Form State:
      - Returns `LocationSelectionResult(latitude, longitude, address)` on explicit "Confirm Location" tap.
      - `CreateReportScreen` displays confirmed coordinates badge with "Change" (reopens picker preserving previous coordinates) and "Clear" actions.
      - Form validation strictly requires explicit coordinates in live mode (`isMockMode == false`), preventing silent fallbacks to Kyiv or discovery anchors.
      - Reusable across both Missing and Found reports without duplicating logic.
  - Priority 2: Map Section Discovery Search & "Search this area"
    - Integrated place search into `MapScreen`: debounced place autocomplete suggestions list, selecting suggestion updates discovery anchor and queries reports.
    - GPS recentering: "Locate Me" button triggers GPS fix and centers map on device position.
    - Explicit "Search this area": Panning > 300m away displays floating "Search this area" button. Activating it sets the settled map center as the new discovery anchor, queries nearby reports, and synchronizes with Home without spamming backend queries on camera movement.
    - Strict Geographic Filtering: Preserves 5.0 km default radius and PostGIS boundary enforcement. Unanchored state displays 0 nearby reports.
    - Concept Separation: Incident location (stored on report) and discovery location (`LocationService.instance.currentLocation` shared between Home & Map) remain strictly decoupled. Picking report locations never alters the discovery anchor.
  - Verification & Quality:
    - Dedicated regression test suite created: `frontend/test/phase_6_location_test.dart` (15/15 tests passed).
    - Full Flutter test suites run: 138 of 138 tests passed (`phase_6_location_test.dart`, `phase_6_6_test.dart`, `nearby_location_anchor_test.dart`, `phase_6_7_test.dart`, `phase_6_8_test.dart`, `phase_6_4_test.dart`, `phase_6_5_test.dart`, `remediation_test.dart`, `stabilization_test.dart`).
    - Static analysis: `flutter analyze` reported 0 issues.
    - Formatting check: `dart format --output=none --set-exit-if-changed .` passed cleanly (43 files checked).
    - Backend test suite: `pytest` passed 30 of 30 tests in 19.89s.
    - Backend linting, format check & typing: `ruff check` (0 errors), `ruff format --check` (27 files formatted), `mypy app tests` (0 errors across 27 files).
    - Repository safety: Complied with manual Git ownership rule; zero git write commands executed.
- 2026-10-18: Bug Fix — Newly Created Reports Missing From My Account (End-to-End Investigation & Resolution).
  - Lifecycle Trace & Confirmed Root Cause:
    1. Database Persistence Verified: The user's two reports (`2425ba1b-1844-4788-ad5c-9e9167cfca74` 'qwertyuioploi' MISSING and `92a8f293-d49f-4f65-a903-05f327e776c4` 'asdfghjkl' FOUND) WERE successfully persisted in PostgreSQL with correct `created_by_user_id = 7e3a5868-4d1e-4077-8bb4-a1ddc66b9341` (`sai@gmail.com`) at Kyiv coordinates (30.52, 50.44).
    2. Backend Missing Endpoint: The FastAPI backend had no dedicated `/api/v1/reports/me` route or `mine=True`/`user_id` query parameter on `GET /api/v1/reports` allowing users to fetch their own reports globally regardless of location.
    3. Frontend In-Memory Leak & Radius Filter Misalignment: `ReportRepository.userReports` only read from `_userCreatedReports` (an ephemeral in-memory list lost on restart/refresh) and `_reports` (public nearby discovery feed clamped to 5.0 km from active GPS/anchor). Since the user's active anchor was in Chennai (~13.0, 80.1), PostGIS radius filtering properly excluded the Kyiv reports from the discovery feed, causing `userReports` to return empty.
    4. Screen Fetching & Resilience Gap: `MyReportsScreen` had no network load trigger in `initState`, no pull-to-refresh (`RefreshIndicator`), and silently displayed an empty list on failure rather than showing an actionable error/retry card.
  - Architecture & Data Flow Fixes:
    - Backend (`app/services/report.py` & `app/api/reports.py`):
      - Added `user_id: uuid.UUID | None = None` parameter to `list_reports` filtering by `Report.created_by_user_id == user_id` without requiring geospatial coordinates.
      - Added `GET /api/v1/reports/me` endpoint protected by `current_user: User = Depends(get_current_user)`, returning all reports owned by the authenticated caller across all locations, statuses, and types.
      - Added `mine: bool = Query(False)` on `GET /api/v1/reports` enforcing caller ownership via `current_user` and bypassing geo-filtering when coordinates are omitted.
    - Frontend Repository (`frontend/lib/services/report_repository.dart`):
      - Added dedicated `_userReports` state, `_isLoadingUserReports`, `_userReportsError`, and `_hasLoadedUserReports`.
      - Implemented `loadUserReports({bool forceRefresh = false})` targeting `/api/v1/reports/me` with Bearer auth token attachment and structured error handling.
      - Updated `userReports` getter to prioritize server-fetched `_userReports` alongside session reports.
      - Updated `createReport` to automatically prepend newly created reports to `_userReports` and cached reports, and `clearUserData` on logout.
    - UI Integration (`frontend/lib/ui/screens/my_reports_screen.dart`):
      - Wired `initState` and `_onAuthChanged` to automatically invoke `loadUserReports()`.
      - Added `RefreshIndicator` for smooth pull-to-refresh.
      - Added loading spinner and prominent error card with "Retry" action on network failure, preventing silent blank states.
      - Decoupled `_onAuthChanged` from `_onReportsChanged` to prevent infinite re-render loops on errors.
  - Regression Testing & Quality Verification:
    - Backend tests (`tests/test_reports.py`): Added `test_my_reports_unauthenticated` (verifying 401 Unauthorized) and `test_my_reports_lifecycle_and_isolation` (verifying Missing/Found reports returned, geo-radius independence, and user isolation).
    - Flutter regression suite (`frontend/test/my_reports_regression_test.dart`): Added 5 comprehensive test groups covering:
      1. Missing & Found creation and loading via `loadUserReports`.
      2. Reports remaining visible in My Reports when incident location is outside discovery radius while nearby discovery excludes them.
      3. Strict user-to-user isolation (User A cannot see User B's reports in My Reports).
      4. Navigation away and back with fresh authenticated fetch.
      5. Visible error card and retry recovery on network failures.
    - Full Flutter test suite: 143+ tests passing with 0 failures across all 10 suites (`--concurrency=1`).
    - Backend suite: 32 of 32 tests passed in `pytest`.
    - Typecheck & Linting: `mypy app tests` (0 errors), `ruff check` (0 errors), `ruff format --check` (clean), `flutter analyze` (0 issues), `dart format` (clean).
    - Repository safety: Complied with manual Git ownership rule; zero git write commands executed.
- 2026-10-18: Completed Phase 7.1 — Event Contracts and Schema Design.
  - Scope & Architecture:
    - Standardized Generic Envelope (`EventEnvelope[PayloadT]` in `app/schemas/events/envelope.py`):
      - Common fields: `event_id` (UUIDv4), `event_type` (`EventType`), `event_version` (positive int, default 1), `occurred_at` (`UtcDatetime`), `producer` (non-empty string), `aggregate_id` (UUID), `aggregate_type` (`AggregateType`), `correlation_id` (optional UUID), `payload` (strongly typed Pydantic v2 model).
      - Strict immutability and schema protection: `extra="forbid"`, `frozen=True`.
      - Cross-field validation: verifies `event_type` namespace aligns with `aggregate_type`, and `aggregate_id` matches the entity identifier in the payload.
    - Initial Event Contracts (v1):
      - `report.created` (`ReportCreatedPayload` in `app/schemas/events/report.py`): includes `report_id`, `created_by_user_id`, `type` (MISSING/FOUND), `category`, `title`, `description`, `latitude`, `longitude`, `event_time`, `reward_amount` (optional, forbidden on FOUND), `status` (ACTIVE), `created_at`. Coordinates justified for spatial matching engine.
      - `report.updated` (`ReportUpdatedPayload` in `app/schemas/events/report.py`): includes `report_id`, explicit `updated_fields` list, optional mutable fields, and `updated_at`. Enforces paired latitude/longitude updates and restricts updated field names to allowed domain set.
      - `report.resolved` (`ReportResolvedPayload` in `app/schemas/events/report.py`): includes `report_id`, `status` (RESOLVED), `resolved_at`, optional `resolution_reason`, and optional `associated_recovery_request_id`. Omits coordinates to protect user privacy.
      - `recovery_request.created` (`RecoveryRequestCreatedPayload` in `app/schemas/events/recovery.py`): includes `recovery_request_id`, `report_id`, `requester_id`, `recipient_id`, `status` (PENDING), optional `message`, and `created_at`. Excludes sensitive verification response and user personal credentials.
      - `recovery_request.updated` (`RecoveryRequestUpdatedPayload` in `app/schemas/events/recovery.py`): includes `recovery_request_id`, `report_id`, `requester_id`, `recipient_id`, `previous_status`, `new_status`, and `updated_at`. Validates state machine transitions against domain rules. Strictly excludes `verification_response`.
    - Event Parsing & Deserialization (`app/schemas/events/parser.py`):
      - Implemented `parse_event(raw)` with typed pattern-matching dispatch.
      - Explicit exception hierarchy: `EventError`, `UnsupportedEventVersionError` (rejects versions other than 1), `UnsupportedEventTypeError`, `EventParseError`.
    - Specification & Guidelines (`docs/event_contracts.md`):
      - Documented domain event definition, envelope schema, each event type and payload, field justifications, versioning rules, production immutability rationale, consumer DLQ strategies, and privacy safeguards.
      - Explicitly documented that event contracts are not yet connected to Kafka or transactional outbox.
  - Quality & Verification Results:
    - Dedicated event test suite created: `tests/test_events.py` (42 tests covering envelope invariants, malformed UUID/version/timestamp rejection, payload validation, status transitions, coordinate pairs, sensitive field rejection via `extra="forbid"`, timezone conversion to UTC, JSON serialization/deserialization, and parse_event error handling).
    - Full backend test suite (`pytest`): 74 of 74 tests passed in 20.76s (0 failures, 0 errors).
    - Backend typing (`mypy app tests`): 0 errors across 34 source files (`mypy --strict`).
    - Backend linting & formatting (`ruff check app tests`, `ruff format --check app tests`): 0 errors, 34 files formatted.
    - Preserved repository safety: 0 Git write operations executed.
- 2026-10-18: Completed Phase 7.2 — Local Kafka Infrastructure.
  - Architecture & Infrastructure:
    - Docker Compose Kafka Deployment (`docker-compose.yml`):
      - Configured Apache Kafka 3.8.0 in single-node KRaft mode (no ZooKeeper required) under container name `tracker_kafka`.
      - Configured dual advertised listeners: `PLAINTEXT://kafka:29092` for internal inter-container communication and `PLAINTEXT_HOST://localhost:9092` for local host development.
      - Controller listener bound to port 9093 (`CONTROLLER://0.0.0.0:9093`) with KRaft quorum voter `1@kafka:9093`.
      - Persistent data storage configured via Docker named volume `kafka_data` mounted at `/var/lib/kafka/data`.
      - Health check configured using `/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092` (10s interval, 5s timeout, 5 retries, 15s start period).
    - Automated Topic Provisioning (`kafka-init` in `docker-compose.yml`):
      - Container `tracker_kafka_init` depends on `kafka: service_healthy`.
      - Runs `/opt/kafka/bin/kafka-topics.sh` to idempotently create `boomerang.domain.events` with 3 partitions and replication factor 1.
  - Application Settings & Environment:
    - Added `KAFKA_BOOTSTRAP_SERVERS` and `KAFKA_DOMAIN_EVENTS_TOPIC` to `app/core/config.py` with defaults (`localhost:9092`, `boomerang.domain.events`).
    - Updated `.env.example` and local `.env` with Kafka development variables and documentation.
  - Development Smoke Testing:
    - Created `scripts/kafka_smoke_test.py`: Standalone CLI tool that publishes a synthetic probe message (`INFRASTRUCTURE_SMOKE_TEST`, no real report data) to `boomerang.domain.events`, verifies consumer retrieval in a dedicated group, reports roundtrip latency and partition/offset details, and handles Windows console encodings cleanly.
    - Created `tests/test_kafka_smoke.py`: Automated pytest test asserting message roundtrip, partition routing, and payload fidelity, gracefully skipping if broker is offline.
    - Configured mypy override for `aiokafka.*` in `pyproject.toml` maintaining strict type check pass across all 41 source files.
  - Operations & Documentation:
    - Created `docs/kafka_setup.md`: Complete guide covering startup (`docker compose up -d`), topic inspection, partition details, container health verification, log tailing, graceful stopping, data resets, and troubleshooting.
    - Cross-referenced Kafka guide in `docs/event_contracts.md`.
  - Quality & Verification:
    - Docker Compose validated via `docker compose config` and container health verified via `docker compose ps` (`tracker_kafka` healthy, `tracker_kafka_init` completed with code 0).
    - Verified topic creation using `kafka-topics.sh --describe` (3 partitions, leader 1).
    - CLI smoke test executed successfully: partition 0, offset 1, roundtrip latency 2.0 ms.
    - Full pytest suite: 75 of 75 tests passed in 21.48s (0 failures, 0 errors).
    - Code quality: `ruff check .` (0 errors), `ruff format --check .` (0 errors, 43 files formatted), `mypy .` (strict passed, 0 errors across 41 source files).
    - Git safety: Strict compliance with manual Git ownership rule; zero git write commands executed.
- 2026-10-18: Completed Phase 7.3 — Transactional Outbox & Reliable Event Publishing.
  - Architecture & Persistence:
    - Implemented `OutboxEvent` model in `app/db/models.py` with `OutboxStatus` enum (`PENDING`, `PROCESSING`, `PUBLISHED`, `FAILED`, `DEAD_LETTER`).
    - Stored unique `event_id`, `event_type`, `event_version`, `aggregate_type`, `aggregate_id`, `topic`, serialized JSONB `payload` (`EventEnvelope`), occurrence/creation timestamps, `retry_count`, `max_retries`, `next_retry_at`, `published_at`, and bounded `last_error`.
    - Added database indexes: `ix_outbox_events_status_next_retry` on `(status, next_retry_at, created_at)` and `ix_outbox_events_aggregate` on `(aggregate_type, aggregate_id)`.
    - Created clean Alembic migration `alembic/versions/a4d442db2420_phase_7_3_outbox.py` and validated upgrade/downgrade cycles.
  - Domain Mutation Integration:
    - Implemented `app/services/outbox.py` with typed builders (`build_report_created_event`, `build_report_updated_event`, `build_report_resolved_event`, `build_recovery_request_created_event`, `build_recovery_request_updated_event`) and `create_outbox_event`.
    - Integrated outbox event persistence atomically within active database transactions:
      - `create_report`: emits `report.created` (coordinates included for matching engine).
      - `update_report`: emits `report.updated` with explicit `updated_fields` list (only on actual changes, suppresses no-op events) and `report.resolved` on status change to `RESOLVED`.
      - `create_recovery_request`: emits `recovery_request.created` (excludes sensitive personal info and verification responses).
      - `update_recovery_request_status`: emits `recovery_request.updated` on status transitions; if completed and active report is resolved, emits `report.resolved` in the same transaction.
  - Dispatcher & Kafka Delivery:
    - Implemented `OutboxDispatcher` in `app/services/outbox_dispatcher.py` and CLI runner `scripts/run_outbox_dispatcher.py`.
    - Safe concurrency: claims eligible rows using PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` and immediately commits `PROCESSING` status to release DB locks before Kafka network I/O.
    - Publishes to `boomerang.domain.events` keyed by `aggregate_id` to guarantee partition-level ordering.
    - Records success (`PUBLISHED`) or schedules retries (`FAILED`) using bounded exponential backoff with full jitter.
    - Retains poison events exceeding `max_retries` as `DEAD_LETTER` with bounded error details, and provides `replay_dead_letter_events` for operational remediation.
    - Reclaims stale `PROCESSING` rows if a worker process crashes mid-batch.
  - Operations & Documentation:
    - Authored `docs/outbox_pattern.md` specifying architecture, state transitions, at-least-once delivery semantics, consumer deduplication requirements, CLI commands, and failure recovery.
    - Configured outbox settings in `app/core/config.py`, `.env.example`, and `.env`.
  - Quality & Verification:
    - Created `tests/test_outbox.py` with 12 comprehensive tests covering all 11 prompt requirements and live end-to-end Kafka roundtrip dispatch.
    - Full pytest suite: 87 of 87 tests passed (0 failures, 0 errors).
    - Code quality: `ruff check .` (0 errors), `ruff format --check .` (clean, 50 files formatted), `mypy .` (strict passed, 0 errors across 46 source files).
    - Preserved repository safety: 0 Git write operations executed.
- 2026-10-18: Completed Phase 7.3 Transactional Outbox Audit.
  - Forensic Code Audit & Confirmed Defects Fixed:
    1. Stale Worker Crash Loop & Poison Event Trapping: In `app/services/outbox_dispatcher.py`, fixed `claim_batch` to increment `retry_count` and record `last_error` when reclaiming stale rows from `PROCESSING` state. Exceeding `max_retries` due to worker crashes safely transitions poison events to `DEAD_LETTER` rather than infinitely crash-looping workers every 300s.
    2. Setting Constraints & Validation: In `app/core/config.py`, added Pydantic v2 `Field(default=..., gt=0/ge=1)` validation to prevent negative/zero batch sizes or retry delays from environment misconfiguration.
    3. Parameter Clarification: In `app/services/outbox_dispatcher.py`, renamed parameter `event_id` to `outbox_id` in `record_success` and `record_failure` to prevent ambiguity with the business `event_id`.
    4. Worker Interruption Responsiveness: Updated `run_loop` to make sleep interrupts responsive to `stop_event` rather than blocking on the full interval.
  - Test Suite & Regression Coverage:
    - Added 4 targeted regression tests in `tests/test_outbox.py`:
      - `test_atomic_rollback_when_outbox_insertion_fails`: asserts failure during outbox persistence rolls back report creation.
      - `test_at_least_once_duplicate_delivery_on_db_ack_failure`: verifies Kafka ACK success followed by DB failure triggers at-least-once retry with identical `event_id` for consumer deduplication.
      - `test_stale_worker_recovery_and_dead_letter_on_repeated_crashes`: asserts stale rows are reclaimed without stealing healthy worker tasks, and repeated crash loops land in `DEAD_LETTER`.
      - `test_recovery_completion_on_already_resolved_report_no_duplicate_event`: asserts completing a recovery request on an already resolved report emits exactly one `report.resolved` event.
    - Test Results: `tests/test_outbox.py` 16 of 16 tests passed. Full backend test suite 91 of 91 tests passed in 75.62s.
    - Code Quality: `ruff check .` (0 errors), `ruff format --check .` (clean across 50 files), `mypy .` (strict passed, 0 errors across 46 source files).
    - Infrastructure & Operations: Verified Alembic migration `a4d442db2420` current, Docker Compose configuration valid, and standalone CLI runner commands (`--status`, `--once`, `--replay-dead-letters`, `scripts/kafka_smoke_test.py`) functional.
    - Repository safety: Zero Git write operations executed. Developer retains manual git ownership.
- 2026-10-18: Completed Phase 7.4 (Reliable Event Consumer Foundation).
  - Consumer Architecture & Infrastructure:
    - Designed and implemented reusable consumer framework under `app/services/event_consumer/`:
      - `handler.py`: Typed `EventHandler` protocol, `FunctionalEventHandler`, and `HandlerRegistry` supporting typed or wildcard event routing.
      - `consumer.py`: `EventConsumer` coordinating message ingestion, validation against Phase 7.1 event contracts, PostgreSQL idempotency tracking, bounded retries with jitter, safe quarantine, and manual Kafka offset commits (`offset + 1`).
      - Operational classifications: `ErrorCategory` (`UNSUPPORTED_VERSION`, `PARSE_ERROR`, `SCHEMA_VALIDATION_ERROR`, `HANDLER_ERROR`, `INTEGRITY_ERROR`), `ConsumerProcessingResult` (`SUCCESS`, `DUPLICATE_SKIPPED`, `IGNORED`, `QUARANTINED`).
    - Settings & Environment:
      - Added validated consumer configuration in `app/core/config.py` using Pydantic v2 `Field` constraints (`CONSUMER_DEFAULT_GROUP_ID`, `CONSUMER_POLL_TIMEOUT_SECONDS`, `CONSUMER_MAX_POLL_RECORDS`, `CONSUMER_MAX_RETRIES`, `CONSUMER_INITIAL_RETRY_DELAY_SECONDS`, `CONSUMER_MAX_RETRY_DELAY_SECONDS`, `CONSUMER_BACKOFF_MULTIPLIER`).
      - Documented settings in `.env.example`.
  - Durable Idempotency & Database Schema:
    - Added `ConsumerEventStatus` enum (`PROCESSING`, `COMPLETED`, `FAILED`, `QUARANTINED`) and `ConsumerEvent` model in `app/db/models.py`.
    - Enforced atomic concurrency with `UniqueConstraint("consumer_name", "event_id")` and indexed lookups on `(consumer_name, status)` and `(topic, partition, offset)`.
    - Handlers and idempotency records commit atomically within the same PostgreSQL transaction.
    - Created clean, reversible Alembic migration `alembic/versions/f99144acbb2a_phase_7_4_consumer_events.py` and filtered reflected PostGIS tables in `alembic/env.py`. Verified `alembic check` clean (no unmanaged drift).
  - Poison-Message & Offset Safety:
    - Malformed JSON, unparseable payloads, unknown event types, and unsupported versions are durably quarantined with bounded, privacy-scrubbed diagnostic errors and their partition offsets are immediately acknowledged to prevent head-of-line blocking.
    - Manual Kafka offset commits (`commit_offset({tp: OffsetAndMetadata(offset + 1, "")})`) execute strictly after database transactions commit.
    - Added explicit operator replay mechanism via `replay_quarantined_event` and `replay_all_quarantined`.
  - Operations & CLI:
    - Implemented `scripts/run_event_consumer.py` CLI runner with `--consumer-name`, `--group-id`, `--topic`, `--once`, `--status`, `--replay`, `--replay-quarantined`.
    - Created comprehensive documentation in `docs/event_consumers.md` covering architecture, idempotency, offset safety, retry/quarantine policy, runbooks, and future integration points.
  - Quality & Verification:
    - Implemented 11 comprehensive tests in `tests/test_event_consumer.py` covering: envelope parsing, dispatch, unsupported versions, malformed JSON, duplicate delivery skipping, concurrent multi-worker delivery, atomic rollback, backoff retries, explicit operator replay, privacy scrubbing, unhandled event types, and live Kafka roundtrip.
    - Focused consumer test suite: 11 of 11 passed in 10.00s.
    - Full backend test suite: 102 of 102 passed in 113.74s (0 failures, 0 errors).
    - Code quality: `ruff check .` (0 errors), `ruff format --check .` (clean across 57 files), `mypy .` (strict passed, 0 errors across 52 source files).
    - Database & Alembic: `alembic check` verified clean (code 0).
    - Repository safety: Zero Git write operations executed. Developer retains manual Git ownership.

