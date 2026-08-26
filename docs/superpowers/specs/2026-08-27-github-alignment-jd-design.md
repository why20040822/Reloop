# RE:LOOP GitHub Alignment And JD Parsing Design

## Goal

Make `why20040822/Reloop` the single source of truth for the current React/FastAPI application, preserve the current restrained workbench style, improve talent presentation using the supplied reference frontend, and add a production-safe DeepSeek JD parsing flow before pushing a reviewed and verified branch to GitHub.

## Source Of Truth And Migration Boundary

- Start from `why20040822/Reloop` `main`, not from the unrelated local Next.js history.
- Port the current React/Vite source, OAuth callback bridge, per-user TTC binding, token vault, sync isolation, tests, and generated `webapp/` bundle into that history.
- Keep the GitHub backend's existing talent normalization, recommendation engine, and database compatibility behavior unless the newer local implementation fixes a verified contract mismatch.
- Do not copy local databases, `.env`, credentials, temporary scripts, `node_modules`, old Next.js files, or browser-managed DeepSeek key code.
- The committed React source in `frontend/` is authoritative; `webapp/` is a reproducible Vite build served by FastAPI.

## Authentication And TTC Contract

- `GET /auth/feishu/url` derives its fixed callback from `BRAINX_AUTH_PUBLIC_BASE_URL`; the browser does not supply an arbitrary `redirect_uri`.
- Provider callbacks land on `/auth/feishu/callback` or `/auth/ttc/callback`, then redirect query parameters into the SPA hash routes.
- Invalid explicit `X-Auth-Token` returns `401`; it never silently downgrades to guest data.
- Logged-in users bind their own TTC login token through `POST /auth/ttc/bind`. Tokens are validated, encrypted at rest, never returned, and used only for that owner's sync.
- Guest mode may use a separately configured read-only shared TTC token. A logged-in user's sync never falls back to that token.
- `GET /auth/me` returns `ttc_connected`, `ttc_space_id`, and `ttc_bound_name` in addition to the existing identity and pool count fields.

## JD Parsing Architecture

### Configuration

DeepSeek configuration is backend-only:

- `BRAINX_DEEPSEEK_API_KEY`
- `BRAINX_DEEPSEEK_BASE_URL`, default `https://api.deepseek.com`
- `BRAINX_DEEPSEEK_MODEL`, default `deepseek-chat`
- `BRAINX_DEEPSEEK_TIMEOUT_SECONDS`, default `30`

The DeepSeek key is never accepted from the browser, persisted in browser storage, returned by an API, logged, or included in the frontend bundle. Existing embedding configuration remains separate because DeepSeek does not provide the embedding contract used by the recommendation engine.

### Parsing API

`POST /positions/parse-jd` accepts:

```json
{
  "jd_text": "raw JD text"
}
```

It requires a non-empty JD with a bounded length, calls DeepSeek using strict JSON output, validates the response with Pydantic, and returns:

```json
{
  "title": "岗位名称",
  "summary": "岗位摘要",
  "responsibilities": ["职责"],
  "required_skills": ["必备技能"],
  "preferred_skills": ["加分技能"],
  "experience": "经验要求",
  "education": "学历要求",
  "location": "地点",
  "industry_keywords": ["行业关键词"],
  "salary_range": "薪资范围",
  "team_size": "团队规模",
  "reporting_line": "汇报对象",
  "language_requirements": ["语言要求"]
}
```

The endpoint does not write a position. Missing configuration, timeout, network failure, non-JSON output, or schema failure produces an explicit sanitized error. The user's raw JD remains in the drawer.

### Persistence

- `positions.jd_text` remains the raw source JD.
- Add nullable `positions.jd_analysis` JSON and `positions.jd_analysis_version` string columns.
- Extend the existing idempotent startup migration and SQL schema so existing databases are upgraded without destructive migration.
- `POST /positions` accepts an optional validated `jd_analysis`. A structured analysis may only be saved with non-empty raw JD.
- Updating a position creates the existing new active version and stores raw plus structured JD atomically.
- Recommendation cache identity incorporates raw JD as it does today; structured fields improve display and future scoring without changing current ranking semantics unexpectedly.

## Frontend Interaction

### Match Entry

- `活跃优先` continues to work without a position or JD.
- Clicking `岗位匹配` with a selected position that already has `jd_analysis` starts matching immediately.
- If no parsed position is available, clicking `岗位匹配` opens a right-side JD drawer and leaves the dashboard in activity mode until confirmation.
- The position selector remains visible in match mode. A `解析新 JD` command opens the same drawer for another position.

### Right Drawer

The drawer has three stable states:

1. Input: raw JD textarea and `解析 JD` command.
2. Parsing: disabled controls and a clear progress state.
3. Review: editable fields for every structured property, with list fields edited as one item per line.

`确认并开始匹配` saves the position, refreshes positions, selects it, closes the drawer, and enters match mode. Closing the drawer or a parse failure preserves the raw input for the session and performs no save. Escape and backdrop close the drawer only when not submitting. Focus returns to the trigger.

### Talent Presentation

Preserve the current sidebar, typography, palette, spacing judgment, glass segmented control, and compact page hierarchy. Borrow only the supplied reference frontend's information organization:

- Rank candidates vertically below the page controls.
- Each desktop row shows person, current company/position, years of experience, education, latest signal/reason, score, and recent activity.
- Activity mode sorts by recent activity. Match mode preserves backend recommendation rank and displays match score/reason.
- Rows navigate to the current talent detail route; no nested cards or copied reference topbar/sidebar are introduced.
- Mobile collapses secondary fields into a readable two-line row without horizontal scrolling.
- Talent library and followed views keep their current table behavior, with the three requested subtitles removed:
  - `搜索并处理人才库中的候选人。`
  - `你已标记的重点人选。`
  - `岗位与 JD 会直接影响人才匹配与排序。`

## Error Handling

- API errors are rendered in the relevant page or drawer, not browser alerts.
- A parse error never clears raw JD, creates a position, changes dashboard mode, or starts recommendation.
- A save error keeps the reviewed analysis editable.
- Authentication `401` clears stale browser auth and emits the existing auth-change event.
- TTC sync continues to expose progress by the exact returned `sync_id`.

## Verification And Release

- Use test-first changes for API contracts, database migration, parser behavior, frontend source contracts, and regressions.
- Mock only the external DeepSeek HTTP boundary; validate actual request construction and response parsing.
- Run the complete Python suite, TypeScript check, frontend tests, production Vite build, and generated-bundle checks.
- Run desktop and `390x844` browser scenarios for activity ordering, unparsed match entry, parse error preservation, editable review, successful save/match, existing parsed match, drawer focus/close, subtitle removal, sidebar, settings, and no horizontal overflow.
- Inspect browser console and network failures.
- Scan tracked files and the final diff for credentials, private tokens, `.env`, databases, temporary files, and unexpected generated artifacts.
- Perform an independent code review and fix all critical or important findings before push.
- Push the reviewed feature branch to `why20040822/Reloop`; do not force-push or modify production deployment.

## Non-Goals

- No production deployment or OAuth provider console changes.
- No browser-side DeepSeek key management.
- No new embedding provider or ranking formula rewrite.
- No wholesale redesign based on the reference frontend.
