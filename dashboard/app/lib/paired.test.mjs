// Run with: node --test dashboard/app/lib/paired.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { mcnemar, pair, comparisons } from "./paired.js";

const r2 = (x) => Math.round(x * 100) / 100;

test("exact McNemar reproduces the hand-computed p-values in RESULTS.md §7", () => {
  assert.equal(r2(mcnemar(19, 22)), 0.76);   // E2B Pi only / Orin only
  assert.equal(r2(mcnemar(12, 13)), 1.0);    // E4B
  assert.equal(r2(mcnemar(31, 35)), 0.71);   // pooled n=600
});

test("McNemar is symmetric, bounded and detects a lopsided split", () => {
  assert.equal(mcnemar(3, 17), mcnemar(17, 3));
  assert.equal(mcnemar(0, 0), 1);
  assert.ok(mcnemar(3, 17) < 0.01);
  assert.ok(mcnemar(300, 300) <= 1);
});

test("pairing counts only shared questions and reports the rest", () => {
  const t = pair({ 1: 1, 2: 1, 3: 0, 4: 0, 9: 1 }, { 1: 1, 2: 0, 3: 1, 4: 0, 8: 1 });
  assert.deepEqual(t, { n: 4, both: 1, neither: 1, aOnly: 1, bOnly: 1, missing: 2 });
});

const run = (model, subset, thinking, correct, done = true) =>
  ({ model, subset, thinking, done, correct, no_answer: 0 });
const q = (bits) => Object.fromEntries([...bits].map((b, i) => [i, Number(b)]));

test("pools only subsets both sides finished, and names the others", () => {
  const boxes = [
    { id: "pi", runs: [run("e2b", "s1", "off", q("1100")), run("e2b", "s2", "off", q("1111"))] },
    { id: "jetson", runs: [run("e2b", "s1", "off", q("1010")),
                           run("e2b", "s2", "off", null, false)] },
  ];
  const e2b = comparisons(boxes).board[0].groups[0];
  assert.equal(e2b.subsets, 1);
  assert.deepEqual(e2b.pending, ["E2B s2"]);
  assert.equal(e2b.pooled.n, 4);
  assert.equal(e2b.pooled.aAcc, 50);
  assert.equal(e2b.pooled.sig, false);
  assert.equal(e2b.pooled.winner, null);
});

test("thinking is compared on the same board, never across boards", () => {
  const boxes = [
    { id: "pi", runs: [run("e4b", "s1", "off", q("0000")), run("e4b", "s1", "on", q("1111"))] },
    { id: "jetson", runs: [run("e4b", "s1", "on", q("0000"))] },
  ];
  const { thinking } = comparisons(boxes);
  const pi = thinking.find((t) => t.board === "pi").groups[1];
  assert.equal(pi.pooled.bAcc - pi.pooled.aAcc, 100);
  const jet = thinking.find((t) => t.board === "jetson").groups[1];
  assert.equal(jet.pooled, null);            // no Jetson baseline in this data
  assert.deepEqual(jet.pending, ["E4B s1"]);
});
