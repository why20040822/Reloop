# RE:LOOP Position Company Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development. Every behavior change must begin with a focused failing test whose expected failure is observed before production code changes.

**Goal:** Add an optional recruiting-company identity to positions, make same-title positions from different companies coexist, select recommendations by position ID, and display positions consistently as `company - title` without changing scoring.

**Architecture:** `Position.company_name` is a nullable identity/display field mirrored into structured JD data. Position persistence versions rows by normalized owner/company/title. Recommendation APIs resolve an active owned position by ID when supplied, retain the legacy title lookup fallback, and isolate cache keys by ID/company. React stores a selected position ID and derives all labels through one helper.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, SQLite/MySQL schema, pytest, React 18, TypeScript, Vite, Node test runner.

## Global Constraints

- Work only in `/Users/shishen/Downloads/RE-LOOP-source 3/.worktrees/github-align-jd` on `codex/github-align-jd`.
- `company_name` is optional, trimmed, and normalized from blank text to `null`.
- DeepSeek may return a company only when it is explicitly stated in the JD; it must return `null` when uncertain and must not infer one.
- The final user-edited company value is authoritative and is stored both on the position row and in structured JD.
- Position identity for version replacement is owner + normalized company + normalized position name. Different companies may retain active positions with the same title.
- Recommendation endpoints prefer `position_id`, reject inactive or foreign IDs, and retain legacy `position_name` fallback.
- Recommendation cache identity includes position ID and company. Company must not enter embeddings, matching features, formulas, or weights.
- Preserve existing sidebar, compact Direct Glass visual language, responsive behavior, and unparsed-position drawer gate.
- Never commit secrets, private candidate payloads, local databases, or `.env` files. Do not push, merge, or deploy.

## Task 1: Add Backend Company Identity And ID-Based Recommendations

**Files:**
- Modify: `reloop/db/models.py`
- Modify: `reloop/db/engine.py`
- Modify: `reloop/schemas/jd.py`
- Modify: `reloop/schemas/talent.py`
- Modify: `reloop/modules/positions/jd_parser.py`
- Modify: `reloop/api/positions.py`
- Modify: `reloop/api/recommend.py`
- Modify: `reloop/modules/recommendation/engine.py`
- Modify: `sql/schema.sql`
- Modify/Create focused tests under `tests/`

**Required behavior:**

- Add nullable `positions.company_name VARCHAR(128)` to SQLAlchemy, SQL schema, and the idempotent SQLite startup migration. Repeated `init_db()` calls must leave exactly one column.
- Add optional `company_name` to `JDAnalysis`, `PositionCreate`, and `PositionOut`.
- Require the parser prompt to extract only an explicitly named recruiting company and return JSON `null` when absent or uncertain.
- Normalize company by trimming; empty or whitespace-only input becomes `None`. `PositionCreate.company_name` is authoritative and overwrites any parsed company before persistence.
- Deactivate only an existing active position belonging to the same owner with the same trimmed company identity and position name. Preserve active same-title positions for other companies.
- Extend `POST /recommend/compute` and `GET /recommend/result` with optional `position_id`. When both ID and title exist, ID wins. An ID must resolve to an active position owned by the current user; otherwise return 404. Legacy title-only behavior remains compatible.
- Include position ID and company in the recommendation cache key while keeping company out of matching inputs and scoring.
- Tests must cover parser company present/absent, blank normalization, migration idempotence, same-company replacement, different-company coexistence, ID precedence, foreign/inactive ID rejection, legacy title lookup, and cache isolation.

**TDD steps:**

1. Add focused tests and run them to observe expected RED failures caused by missing fields/contracts.
2. Implement the smallest backend changes needed for GREEN.
3. Run the focused backend tests and the full `pytest -q` suite.
4. Run `git diff --check`, self-review, and commit with a scoped message.

## Task 2: Use Company Labels And Position IDs In React

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/jd.ts` or add a focused position helper beside existing frontend helpers
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css` only as needed for long labels and responsive layout
- Modify/Create focused Node tests under `tests/`
- Rebuild: `webapp/`

**Required behavior:**

- Extend frontend `JDAnalysis` and `Position` types with optional nullable `company_name`.
- Add one pure `formatPositionLabel(position)` helper. It returns `company - title` for a nonblank company and only `title` otherwise.
- Store selected position identity as ID, use position IDs as `<option>` values, and pass `position_id` to both recommendation compute and result requests.
- Keep the legacy API capability available if required by existing callers, but all current React matching flows use IDs.
- Put editable `招聘公司` before `岗位名称` in the JD review form. Saving uses the edited company as both top-level `company_name` and structured analysis company.
- Add an optional `招聘公司` field before `岗位名称` in the manual position form.
- Use the unified label in the picker, position management list, delete aria-label/confirmation, current match heading, and any fallback insertion after save.
- Preserve the gate: unparsed positions open the JD drawer; parsed positions enter matching directly. Same-title positions from different companies must remain independently selectable.
- Ensure long company names wrap or truncate without horizontal overflow on desktop or at 390x844.
- Update local mock/demo position data to `北辰智能（演示） - AI 产品经理（演示）`.
- Tests must cover label fallback, ID option selection and requests, company editing/saving, manual company input, unparsed gating, and same-title selection.

**TDD steps:**

1. Add focused Node tests and run `npm run test:web` to observe expected RED failures.
2. Implement the smallest frontend changes needed for GREEN.
3. Run `npm run test:web`, `npm run check:web`, and `npm run build:web`.
4. Run `git diff --check`, self-review, and commit with a scoped message.

## Final Verification

- Run `pytest -q`, `npm run test:web`, `npm run check:web`, `npm run build:web`, and `git diff --check`.
- Inspect the full branch diff for secrets, scoring regressions, owner isolation, ID/title ambiguity, and generated asset consistency.
- Sync only verified source/build changes and the local demo position update into `/Users/shishen/Downloads/RE-LOOP-source 3`; preserve unrelated user files.
- Restart the local server and verify desktop plus 390x844: long labels do not overlap, drawer and manual form remain usable, and two same-title positions target different IDs.
- Keep the feature branch/worktree. Do not push, merge, deploy, or delete it.
