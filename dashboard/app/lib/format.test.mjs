// Run with: node --test dashboard/app/lib/format.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { timeTicks } from "./format.js";

const MIN = 60000, T = Date.UTC(2026, 9, 4, 12, 0, 0);

test("time ticks are unique, inside the domain, on whole minutes", () => {
  for (const [a, b] of [[T, T + 20 * MIN], [T + 7000, T + 3 * MIN + 1000], [T - MIN, T + 1], [T, T + 30000], [T + 1, T + 2]]) {
    const ticks = timeTicks([a, b]);
    assert.equal(new Set(ticks).size, ticks.length, `duplicate tick for ${a}-${b}`);
    assert.ok(ticks.every((t) => t >= a && t <= b));
    assert.ok(ticks.length >= 1 && ticks.length <= 5);
  }
  assert.deepEqual(timeTicks([T, T + 20 * MIN]), [T, T + 5 * MIN, T + 10 * MIN, T + 15 * MIN, T + 20 * MIN].filter((_, i, a) => a.length <= 5));
});
