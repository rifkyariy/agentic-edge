// The experiment queue, so the matrix can show what is done, running and pending.
// Subsets are disjoint 100-question MMLU-Pro samples (seeds 20260918/19/20).
export const PLAN = { models: ["e2b", "e4b"], subsets: ["s1", "s2", "s3"] };

// The telemetry rerun started here. Results older than this are real, but they
// belong to the first batch (no power/thermal data), so the matrix shows them
// greyed with their date rather than letting them stand in for a current run.
export const BATCH_START = "2026-09-20 23:00";

// Run directories are mmlupro100-<model> (an early run, implicitly s1) or
// mmlupro100-<model>-<subset>. Anything else — a smoke test, a .bak — must not
// be matched into a cell, so the pattern is anchored.
const RUN_RE = /^mmlupro100-(e2b|e4b)(?:-(s\d))?$/i;
const matches = (name, model, subset) => {
  const m = RUN_RE.exec((name || "").trim());
  return !!m && m[1].toLowerCase() === model && (m[2] || "s1").toLowerCase() === subset;
};

export function cell(box, model, subset) {
  const d = box?.data;
  if (!d) return { status: "unknown" };
  // progress comes from parsing the newest lm_eval.log, which keeps reading
  // 100/100 long after the run ended — so it only means "running" while the
  // box actually has the processes to match. Without this a finished run
  // sits at a blue 100% instead of showing its score.
  const procs = d.procs || {};
  const live = procs.lm_eval || procs.run_measured || procs.telemetry;
  if (live && d.progress && matches(d.progress.run, model, subset)) {
    return { status: "running", pct: d.progress.pct, eta: d.progress.eta, run: d.progress.run };
  }
  const done = (d.completed || []).find(
    (c) => c.task === "mmlu_pro" && matches(c.run, model, subset));
  if (!done) return { status: "pending" };
  return { status: done.at >= BATCH_START ? "done" : "prior", run: done.run,
           score: done.score, stderr: done.stderr, minutes: done.minutes, at: done.at };
}
