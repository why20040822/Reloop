# Final Position/Company Fixes Report

Date: 2026-08-27
Branch: `codex/github-align-jd`
Base commit: `619862ec8e5d33df5084a84d021d052caa63d26c`

## Findings and implementation

### 1. Authentication boundaries

Finding: token-enforced requests still had paths that could trust `X-Owner-User-Id`
or provision/use the anonymous guest owner for writes.

Implementation:

- Token enforcement now rejects missing or invalid signed sessions before considering
  owner headers or guest fallback.
- Owner-header and guest compatibility exists only with
  `BRAINX_AUTH_REQUIRE_TOKEN=false`.
- Production TTC sync and raw ingest require a signed, existing, non-guest user.
- Unsigned development sync writes require an explicit owner header; anonymous guest
  fallback cannot start a write.
- TTC login and legacy bind endpoints always require a signed, non-guest user.

Primary files: `reloop/api/deps.py`, `reloop/api/sync.py`, `reloop/api/auth.py`,
`tests/test_auth_security.py`, `tests/test_sync_pipeline.py`.

### 2. Correlated, secret-safe callbacks

Finding: provider callbacks lacked durable random correlation, and TTC credentials or
Feishu provider codes could reach browser-visible callback data.

Implementation:

- Added `auth_flow_tokens`, storing only SHA-256 token/browser-binding digests with
  provider, purpose, expiry, user binding, and one-use consumption state.
- Feishu and TTC authorization issue cryptographically random state bound to an
  HttpOnly, Secure, SameSite=Lax browser cookie. TTC state also binds the initiating
  authenticated user.
- Feishu code exchange now occurs on the backend. The SPA receives only an opaque,
  expiring, single-use session handle and exchanges that handle once.
- TTC callback state is consumed before credential processing. The backend validates,
  encrypts, binds, and starts owned sync, then redirects with status only.
- Callback query redaction moves provider code/token values into ASGI state and
  rewrites the request query before downstream/access logging. Exact and trailing-slash
  callback paths are covered.
- React StrictMode duplicate effects share only the in-flight operation; settled
  operations are released so later reconnect attempts can retry.
- Removed the dead plaintext auto-login module.

Primary files: `reloop/modules/auth/flows.py`, `reloop/modules/auth/redaction.py`,
`reloop/db/models.py`, `reloop/api/auth.py`, `reloop/main.py`,
`frontend/src/lib/ttcCallback.ts`, `frontend/src/App.tsx`,
`tests/test_auth_callback_urls.py`, `tests/ttc-callback.test.mjs`.

### 3. TTC URL compatibility

Finding: a retained base or API path ending in `/all-talents` could duplicate path
segments, and the authorization default used the gateway host instead of the app host.

Implementation:

- TTC collection URL construction recognizes both host-only/new API roots and retained
  legacy `/all-talents` roots.
- Mixed legacy-base/default-path configuration no longer appends an already-present API
  prefix.
- Shared and owned endpoints are derived from one normalized root.
- Default authorize URL is `https://app.ttcadvisory.com/auth/authorize`; API requests
  remain on `https://gateway.ttcadvisory.com`.

Primary files: `reloop/modules/sync/client.py`, `reloop/modules/auth/ttc.py`,
`reloop/config.py`, `tests/test_ttc_auth_flow.py`.

### 4. Canonical position identity

Finding: legacy whitespace/blank company values could evade identity replacement, and
active duplicate rows were not normalized deterministically.

Implementation:

- Startup migration trims stored title/company values, converts blank company to null,
  and keeps the newest active duplicate by `(created_at, id)` for each owner/company/title
  identity.
- Runtime lookup compares trimmed stored values so directly seeded legacy rows are
  replaced by canonical requests before startup migration can run.
- Company remains an identity/cache discriminator only; scoring code is unchanged.

Primary files: `reloop/db/engine.py`, `reloop/api/positions.py`,
`tests/test_position_company.py`.

### 5. Storage-safe 50,000-character JD contract

Finding: request validation allowed the documented JD size while production MySQL DDL
used `TEXT`, and image limits were per image rather than cumulative.

Implementation:

- `positions.jd_text` and `recommend_runs.jd_text` use portable SQLAlchemy text with a
  MySQL `MEDIUMTEXT` variant.
- Startup emits idempotent MySQL type upgrades only when a column is not already
  `MEDIUMTEXT`.
- Production DDL creates both JD columns as `MEDIUMTEXT` and includes repeatable
  `MODIFY COLUMN` upgrades.
- `PositionCreate.jd_text` and parsed `source_text` are bounded to 50,000 characters.
- Uploaded JD images have a cumulative 40-million-pixel ceiling across the request.

Primary files: `reloop/db/models.py`, `reloop/db/engine.py`, `sql/schema.sql`,
`reloop/schemas/jd.py`, `reloop/schemas/talent.py`, `tests/test_jd_parser.py`,
`tests/test_position_company.py`.

### 6. Authoritative edited review titles

Finding: saving a reviewed JD could retain the old top-level title and leave the
selected row active after a rename.

Implementation:

- Structured analysis title is authoritative for the saved `position_name`.
- Save payload accepts `replacement_position_id`; backend verifies active ownership,
  rejects foreign/inactive IDs, and deactivates the replacement transactionally.
- Frontend sends the selected position ID, selects the returned row ID, and removes
  replaced or duplicate fallback rows when list refresh fails.
- Same-title/company identity semantics and ID-over-name recommendation selection remain
  intact.

Primary files: `reloop/api/positions.py`, `reloop/schemas/talent.py`,
`frontend/src/lib/positionFlow.ts`, `frontend/src/lib/positionSave.ts`,
`frontend/src/App.tsx`, `tests/test_position_company.py`,
`tests/position-company-ui.test.mjs`.

### 7. Approved browser-local DeepSeek override

Finding: the continuation incorrectly treated the approved browser-local DeepSeek key
as deprecated credential exposure and removed its UI, storage, request header, and
backend request override.

Implementation:

- Restored the masked Advanced Settings input, show/hide and clear icon buttons, and
  exact `仅保存在此浏览器` label.
- The value is trimmed into the dedicated `reloop.deepseekApiKey` localStorage item and
  never enters `reloop.cfg`.
- Only same-origin `/positions/parse-jd` requests can receive
  `X-DeepSeek-Api-Key`; a stored key with a cross-origin backend fails before `fetch`,
  and every other API call omits the header.
- The backend uses the header only for that parser instance and falls back to
  `BRAINX_DEEPSEEK_API_KEY` when the request header is blank or absent.
- Added a regression requiring this behavior to coexist with opaque callback handles,
  callback redaction, and StrictMode in-flight deduplication.

Primary files: `frontend/src/lib/api.ts`, `frontend/src/App.tsx`,
`reloop/api/positions.py`, `tests/position-company-ui.test.mjs`,
`tests/jd-ui.test.mjs`, `tests/ttc-callback.test.mjs`, `tests/test_jd_parser.py`.

### 8. Test and repository hygiene

Finding: the sync pipeline was an uncollected script, pipeline collection mutated DB
environment/files, and a generated SQLite DB was tracked.

Implementation:

- Converted sync pipeline coverage into one collected authenticated async test with
  polling and cross-owner denial.
- Centralized pytest DB isolation in `tests/conftest.py`; collection no longer deletes
  files or overrides the DB target from a test module.
- Removed `tests/test_reloop_104740.db` from the branch.
- Added a real cached-engine regression proving `position_id` wins over a conflicting
  title.
- Removed the changed pipeline test's return-value warning.

## TDD evidence

Earlier RED runs in this worktree covered production header impersonation, guest-pool
poisoning, strict TTC binding, state mismatch/expiry/replay, provider secret exposure,
legacy position whitespace, MySQL type mismatch, JD bounds, authoritative titles,
replacement ownership, ID precedence, callback StrictMode duplication, and sync
collection/auth behavior. The old gateway authorize default was also mutation-checked
and failed the focused contract before restoration.

Additional RED/GREEN evidence from the final continuation:

- Mixed TTC base/path:
  `pytest -q tests/test_auth_callback_urls.py tests/test_ttc_auth_flow.py -x`
  produced `1 failed, 19 passed`; after root
  normalization, the focused set produced `28 passed`.
- Production schema parity: the new DDL contract failed because
  `auth_flow_tokens` was absent; after DDL changes it produced `1 passed`.
- Trailing-slash callback redaction failed with missing ASGI secret state; after path
  normalization it produced `1 passed`.
- Settled callback retry failed `1 != 2` with `3 passed, 1 failed`; after making the
  registry in-flight-only it produced `4 passed`.
- Changed Python surface produced `103 passed` before the repository-wide rerun.
- Restored browser-key frontend contracts:
  `node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/position-company-ui.test.mjs tests/jd-ui.test.mjs tests/ttc-callback.test.mjs`
  produced `15 passed, 4 failed` while the storage helper, header, and Settings controls
  were absent; after restoration the same command produced `19 passed`.
- Transient-header precedence:
  `pytest -q tests/test_jd_parser.py -k 'parse_endpoint_uses_transient_header_key_without_persisting_it or parse_endpoint_falls_back_to_server_key_without_transient_header'`
  produced `1 failed, 1 passed` because the server key incorrectly won. The expanded
  endpoint rerun after restoration produced `4 passed, 27 deselected`.

## Final verification

Fresh verification after all implementation and self-review fixes:

- `pytest -q`: `104 passed`, exit 0. Six warnings remain from third-party/deprecated
  interfaces: Starlette TestClient/httpx, two Pydantic v2 class Config warnings, and
  SQLite's deprecated default datetime adapter in three expiry tests.
- `npm run test:web`: `38 passed`, `0 failed`, exit 0.
- `npm run check:web`: exit 0.
- `npm run build:web`: exit 0; Vite transformed 1,595 modules and generated
  `webapp/assets/index-DIFwGD8O.js` (209.35 kB, 68.31 kB gzip).
- `git diff --check`: exit 0.

## Commits

- `d3e9e37` - `fix: harden auth and position contracts`
- `8f51510` - `fix(web): align secure callbacks and position saves`
- `0f297e1` - `fix: restore browser-local DeepSeek key`

The documentation and this report are committed separately after these implementation
commits so the report can contain stable implementation hashes.

## Self-review

- Confirmed no files under `reloop/modules/scoring` changed and no scoring weights were
  modified.
- Confirmed browser DeepSeek key UI/storage/header behavior is present, uses only the
  dedicated storage item, fails closed across origins, and leaves all non-parse requests
  header-free.
- Confirmed provider TTC tokens and Feishu codes are absent from SPA callback handling,
  redirect bodies/locations, flow payloads, and redacted downstream query strings.
- Confirmed production schema, ORM types, startup migration, and examples agree.
- Confirmed generated `webapp/index.html` references the new tracked hash and the old
  asset is removed; the bundle contains both the key boundary and opaque callback flow.
- Confirmed no `test_reloop*.db` file remains in this worktree.
- Secret-pattern scan found no credential-like additions; examples and tests contain
  placeholders/fake values only.

## Concerns

- Expired and consumed `auth_flow_tokens` remain in the table for auditability. A
  periodic retention cleanup may be appropriate if authorization volume becomes high.
- Existing third-party/Pydantic/SQLite deprecation warnings are outside this fix wave;
  they do not affect the green verification results but should be retired before their
  upstream removals.
- No push, merge, deployment, real-secret write, or scoring change was performed.
