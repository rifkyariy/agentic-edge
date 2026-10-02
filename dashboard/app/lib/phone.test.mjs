// Run with: node --test dashboard/app/lib/phone.test.mjs
// (Node 20: add --experimental-detect-module, as for the other tests here.)
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

process.env.PHONE_DIR = await mkdtemp(path.join(tmpdir(), "phone-"));
const { invalid, loadRun, phoneBox, saveRun } = await import("./phone.js");

const run = (name, status, end, qs) => ({
  run: name, model: "e2b", subset: "s1", status, host_name: "iPhone 15 Pro", os: "iOS 18.6", ram_gb: 8,
  summary: { score: 50, stderr: 5, minutes: 40 }, device: { energy_wh: 3.1 },
  timeline: [{ end_epoch: end }],
  questions: qs.map(([id, ok, got]) => ({ question_id: id, ok, got })),
});

test("the upload is checked at the trust boundary", () => {
  assert.equal(invalid(run("ok-1", "done", 1, [])), null);
  assert.match(invalid({ ...run("x", "done", 1, []), run: "../etc/passwd" }), /run name/);
  assert.match(invalid({ ...run("x", "done", 1, []), model: "e9b" }), /model/);
  assert.match(invalid({ ...run("x", "done", 1, []), subset: "s4" }), /subset/);
  assert.match(invalid([]), /object/);
  assert.match(invalid({ ...run("x", "done", 1, []), questions: null }), /arrays/);
});

test("uploaded runs come back as the iphone box, newest first, in each view", async () => {
  await saveRun(run("mmlupro-e2b-s1-old", "done", 100, [[11, true, "A"], [12, false, "B"]]));
  await saveRun(run("mmlupro-e2b-s1-new", "done", 200, [[11, false, "C"], [12, true, null]]));
  await saveRun(run("mmlupro-e2b-s1-stopped", "incomplete", 50, [[11, true, "A"]]));

  const base = await phoneBox("baseline");
  assert.equal(base.id, "iphone");
  assert.equal(base.label, "iPhone 15 Pro");
  assert.deepEqual(base.runs.map((r) => r.run), ["mmlupro-e2b-s1-new", "mmlupro-e2b-s1-old"]); // done only
  assert.equal(base.runs[0].engine, "mlx");

  const hist = await phoneBox("history");
  assert.equal(hist.runs.length, 3); // every run, the stopped one too (AGENTS §5)
  assert.equal(hist.runs.at(-1).status, "incomplete");

  const paired = await phoneBox("paired");
  assert.deepEqual(paired.runs[0].correct, { 11: 0, 12: 1 });
  assert.equal(paired.runs[0].no_answer, 1);

  assert.equal((await loadRun("mmlupro-e2b-s1-new")).summary.score, 50);
  assert.equal(await loadRun("../../etc/passwd"), null);
});
