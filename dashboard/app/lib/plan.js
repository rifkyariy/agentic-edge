// The experiment queue, so the matrix can show what is done, running and pending.
// Subsets are disjoint 100-question MMLU-Pro samples (seeds 20260918/19/20).
export const PLAN = { models: ["e2b", "e4b"], subsets: ["s1", "s2", "s3"],
                      thinking: ["off", "on"] };

// The telemetry rerun started here. Results older than this are real, but they
// belong to the first batch (no power/thermal data), so the matrix shows them
// greyed with their date rather than letting them stand in for a current run.
export const BATCH_START = "2026-09-20 23:00";

// Run directories are mmlupro100-<model> (an early run, implicitly s1) or
// mmlupro100-<model>-<subset>, with -think appended for the reasoning row
// (std_mmlupro.sh sets OUT=$OUT-think). Anything else — a smoke test, a .bak —
// must not be matched into a cell, so the pattern stays anchored.
const RUN_RE = /^mmlupro100-(e2b|e4b)(?:-(s\d))?(-think)?$/i;
const matches = (name, model, subset, thinking = "off") => {
  const m = RUN_RE.exec((name || "").trim());
  if (!m) return false;
  return m[1].toLowerCase() === model
      && (m[2] || "s1").toLowerCase() === subset
      && (m[3] ? "on" : "off") === thinking;
};

// States in which the queue, not the log, is the authority on a cell.
const LIVE = ["queued", "prechecking", "fingerprinting", "running", "blocked"];

export function cell(box, model, subset, thinking = "off", queue = null) {
  const d = box?.data;

  // The queue knows what it started; ask it before guessing. Without a daemon
  // (an older board, or one where the unit is down) fall through to the
  // process heuristic below so the matrix still renders. A finished job is
  // deliberately not matched here: once it is done the score comes from
  // lm-eval's own results, which is what the matrix shows.
  const job = (queue?.jobs || []).find(
    (j) => matches(j.output_dir, model, subset, thinking) && LIVE.includes(j.state));
  if (job) {
    if (job.state === "blocked") {
      return { status: "blocked", job: job.id, note: job.note, run: job.output_dir };
    }
    if (job.state === "queued") {
      return { status: "queued", job: job.id, run: job.output_dir,
               notBefore: job.not_before_epoch };
    }
    return { status: "running", job: job.id, run: job.output_dir,
             pct: d?.progress && matches(d.progress.run, model, subset, thinking)
                  ? d.progress.pct : null,
             eta: d?.progress?.eta };
  }

  if (!d) return { status: "unknown" };

  // progress comes from parsing the newest lm_eval.log, which keeps reading
  // 100/100 long after the run ended — so it only means "running" while the
  // box actually has the processes to match. Without this a finished run
  // sits at a blue 100% instead of showing its score.
  const procs = d.procs || {};
  const live = procs.lm_eval || procs.run_measured || procs.telemetry;
  if (live && d.progress && matches(d.progress.run, model, subset, thinking)) {
    return { status: "running", pct: d.progress.pct, eta: d.progress.eta,
             run: d.progress.run };
  }
  const done = (d.completed || []).find(
    (c) => c.task === "mmlu_pro" && matches(c.run, model, subset, thinking));
  if (!done) return { status: "pending" };
  return { status: done.at >= BATCH_START ? "done" : "prior", run: done.run,
           score: done.score, stderr: done.stderr, minutes: done.minutes, at: done.at };
}
