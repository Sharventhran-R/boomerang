@[Project Memory](.agents/AGENT_MEMORY.md)
@[Design Policy](.agents/DESIGN_POLICY.md)

## Tech Stack
- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.x, PostgreSQL/PostGIS, aiokafka, Pydantic v2.
- Frontend: Dart 3.x, Flutter 3.x, `google_fonts`, Material 3 design tokens.
- Backend Testing: pytest
- Backend Linting/Formatting: Ruff
- Backend Type Checking: mypy
- Frontend Formatting & Testing: `dart format`, `flutter analyze`, `flutter test`

## Canonical Commands (Windows)
### Backend
- Create environment: `python -m venv .venv`
- Activate environment: `.venv\Scripts\Activate.ps1`
- Install dependencies: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
- Run backend: `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`
- Lint: `.venv\Scripts\python.exe -m ruff check .`
- Format check: `.venv\Scripts\python.exe -m ruff format --check .`
- Typecheck: `.venv\Scripts\python.exe -m mypy .`
- All tests: `.venv\Scripts\python.exe -m pytest`
- Single test: `.venv\Scripts\python.exe -m pytest path/to/test_file.py::test_name -q`

### Frontend
- Format code: `cd frontend; dart format .`
- Analyze code: `cd frontend; flutter analyze`
- All tests: `cd frontend; flutter test`
- Single test: `cd frontend; flutter test path/to/test_file.dart`

## Design Skills & UI Refinement
Consult the three installed workspace design skills whenever implementing UI features, redesigning screens, auditing layout quality, or refining accessibility:
1. **`design-taste-frontend`** (`.agents/skills/design-taste-frontend/SKILL.md`): Use for visual hierarchy, typography scaling, spacing, layout composition, and avoiding generic template defaults.
2. **`web-design-guidelines`** (`.agents/skills/web-design-guidelines/SKILL.md`): Use for auditing accessibility (`Semantics`, `Tooltip`), keyboard focus, form input patterns, and responsive behavior adapted to Flutter.
3. **`awesome-design`** (`.agents/skills/awesome-design/SKILL.md`): Use to reference real-world design system specifications and token structures under `.agents/skills/awesome-design/design-md/`.

### Design Authority Order
Resolve conflicting recommendations in this order:
1. Boomerang product requirements & business rules (`.agents/PROJECT_SPEC.md`).
2. Google Stitch HTML/PNG export references (`stitch_export/`).
3. Boomerang established theme and design tokens (`frontend/lib/theme.dart`, `.agents/DESIGN_POLICY.md`).
4. Applicable guidance from the three design skills.

## Execution Guardrails
1. **Minimal Diffs**: Make precise, in-place edits. Do not rewrite files unnecessarily.
2. **Strict Typing**: Zero tolerance for untyped or loose variables. All Python code must pass `mypy --strict`.
3. **Mandatory Tests**: Run the appropriate single-test, test suite, or typecheck command before marking a task as complete.
4. **Session Logging**: Update `.agents/AGENT_MEMORY.md` under `# Session Log` after completing substantive milestones.
5. **No Global Dependencies**: Use `.venv\Scripts\python.exe` for all tool executions.
6. **Manual Git Operations**: Never execute `git` commands autonomously (like `git add`, `git commit`). Always ask the user to perform them manually.
7. **Consumer Reliability Invariants (Mandatory Architectural Rules)**:
   - Handler database mutations and the `ConsumerEvent` idempotency record must commit atomically.
   - A failure to commit a Kafka offset after a successful database commit must not rerun handler side effects in the same processing retry sequence.
   - Redelivery after a crash must be safe through the durable idempotency barrier.
   - Offsets must advance only through contiguous, durably processed or safely quarantined records.
   - A consumer must not commit offsets for partitions it no longer owns.
   - Partition revocation and reassignment must update offset-tracker state safely.
   - External side effects must not be assumed idempotent merely because database writes are deduplicated.
   - Preserve at-least-once delivery semantics; do not claim exactly-once processing across PostgreSQL, Kafka, and external services.
   - Quarantine and replay must remain observable, controlled, and privacy-safe.
8. **Multi-Consumer Production Verification Requirement**:
   - Do not claim multi-consumer rebalance behavior is fully production-verified until a live consumer-group rebalance integration test passes against an actual Kafka broker (see `.agents/AGENT_MEMORY.md` under `## Production-Readiness Checklist`). Existing mock/unit tests do not substitute for live rebalance verification.
9. **Phase Progression Guardrail**:
   - Do not start Phase 8 or later phases without explicit user authorization.

## Git Ownership & Repository Safety

The AI agent MUST NOT perform any Git operations that modify repository history or staging state.

Git is manually controlled by the developer.

The agent MUST NOT:

- run `git init`
- run `git add`
- run `git commit`
- run `git push`
- run `git pull`
- run `git merge`
- run `git rebase`
- run `git reset`
- run `git checkout`
- run `git switch`
- create or modify branches
- modify Git history
- stage or unstage files
- create tags
- amend commits
- force push
- delete branches

The agent MAY use read-only Git commands when necessary for development context or verification, such as:

- `git status`
- `git diff`
- `git diff -- <file>`
- `git log`
- `git show`
- `git branch --show-current`

Read-only Git commands must not modify repository state.

The agent must NEVER automatically commit after completing a task.

After completing a milestone, the agent should instead report:

1. Files changed
2. Summary of changes
3. Tests/verification performed
4. Current `git diff` status if inspected
5. Suggested commit message

The developer will manually review, stage, and commit the changes.
