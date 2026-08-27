import assert from "node:assert/strict";
import test from "node:test";

import { scrubTtcCallbackHash } from "../frontend/src/lib/ttcCallback.ts";

test("TTC callback scrub preserves the static entry pathname and removes only hash query data", () => {
  assert.equal(
    scrubTtcCallbackHash("/reloop/", "#/ttc/callback?token=short-lived-token&state=ok"),
    "/reloop/#/ttc/callback",
  );
});
