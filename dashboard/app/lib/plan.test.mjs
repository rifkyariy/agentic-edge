// Run with: node --test dashboard/app/lib/plan.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { cell, PLAN } from "./plan.js";

const doneBox = (run, at = "2026-09-21 10:00") => ({
  data: { procs: {}, completed: [{ task: "mmlu_pro", run, score: 66, stderr: 4.7, at }] },
});

test("plan covers both thinking conditions", () => {
  assert.deepEqual(PLAN.thinking, ["off", "on"]);
});

test("a thinking-on run is matched to its cell", () => {
  const box = doneBox("mmlupro100-e4b-s2-think");
  assert.equal(cell(box, "e4b", "s2", "on").status, "done");
});

test("a thinking-on run does not fill the thinking-off cell", () => {
  const box = doneBox("mmlupro100-e4b-s2-think");
  assert.equal(cell(box, "e4b", "s2", "off").status, "pending");
});

test("a baseline run does not fill the thinking-on cell", () => {
  const box = doneBox("mmlupro100-e4b-s2");
  assert.equal(cell(box, "e4b", "s2", "on").status, "pending");
});

test("the queue is authoritative about what is running", () => {
  const box = { data: { procs: {}, completed: [] } };
  const queue = { jobs: [{ state: "running", output_dir: "mmlupro100-e4b-s2", id: "j1" }] };
  const c = cell(box, "e4b", "s2", "off", queue);
  assert.equal(c.status, "running");
  assert.equal(c.job, "j1");
});

test("a blocked job is shown as blocked, not pending", () => {
  const box = { data: { procs: {}, completed: [] } };
  const queue = { jobs: [{ state: "blocked", output_dir: "mmlupro100-e4b-s2",
                           id: "j1", note: "reasoning: expected off, got None" }] };
  const c = cell(box, "e4b", "s2", "off", queue);
  assert.equal(c.status, "blocked");
  assert.match(c.note, /reasoning/);
});

test("without a queue the process heuristic still works", () => {
  const box = {
    data: { procs: { lm_eval: 1 },
            progress: { run: "mmlupro100-e4b-s2", pct: 41, eta: "1h 2m" },
            completed: [] },
  };
  assert.equal(cell(box, "e4b", "s2", "off").status, "running");
});

test("a completed job in the queue does not mask the finished score", () => {
  // Once a job is done the queue stops being the authority: the score comes
  // from lm-eval's own results, which is what the matrix shows.
  const box = doneBox("mmlupro100-e4b-s2");
  const queue = { jobs: [{ state: "completed", output_dir: "mmlupro100-e4b-s2", id: "j1" }] };
  const c = cell(box, "e4b", "s2", "off", queue);
  assert.equal(c.status, "done");
  assert.equal(c.score, 66);
});

test("existing three-argument calls still work", () => {
  // app/page.js calls cell(box, m, s) — the new parameters must default.
  const box = doneBox("mmlupro100-e2b-s1");
  assert.equal(cell(box, "e2b", "s1").status, "done");
});
