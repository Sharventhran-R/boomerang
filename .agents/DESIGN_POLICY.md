# Boomerang Design Policy & Token Specification

@[Project Specification](.agents/PROJECT_SPEC.md)
@[Project Memory](.agents/AGENT_MEMORY.md)

This document defines Boomerang's design system hierarchy, established visual tokens, Stitch screen reference mappings, and guidelines for applying installed design skills.

---

## 1. Design Authority Order

When designing, refining, or auditing interfaces, resolve conflicts in this strict order:

1. **Boomerang Product Requirements & Business Rules** (`.agents/PROJECT_SPEC.md`): Functional integrity, report data models, and user privacy take highest precedence.
2. **Exported Google Stitch HTML & PNG References** (`stitch_export/`): Source of truth for layout composition, section hierarchy, and component structure.
3. **Established Boomerang Theme & Design Tokens** (`frontend/lib/theme.dart`): Centralized color palette, border radii, typography pairings, and elevation surfaces.
4. **Design Skills Guidance**:
   - `design-taste-frontend`: Visual hierarchy, spatial cadence, deliberate composition, and anti-template discipline.
   - `web-design-guidelines`: Accessibility semantics, focus visibility, keyboard navigation, input ergonomics, and responsive adaptation.
   - `awesome-design`: Curated reference library of 55+ design systems in Stitch DESIGN.md format (`.agents/skills/awesome-design/design-md/`).

---

## 2. Established Visual Identity & Design Tokens

Boomerang utilizes a dark, monochrome-led palette with intentional, high-contrast status accents.

### Color Tokens
- **Background**: `#080909` (Primary scaffold background)
- **Card Surface**: `#171819` (Default card and panel container)
- **Elevated Surface**: `#202122` (Modals, badges, chip containers, inputs)
- **Primary Text**: `#F5F5F5` (High-emphasis headers, active titles)
- **Secondary Text**: `#A5A8AA` (Subtitles, metadata, timestamps, inactive icons)
- **FOUND Status**: `#43D17D` (Item recovered / found badge)
- **MISSING Status**: `#F06464` (Item missing / alert badge)
- **Reward Accent**: `#D8AC4B` (Bounty / reward indicator)
- **Current Location**: `#35BFFF` (Spatial anchor, GPS vector, accent actions)

### Typography
- **Headings & Display**: `Hanken Grotesk` (Semibold / Bold, titles and numerical metrics)
- **Body & Labels**: `Inter` (Regular / Medium, readable body text, inputs, captions)
- Centralized in `frontend/lib/theme.dart` via `AppTheme.darkTheme`.

### Shape & Surface Elevation
- **Corner Radii**: Standard `12.0px` (`BorderRadius.circular(12)`). Badges and pill chips use `16.0px`–`20.0px`.
- **Translucent Overlays**: Subtle glassmorphism (`BackdropFilter` with `ImageFilter.blur(sigmaX: 10, sigmaY: 10)` and translucent background `Color(0xFF171819).withValues(alpha: 0.85)`) on floating elements (bottom navigation bar, map header controls).
- **Desktop/Tablet Constraint**: Mobile app views must remain constrained to `maxWidth: 600` on wide viewports to prevent desktop stretching.

---

## 3. Stitch Screen Reference Mapping

The repository includes 14 screen exports under `stitch_export/`:

| Screen Name | Stitch Export ID | Target / Implemented Flutter Widget |
| :--- | :--- | :--- |
| **Home (Browse & Activity)** | `dead0e5f63fd4bb1997e7e4065fd9068` | `HomeScreen` (`frontend/lib/ui/screens/home_screen.dart`) |
| **Explore Map** | `f43c8194dc86453f9c6502540f22295f` | `MapScreen` (`frontend/lib/ui/screens/map_screen.dart`) |
| **Choose Report Type** | `0e6ecf95933d48bba9856bbd455e09bd` | `ChooseReportTypeScreen` (`frontend/lib/ui/screens/choose_report_type_screen.dart`) |
| **Report Details** | `e27a557fa59c4e34a80dc491e7ba368a` | `ReportDetailsScreen` (`frontend/lib/ui/screens/report_details_screen.dart`) |
| **My Reports** | `4409e9342046443caacf14d70045f269` | `MyReportsScreen` (`frontend/lib/ui/screens/my_reports_screen.dart`) |
| **Profile** | `5350c3141cb54b6a9ad50b8a74061439` | `ProfileScreen` (`frontend/lib/ui/screens/profile_screen.dart`) |
| **Settings** | `2922a090a7f64c7a9b200fe03b3a70df` | `SettingsScreen` (`frontend/lib/ui/screens/settings_screen.dart`) |
| **Recovery Requests** | `325c904fe37c4927a3dcd8848df4cf58` | `RecoveryRequestsScreen` (`frontend/lib/ui/screens/recovery_requests_screen.dart`) |
| **Report Flow — Step 2 Missing** | `dd58dfcc38884f33ac7e2d7dc24a78a8` | Pending Phase 6.4 |
| **Report Flow — Step 3 Missing** | `bd3073925cf34b1ab860362bae730567` | Pending Phase 6.4 |
| **Report Flow — Success Missing**| `ad0a7a2c83fe49e38176f2ad53275b35` | Pending Phase 6.4 |
| **Report Flow — Step 2 Found**   | `d5c34e510b1a4c39a6e5c47b86e1729f` | Pending Phase 6.4 |
| **Report Flow — Step 3 Found**   | `2c334b4e247c4733b66ec2260ae1fdd7` | Pending Phase 6.4 |
| **Report Flow — Success Found**  | `ae31c8b5fbfb4b80a62a62679f1dea1d` | Pending Phase 6.4 |

---

## 4. Design Skills & Application Rules

### `design-taste-frontend` (`.agents/skills/design-taste-frontend/SKILL.md`)
- **When to use**: Visual layout refinement, spatial rhythm, typography scaling, card structures, and eliminating cookie-cutter template patterns.
- **Rules**:
  - Perform a one-line "Design Read" before implementing or restructuring screens.
  - Set appropriate dial parameters (`DESIGN_VARIANCE`, `MOTION_INTENSITY`, `VISUAL_DENSITY`). For Boomerang utility interfaces, recommend: `VARIANCE: 6`, `MOTION: 4`, `DENSITY: 4`.
  - Avoid AI defaults: no unnecessary purple gradients, no equal three-column card soup, no bloated animation loops.

### `web-design-guidelines` (`.agents/skills/web-design-guidelines/SKILL.md`)
- **When to use**: Auditing UI quality, accessibility compliance, input usability, and responsive ergonomics.
- **Flutter Adaptation Rules**:
  - Map `aria-label` / image `alt` to Flutter `Semantics(label: ..., child: ...)` and `Tooltip`.
  - Ensure interactive buttons have hit targets $\ge 44 \times 44$ px.
  - Form fields must declare proper `keyboardType`, `autofillHints`, and error text indicators.
  - Wrap overflow-prone rows in `Flexible`, `Expanded`, or `Wrap`.
  - Respect `MediaQuery.of(context).disableAnimations` for reduced motion settings.

### `awesome-design` (`.agents/skills/awesome-design/SKILL.md`)
- **When to use**: When evaluating component designs, micro-interactions, or token systems inspired by best-in-class dark mode platforms (e.g., `linear.app`, `vercel`, `raycast`, `supabase` located under `design-md/`).
- **Rules**:
  - Use as a reference library to inform component consistency.
  - Never override Boomerang's brand tokens with third-party branding.

---

## 5. Scope & Language Boundaries
- Maintain clear, grounded wording (e.g. "Missing", "Found", "Nearby Reports", "Recovery Request").
- Do **not** invent unsupported business domains: no cryptocurrency tokens, escrow services, payment processing, KYC identity verification, or automated biometric/telemetry protocols.
