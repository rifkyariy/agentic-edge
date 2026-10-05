// Run with: node --test dashboard/app/lib/timing.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { collectRuns } from "./timing.js";

const run = (name, minutes, extra = {}) =>
  ({ run: name, place: "current", minutes, score: 50, ...extra });

test("only current grid runs with a time are kept", () => {
  const rows = collectRuns([{ id: "pi", runs: [
    run("mmlupro100-e2b-s1", 181),
    run("mmlupro100-e2b-s3-letter-r6", 9),
    run("failed/mmlupro100-e2b-s2", 10, { place: "failed" }),
    run("mmlupro100-e4b-s1", null),
  ] }]);
  assert.deepEqual(rows.map((r) => r.run), ["mmlupro100-e2b-s1"]);
});

test("an explicit -s1 wins over the early subset-less directory, either order", () => {
  for (const order of [[0, 1], [1, 0]]) {
    const runs = [run("mmlupro100-e2b", 200), run("mmlupro100-e2b-s1", 181)];
    const rows = collectRuns([{ id: "pi", runs: order.map((i) => runs[i]) }]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].minutes, 181);
  }
});
