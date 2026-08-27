# RE:LOOP Position Company Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development. Every behavior change must begin with a focused failing test whose expected failure is observed before production code changes.

**Goal:** Add an optional recruiting-company identity to positions, make same-title positions from different companies coexist, select recommendations by position ID, and display positions consistently as `company - title` without changing scoring.

**Architecture:** `Position.company_name` is a nullable identity/display field mirrored into structured JD data. Position persistence versions rows by normalized owner/company/title. Recommendation APIs resolve an active owned position by ID when supplied, retain the legacy title lookup fallback, and isolate cache keys by ID/company. React stores a selected position ID and derives all labels through one helper.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, SQLite/MySQL schema, pytest, React 18, TypeScript, Vite, Node test runner.

## Global Constraints

- Work only in `/Users/shishen/Downloads/RE-LOOP-source 3/.worktrees/github-align-jd` on `codex/github-align-jd`.
- `company_name` is optional, trimmed, and normalized from blank text to `null`.
- DeepSeek may return a company only when it is explicitly stated in the JD; it must return `null` when uncertain and must not infer one.
- Text-only parsing uses the official `deepseek-v4-flash` model. Parsing with images uses the official `deepseek-v4-flash-vision-exp` model and OpenAI-compatible `image_url` content blocks. A user-entered API key is stored only in that browser and is sent transiently to the same-origin parse endpoint; it is never committed, persisted, logged, or returned by the backend.
- The final user-edited company value is authoritative and is stored both on the position row and in structured JD.
- Position identity for version replacement is owner + normalized company + normalized position name. Different companies may retain active positions with the same title.
- Recommendation endpoints prefer `position_id`, reject inactive or foreign IDs, and retain legacy `position_name` fallback.
- Recommendation cache identity includes position ID and company. Company must not enter embeddings, matching features, formulas, or weights.
- Preserve existing sidebar, compact Direct Glass visual language, responsive behavior, and unparsed-position drawer gate.
- Remove the Settings page `使用偏好` language section and its save action. Keep account/talent-pool and advanced settings, and remove preference wording from the page description.
- Never commit secrets, private candidate payloads, local databases, or `.env` files. Do not push, merge, or deploy.

## Task 1: Add Backend Company Identity And ID-Based Recommendations

**Files:**
- Modify: `reloop/db/models.py`
- Modify: `reloop/db/engine.py`
- Modify: `reloop/schemas/jd.py`
- Modify: `reloop/schemas/talent.py`
- Modify: `reloop/modules/positions/jd_parser.py`
- Modify: `reloop/config.py`
- Modify: `.env.example`
- Modify: `reloop/api/positions.py`
- Modify: `reloop/api/recommend.py`
- Modify: `reloop/modules/recommendation/engine.py`
- Modify: `sql/schema.sql`
- Modify/Create focused tests under `tests/`

**Required behavior:**

- Add nullable `positions.company_name VARCHAR(128)` to SQLAlchemy, SQL schema, and the idempotent SQLite startup migration. Repeated `init_db()` calls must leave exactly one column.
- Add optional `company_name` to `JDAnalysis`, `PositionCreate`, and `PositionOut`.
- Require the parser prompt to extract only an explicitly named recruiting company and return JSON `null` when absent or uncertain.
- Default `DEEPSEEK_MODEL` to `deepseek-v4-flash` and add a separately configurable vision model defaulting to `deepseek-v4-flash-vision-exp`.
- Extend the parse preview request to accept zero to four pasted JPEG/PNG/GIF/WebP data URLs, each at most 8 MiB decoded, no more than 8192 pixels on either side, and no more than 40 million total pixels. This accepts standard 4K screenshots while bounding decompression memory. Require nonblank text or at least one valid image, reject malformed/unsupported image data, and perform no database write on rejection.
- Accept an optional `X-DeepSeek-Api-Key` request header on the parse preview endpoint. A nonblank request key overrides the configured server key only for that call; do not persist, return, or log it. Retain the configured-key fallback for deployments.
- For image requests, send text plus official OpenAI-compatible `image_url` user-content blocks to the vision model. Ask DeepSeek to transcribe the source JD and return that text with the structured analysis so the frontend can refill the editable raw-JD field. Text-only requests continue to return the submitted raw JD as the source text.
- Normalize company by trimming; empty or whitespace-only input becomes `None`. `PositionCreate.company_name` is authoritative and overwrites any parsed company before persistence.
- Deactivate only an existing active position belonging to the same owner with the same trimmed company identity and position name. Preserve active same-title positions for other companies.
- Extend `POST /recommend/compute` and `GET /recommend/result` with optional `position_id`. When both ID and title exist, ID wins. An ID must resolve to an active position owned by the current user; otherwise return 404. Legacy title-only behavior remains compatible.
- Include position ID and company in the recommendation cache key while keeping company out of matching inputs and scoring.
- Tests must cover parser company present/absent, transient request-key forwarding with no persistence, Flash/Vision model routing, official image block shape, image-only parsing with returned source text, malformed/oversized/unsupported image rejection, blank normalization, migration idempotence, same-company replacement, different-company coexistence, ID precedence, foreign/inactive ID rejection, legacy title lookup, and cache isolation.

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
- Allow users to paste screenshots directly into the JD input area and also choose up to four image files. Show compact previews with per-image remove controls, accept JPEG/PNG/GIF/WebP up to 8 MiB each, send images only to the backend parse endpoint, and refill the raw-JD textarea with DeepSeek's extracted source text before review/save.
- Add an optional `招聘公司` field before `岗位名称` in the manual position form.
- Use the unified label in the picker, position management list, delete aria-label/confirmation, current match heading, and any fallback insertion after save.
- Preserve the gate: unparsed positions open the JD drawer; parsed positions enter matching directly. Same-title positions from different companies must remain independently selectable.
- Ensure long company names wrap or truncate without horizontal overflow on desktop or at 390x844.
- Remove the complete Settings `使用偏好` section, language selector, preference save state/action, and related preference wording without changing advanced data-source settings.
- Add a masked DeepSeek API Key input inside Settings `高级设置`, with show/hide and clear controls. Save it under a dedicated browser-local key and label it `仅保存在此浏览器`; never include it in the regular config object, source, build output, console, or error text. `api.parseJd` sends it only as `X-DeepSeek-Api-Key` on the same-origin parse call, and no other request receives the header.
- Update local mock/demo position data to `北辰智能（演示） - AI 产品经理（演示）`.
- Tests must cover label fallback, ID option selection and requests, company editing/saving, manual company input, browser-only secret read/write/clear, parse-only key header behavior, image paste/file validation/removal and request payloads, extracted-text refill, unparsed gating, same-title selection, and absence of the Settings language-preference section.

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
