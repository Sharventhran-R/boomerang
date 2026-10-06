@[Project Memory](.agents/AGENT_MEMORY.md)

## Tech Stack
- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.x, PostgreSQL/PostGIS, aiokafka, Pydantic v2.
- Testing: pytest
- Linting/Formatting: Ruff
- Type Checking: mypy

## Canonical Commands (Windows)
- Create environment: `python -m venv .venv`
- Activate environment: `.venv\Scripts\Activate.ps1`
- Install dependencies: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
- Run backend: `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`
- Lint: `.venv\Scripts\python.exe -m ruff check .`
- Format check: `.venv\Scripts\python.exe -m ruff format --check .`
- Typecheck: `.venv\Scripts\python.exe -m mypy .`
- All tests: `.venv\Scripts\python.exe -m pytest`
- Single test: `.venv\Scripts\python.exe -m pytest path/to/test_file.py::test_name -q`

## Execution Guardrails
1. **Minimal Diffs**: Make precise, in-place edits. Do not rewrite files unnecessarily.
2. **Strict Typing**: Zero tolerance for untyped or loose variables. All Python code must pass `mypy --strict`.
3. **Mandatory Tests**: Run the appropriate single-test or typecheck command before marking a task as complete.
4. **Session Logging**: Update `.agents/AGENT_MEMORY.md` under `# Session Log` after completing substantive milestones.
5. **No Global Dependencies**: Use `.venv\Scripts\python.exe` for all tool executions.
6. **Manual Git Operations**: Never execute `git` commands autonomously (like `git add`, `git commit`). Always ask the user to perform them manually.

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
