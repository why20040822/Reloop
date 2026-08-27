# RE:LOOP Local Ranking Demo Data Design

## Goal

Populate the local `guest_shared` pool with deterministic fictional data that makes the difference between activity ordering and position-match ordering immediately visible in the existing frontend.

## Scope And Isolation

- Write only to the local SQLite database at `/Users/shishen/Downloads/RE-LOOP-source 3/reloop.local.db`.
- Use the existing `guest_shared` owner so the current unsigned browser session can view the data.
- Mark every talent with a `source_id` beginning `demo-ranking-v1-` and a matching marker in `source_payload`.
- Create one position named `AI 产品经理（演示）` with raw JD plus validated `jd_analysis`, allowing the match view to open without calling DeepSeek.
- Use fictional names and omit phone numbers and email addresses.
- Do not modify frontend or backend source code, production data, OAuth settings, or external services.

## Dataset

Create ten talents with intentionally different signals:

- High activity but low position match, such as sales and HR profiles.
- High position match but older activity, such as senior AI and B2B SaaS product profiles.
- Medium profiles that exercise skills, years, education, title, and missing-activity fallbacks.
- At least one followed talent and at least one talent without a valid activity timestamp.

The demonstration JD targets an AI product manager with at least five years of experience, a bachelor's degree or above, B2B SaaS and AI product experience, SQL/data analysis skills, and cross-functional delivery experience.

## Expected Behavior

### Activity View

The frontend sorts by valid `last_active_at` descending. The newest activity appears first, invalid or missing activity appears last, and equal timestamps preserve API source order.

### Match View

Selecting `岗位匹配` uses the saved demo position and invokes the existing recommendation engine. The engine returns a quick local preview and may later replace it with a final result. The frontend preserves the backend recommendation order and displays match score and contact reason.

The two views must produce visibly different top candidates. Actual match order is recorded after running the engine rather than hard-coded in the design.

## Safety And Repeatability

- Seeding is idempotent by `(owner_user_id, source_id)` for talents and by the exact demo position name.
- Re-running updates the same demo records instead of adding duplicates.
- Any future cleanup must target only the `demo-ranking-v1-` source prefix, the exact demo position name, and recommendation runs produced for that position.
- Existing non-demo records remain untouched.

## Verification

- Confirm `GET /auth/me` reports a pool count of ten or more after seeding.
- Confirm the homepage activity list shows all demo rows in descending activity order.
- Enter match mode and wait for the recommendation result to finish.
- Record the actual top five activity and match orders with their visible scores.
- Verify the orders differ, the demo position is selected, no horizontal overflow appears, and the browser console contains no new errors or warnings.
