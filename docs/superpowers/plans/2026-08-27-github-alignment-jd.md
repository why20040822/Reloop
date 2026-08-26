# RE:LOOP GitHub Alignment And JD Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the current React/FastAPI product with `why20040822/Reloop`, add backend-only DeepSeek JD parsing with an editable right drawer, retain the current visual judgment, improve vertical talent ranking from the supplied reference, and push a reviewed branch.

**Architecture:** The GitHub repository remains the history and backend algorithm base. Authentication and TTC changes are ported narrowly from `/Users/shishen/Downloads/RE-LOOP-source 3`; JD parsing is a new backend service and validated schema; React consumes only typed same-origin APIs and keeps DeepSeek credentials server-side. The dashboard delegates pure row ordering and JD form conversion to testable helpers while `App.tsx` coordinates routes and data.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, httpx, pytest, React 18, TypeScript, Vite, Node test runner, CSS.

## Global Constraints

- Work only in `/Users/shishen/Downloads/RE-LOOP-source 3/.worktrees/github-align-jd` on `codex/github-align-jd`.
- Preserve the GitHub repository's recommendation, scoring, normalization, and talent schema behavior except where an explicit contract test requires change.
- Preserve the current React sidebar, typography, palette, compact hierarchy, settings layout, logo toggle, and mobile drawer.
- Use the supplied reference frontend only for vertical talent row information and ordering; do not copy its topbar, sidebar, dark mode, browser token entry, or old API client.
- DeepSeek credentials stay backend-only. Never commit or print a real key, OAuth secret, session token, TTC token, local database, `.env`, or source payload containing private candidate data.
- Parsing failure performs no database write, does not enter match mode, and preserves raw JD in the open drawer.
- Existing parsed positions enter match mode directly; unparsed positions open the drawer first.
- Remove exactly the three requested page subtitles and leave no blank placeholder.
- Do not deploy production or modify OAuth provider settings.
- Use TDD: every behavior change starts with a focused failing test and records the expected failure before implementation.

---

### Task 1: Port The React And Personal Authentication Baseline

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/public/favicon.svg`
- Create: `frontend/public/reloop-logo.png`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/components/DirectGlassSegment.tsx`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/sidebar.ts`
- Create: `tests/sidebar.test.mjs`
- Create: `tests/test_auth_callback_urls.py`
- Create: `tests/test_ttc_auth_flow.py`
- Create: `reloop/modules/auth/ttc.py`
- Create: `reloop/modules/auth/vault.py`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`
- Modify: `vite.config.ts`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `reloop/config.py`
- Modify: `reloop/db/models.py`
- Modify: `reloop/db/engine.py`
- Modify: `reloop/api/deps.py`
- Modify: `reloop/api/auth.py`
- Modify: `reloop/api/sync.py`
- Modify: `reloop/modules/sync/client.py`

**Interfaces:**
- Produces: `GET /auth/feishu/url`, fixed provider callbacks, `GET /auth/ttc/login-url`, `POST /auth/ttc/bind`, extended `GET /auth/me`, and per-owner `POST /sync/ttc`.
- Produces: React/Vite source whose `api.feishuLoginUrl()` needs no `redirect_uri`, whose TTC callback binds an owned token, and whose build writes `webapp/`.
- Preserves: all existing talent, position, recommendation, feedback, and ingest route contracts.

- [ ] **Step 1: Add the authentication and UI contract tests and verify RED**

Port the focused tests from the current local source, but keep test databases under pytest temporary paths. Required assertions:

```python
def test_invalid_session_token_does_not_silently_become_guest(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    response = client.get("/auth/me", headers={"X-Auth-Token": "invalid-session-token"})
    assert response.status_code == 401

def test_provider_callback_moves_query_into_spa_hash_route(monkeypatch):
    monkeypatch.setattr(settings, "auth_public_base_url", "https://reloop.example.test")
    response = client.get("/auth/feishu/callback?code=one-time-code&state=reloop", follow_redirects=False)
    assert response.headers["location"] == "https://reloop.example.test/#/auth/callback?code=one-time-code&state=reloop"
```

The TTC bind test must assert that plaintext is absent from the stored value and that `sync_for_user_async(user_id, auth_token=token, source="owned")` is called. The frontend test must require the logo toggle, persisted collapse helper, centered position arrow, and absence of the previously removed dashboard description.

Run:

```bash
pytest -q tests/test_auth_callback_urls.py tests/test_ttc_auth_flow.py
npm run test:web
```

Expected: FAIL because the GitHub backend lacks fixed callbacks and TTC bind routes, and because React source/tests are absent.

- [ ] **Step 2: Port the narrow backend changes**

Port only the current local authentication/TTC implementation and its necessary model/config/migration support. The dependency behavior must be:

```python
if x_auth_token:
    user_id = verify_session_token(x_auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录态无效或已过期, 请重新扫码登录")
```

The bind route stores `seal_user_token(body.token.strip())`; `/auth/me` determines connection by successfully unsealing; sync selects the logged-in owner's token and never falls back to the shared guest token for that owner.

- [ ] **Step 3: Port the React/Vite source and build configuration**

Bring the current React files and build configuration into GitHub history, excluding generated caches and local state. Keep these scripts:

```json
{
  "dev:web": "vite --host 0.0.0.0",
  "build:web": "vite build",
  "check:web": "tsc --noEmit",
  "test:web": "node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test tests/*.test.mjs"
}
```

Do not build yet; keep generated `webapp/` changes for Task 5.

- [ ] **Step 4: Verify GREEN and regression coverage**

Run:

```bash
pytest -q tests/test_auth_callback_urls.py tests/test_ttc_auth_flow.py tests/test_pipeline.py tests/test_sync_pipeline.py
npm run check:web
npm run test:web
```

Expected: all focused and inherited tests pass.

- [ ] **Step 5: Commit**

```bash
git add .env.example .gitignore README.md package.json package-lock.json tsconfig.json vite.config.ts frontend reloop tests
git commit -m "feat: align React authentication and TTC contracts"
```

---

### Task 2: Add The DeepSeek JD Parser And Persistence

**Files:**
- Create: `reloop/modules/positions/__init__.py`
- Create: `reloop/modules/positions/jd_parser.py`
- Create: `reloop/schemas/jd.py`
- Create: `tests/test_jd_parser.py`
- Modify: `reloop/config.py`
- Modify: `reloop/db/models.py`
- Modify: `reloop/db/engine.py`
- Modify: `reloop/schemas/talent.py`
- Modify: `reloop/api/positions.py`
- Modify: `.env.example`
- Modify: `sql/schema.sql`

**Interfaces:**
- Produces: `JDAnalysis`, `JDParseRequest`, `DeepSeekJDParser.parse(jd_text: str) -> JDAnalysis`.
- Produces: authenticated `POST /positions/parse-jd` with no write side effect.
- Extends: `PositionCreate.jd_analysis`, `PositionOut.jd_analysis`, `Position.jd_analysis`, and `Position.jd_analysis_version`.

- [ ] **Step 1: Write parser request/validation tests and verify RED**

Tests must use a fake `httpx.Client` transport at the external boundary and assert:

```python
def test_parse_jd_sends_backend_key_and_validates_json():
    result = parser.parse("负责平台产品，要求 5 年经验")
    assert result.title == "平台产品负责人"
    assert result.required_skills == ["产品规划"]
    assert seen_headers["Authorization"] == "Bearer test-deepseek-key"
    assert seen_payload["response_format"] == {"type": "json_object"}
```

Also implement four separately named tests: `test_parse_jd_rejects_missing_key_without_http_call`, `test_parse_jd_sanitizes_upstream_error_without_leaking_key`, `test_parse_endpoint_does_not_create_position`, and `test_parse_endpoint_rejects_blank_and_over_50000_character_jd`. The missing-key test passes `api_key=""` and a transport that raises if called; the sanitized-error test asserts the configured key and upstream body are absent from the exception text; the no-write test compares position counts before and after parsing; the length test sends both `"   "` and `"x" * 50001` and expects `422`.

Run: `pytest -q tests/test_jd_parser.py -k 'parse'`

Expected: FAIL because the schema, service, and route do not exist.

- [ ] **Step 2: Implement the validated parser service**

Use these public exceptions and method:

```python
class JDParserUnavailable(RuntimeError):
    pass

class JDParserError(RuntimeError):
    pass

class DeepSeekJDParser:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = settings.deepseek_api_key if api_key is None else api_key
        self.base_url = base_url or settings.deepseek_base_url
        self.model = model or settings.deepseek_model
        self.timeout_seconds = timeout_seconds or settings.deepseek_timeout_seconds
        self.transport = transport

    def parse(self, jd_text: str) -> JDAnalysis:
        cleaned = jd_text.strip()
        if not self.api_key:
            raise JDParserUnavailable("DeepSeek JD 解析尚未配置")
        payload = {
            "model": self.model,
            "messages": build_jd_messages(cleaned),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return JDAnalysis.model_validate(json.loads(content))
        except httpx.TimeoutException as exc:
            raise JDParserError("DeepSeek JD 解析超时，请稍后重试") from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise JDParserError("DeepSeek 未返回有效的 JD 结构") from exc
```

Post to `${deepseek_base_url.rstrip('/')}/chat/completions` with model, system/user messages, `temperature: 0`, and `response_format: {"type": "json_object"}`. Parse `choices[0].message.content` with `json.loads`, then `JDAnalysis.model_validate`. Error messages may identify configuration, timeout, or invalid response but must not include response bodies, headers, or credentials.

- [ ] **Step 3: Verify parser tests GREEN**

Run: `pytest -q tests/test_jd_parser.py -k 'parse'`

Expected: all parser tests pass.

- [ ] **Step 4: Write persistence and migration tests and verify RED**

Tests must assert:

```python
def test_position_saves_raw_and_structured_jd_atomically():
    response = client.post("/positions", headers=owner, json={
        "position_name": "平台产品负责人",
        "jd_text": "raw jd",
        "jd_analysis": valid_analysis,
    })
    assert response.json()["jd_analysis"]["title"] == "平台产品负责人"
```

Add `test_structured_jd_requires_raw_jd`, which sends an empty `jd_text` with `valid_analysis` and expects `422` with zero rows written. Add `test_init_db_adds_jd_analysis_columns_idempotently`, which runs `init_db()` twice against a legacy SQLite `positions` table and uses `sqlalchemy.inspect(engine).get_columns("positions")` to assert `jd_analysis` and `jd_analysis_version` exist exactly once.

Run: `pytest -q tests/test_jd_parser.py -k 'position or init_db'`

Expected: FAIL because position schemas and columns do not yet expose the analysis.

- [ ] **Step 5: Implement model, schema, route, and idempotent migration support**

Add nullable JSON `jd_analysis` and `String(32)` `jd_analysis_version`. Set the saved version to `"deepseek-v1"` when structured analysis is present. Reject structured analysis without non-empty raw JD using a Pydantic model validator. The parse route maps missing configuration to `503`, upstream/validation failure to `502`, and invalid request to `422`.

- [ ] **Step 6: Verify GREEN and full Python regression suite**

Run:

```bash
pytest -q tests/test_jd_parser.py
pytest -q
```

Expected: all tests pass; only documented dependency deprecation warnings may remain.

- [ ] **Step 7: Commit**

```bash
git add .env.example sql/schema.sql reloop tests/test_jd_parser.py
git commit -m "feat: add backend DeepSeek JD parsing"
```

---

### Task 3: Add The Editable JD Drawer And Match Gate

**Files:**
- Create: `frontend/src/components/JDParserDrawer.tsx`
- Create: `frontend/src/lib/jd.ts`
- Create: `tests/jd-ui.test.mjs`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `api.parseJd(jdText)`, extended `api.setPosition({ position_name, jd_text, jd_analysis })`.
- Produces: `analysisToDraft`, `draftToAnalysis`, and `positionHasParsedJd` pure helpers.
- Produces: `JDParserDrawer` controlled by `open`, `rawJd`, `status`, `analysis`, `error`, `onParse`, `onConfirm`, and `onClose`.

- [ ] **Step 1: Write pure helper and source contract tests and verify RED**

Required assertions:

```javascript
test("JD list fields round-trip one item per line", () => {
  const draft = analysisToDraft({ ...analysis, required_skills: ["Python", "SQL"] });
  assert.equal(draft.required_skills, "Python\nSQL");
  assert.deepEqual(draftToAnalysis(draft).required_skills, ["Python", "SQL"]);
});

test("only structured positions can enter matching directly", () => {
  assert.equal(positionHasParsedJd({ jd_analysis: null }), false);
  assert.equal(positionHasParsedJd({ jd_analysis: analysis }), true);
});
```

The source contract must require `role="dialog"`, `aria-modal="true"`, `解析 JD`, `确认并开始匹配`, `解析新 JD`, and must forbid `deepseek` or `apiKey` in browser storage code.

Run: `npm run test:web`

Expected: FAIL because the helpers and drawer do not exist.

- [ ] **Step 2: Implement typed API and pure form helpers**

Add the exact `JDAnalysis` shape from the backend. Normalize list drafts by splitting lines, trimming values, removing blanks, and preserving first-occurrence order.

- [ ] **Step 3: Implement the controlled drawer**

Render an overlay/backdrop and right `aside`. Input state contains raw JD; review state exposes every schema field. While parsing or saving, disable close/backdrop and commands. Render errors inside the drawer and never clear raw text from an error path.

- [ ] **Step 4: Gate dashboard match mode through parsed JD**

The segmented control handler must behave as:

```tsx
if (nextMode === "match" && !positionHasParsedJd(selected)) {
  setDrawerOpen(true);
  return;
}
setMode(nextMode);
```

Successful confirmation saves raw plus edited analysis, reloads positions, selects the returned position, closes the drawer, and then sets mode to `match`. An existing parsed position skips the drawer. Provide `解析新 JD` in match controls.

- [ ] **Step 5: Verify GREEN and compile**

Run:

```bash
npm run test:web
npm run check:web
```

Expected: all Node tests and TypeScript checks pass.

- [ ] **Step 6: Commit**

```bash
git add frontend tests/jd-ui.test.mjs
git commit -m "feat: add editable JD parsing drawer"
```

---

### Task 4: Improve Talent Ranking Presentation And Remove Subtitles

**Files:**
- Create: `frontend/src/lib/dashboard.ts`
- Create: `tests/dashboard.test.mjs`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `tests/sidebar.test.mjs`

**Interfaces:**
- Produces: `buildActivityRows(talents)` sorted descending by valid recent activity with undated records last.
- Produces: `buildMatchRows(matches, talents)` preserving backend array order.
- Produces: responsive `.focus-*` talent rows following the current visual language.

- [ ] **Step 1: Write ordering, field, and subtitle regression tests and verify RED**

```javascript
test("activity rows sort newest first and undated people last", () => {
  assert.deepEqual(buildActivityRows(talents).map((row) => row.talent.id), [2, 1, 3]);
});

test("match rows preserve backend recommendation order", () => {
  assert.deepEqual(buildMatchRows(matches, talents).map((row) => row.talent.id), [3, 1]);
});
```

Source assertions must require current experience, education, latest signal, score, and recent activity cells. They must reject all three requested subtitle strings.

Run: `npm run test:web`

Expected: FAIL because ordering remains embedded in `App.tsx`, rows lack the reference information density, and subtitles remain.

- [ ] **Step 2: Implement pure row construction**

Activity rows derive signal from `last_active_at`, use `value_score`, and place invalid/missing dates last without mutating the input. Match rows use recommendation score/reason and join optional talent details by ID without re-sorting.

- [ ] **Step 3: Render dense vertical talent rows in the current style**

Keep the existing page title, segmented control, summary command, and unframed list. Desktop rows show rank, person/company/position, years/company, education, latest signal/reason, score, recent activity, and chevron. Mobile hides rank and less important columns, preserves person/signal/score, and has no horizontal scroll. Do not introduce the reference topbar, workspace switcher, dark mode, metric cards, or nested cards.

- [ ] **Step 4: Remove the three subtitles without layout placeholders**

Call `PageHeading` without `description` on talent library, followed, and positions pages. Keep the talent detail description because it carries actual candidate context.

- [ ] **Step 5: Verify GREEN and compile**

Run:

```bash
npm run test:web
npm run check:web
```

Expected: all frontend tests and TypeScript checks pass.

- [ ] **Step 6: Commit**

```bash
git add frontend tests
git commit -m "feat: refine ranked talent presentation"
```

---

### Task 5: Build, Review, Browser Acceptance, And GitHub Push

**Files:**
- Modify: `README.md`
- Generated: `webapp/index.html`
- Generated: `webapp/assets/*`
- Delete: obsolete unhashed static application files only when replaced by the Vite build

**Interfaces:**
- Produces: reproducible React bundle served by FastAPI.
- Produces: reviewed `codex/github-align-jd` branch on `why20040822/Reloop`.

- [ ] **Step 1: Update public documentation and environment examples**

Document React/Vite source/build commands, fixed OAuth callback base, personal TTC binding, DeepSeek backend variables, `/positions/parse-jd`, structured position fields, and the fact that DeepSeek does not supply embeddings. Never include real values.

- [ ] **Step 2: Run full static and backend verification**

```bash
pytest -q
npm run test:web
npm run check:web
npm run build:web
git diff --check
```

Expected: all commands exit `0`. Restore or prevent deletion of any tracked test fixture modified by legacy tests before committing.

- [ ] **Step 3: Run same-origin API smoke tests**

Start FastAPI on an unused local port, then verify `/health`, `/`, `/auth/me`, blank JD validation, missing DeepSeek configuration, and static assets. Do not call real DeepSeek or TTC during automated verification.

- [ ] **Step 4: Run desktop and mobile browser acceptance**

At desktop and `390x844`, verify activity ordering, unparsed match drawer, parse failure preservation using a controlled backend response, editable review, successful save and match transition, direct entry for parsed positions, `解析新 JD`, subtitle removal, settings states, sidebar collapse/mobile drawer, no overlap, and no horizontal overflow. Inspect console and failed network requests.

- [ ] **Step 5: Audit the final repository and diff**

```bash
git status --short
git diff --stat reloop-github/main...HEAD
git ls-files | rg '(^|/)(\.env($|\.)|node_modules|__pycache__|.*\.db$|\.auth|coverage|dist/)'
git grep -n -I -E '(sk-[A-Za-z0-9_-]{16,}|Bearer[[:space:]]+[A-Za-z0-9._-]{16,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)'
```

Expected: no secrets, private databases, caches, dependencies, or unplanned files. Review every generated and deleted path.

- [ ] **Step 6: Obtain independent whole-branch code review and fix findings**

Review the full range from `reloop-github/main` to `HEAD` against the design spec. Fix and re-review all Critical and Important findings, then rerun affected tests and the full verification suite.

- [ ] **Step 7: Commit final generated assets and documentation**

```bash
git add README.md webapp
git commit -m "build: publish verified React workbench"
```

- [ ] **Step 8: Push and verify remote state**

```bash
git push -u reloop-github codex/github-align-jd
git ls-remote reloop-github refs/heads/codex/github-align-jd
```

Expected: the remote branch resolves to the local verified `HEAD`. Do not force-push and do not merge or deploy production.
