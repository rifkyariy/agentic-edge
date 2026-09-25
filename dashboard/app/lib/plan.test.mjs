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

test("a requeued run shows the new job, not the blocked one it replaced", () => {
  // 2026-09-24: the Jetson's E4B s2/s3 thinking jobs were blocked at 00:44,
  // requeued with a waiver at 11:27, and the cell kept reading "blocked".
  const queue = { jobs: [
    { id: "old", output_dir: "mmlupro100-e4b-s2-think", state: "blocked" },
    { id: "new", output_dir: "mmlupro100-e4b-s2-think", state: "running" },
  ] };
  const c = cell({ data: { procs: {} } }, "e4b", "s2", "on", queue);
  assert.equal(c.status, "running");
  assert.equal(c.job, "new");
});

test("once the requeued job completes, the old blocked attempt does not come back", () => {
  // 2026-09-24 evening: E4B s2/s3 thinking finished on the Jetson, and the
  // cells went back to "blocked" — the newest *live* job was last night's.
  const box = doneBox("mmlupro100-e4b-s2-think", "2026-09-24 13:40");
  const queue = { jobs: [
    { id: "old", output_dir: "mmlupro100-e4b-s2-think", state: "blocked" },
    { id: "new", output_dir: "mmlupro100-e4b-s2-think", state: "completed" },
  ] };
  const c = cell(box, "e4b", "s2", "on", queue);
  assert.equal(c.status, "done");
  assert.equal(c.score, 66);
});

// S3: little-gemma runs are mmlupro100-lg-<model>-<subset>[-think], Jetson only.
test("a little-gemma run fills its own cell and never a llama.cpp one", () => {
  const box = doneBox("mmlupro100-lg-e2b-s1");
  assert.equal(cell(box, "e2b", "s1", "off", null, "little-gemma").status, "done");
  assert.equal(cell(box, "e2b", "s1", "off").status, "pending");
});

test("a llama.cpp run never fills a little-gemma cell", () => {
  const box = doneBox("mmlupro100-e2b-s1");
  assert.equal(cell(box, "e2b", "s1", "off", null, "little-gemma").status, "pending");
});

test("a queued little-gemma thinking job shows in its own cell only", () => {
  const box = { data: { procs: {}, completed: [] } };
  const queue = { jobs: [{ state: "queued", output_dir: "mmlupro100-lg-e4b-s3-think", id: "j9" }] };
  assert.equal(cell(box, "e4b", "s3", "on", queue, "little-gemma").status, "queued");
  assert.equal(cell(box, "e4b", "s3", "on", queue).status, "pending");
});

test("little-gemma is planned for the Jetson only", () => {
  assert.deepEqual(PLAN.engines.map((e) => e.id), ["llama.cpp", "little-gemma"]);
  assert.deepEqual(PLAN.engines.find((e) => e.id === "little-gemma").boards, ["jetson"]);
});
