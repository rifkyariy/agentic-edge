// The experiment queue, so the matrix can show what is done, running and pending.
// Subsets are disjoint 100-question MMLU-Pro samples (seeds 20260918/19/20).
// Engines are the S3 axis: little-gemma runs the same task as llama.cpp with
// only the engine swapped (job kind mmlupro-lg), and only on the Jetson —
// its fast path is CUDA, so the Pi has no little-gemma rows at all.
export const PLAN = { models: ["e2b", "e4b"], subsets: ["s1", "s2", "s3"],
                      thinking: ["off", "on"],
                      engines: [{ id: "llama.cpp", boards: ["pi", "jetson"] },
                                { id: "little-gemma", short: "LG", boards: ["jetson"] }] };

// The telemetry rerun started here. Results older than this are real, but they
// belong to the first batch (no power/thermal data), so the matrix shows them
// greyed with their date rather than letting them stand in for a current run.
export const BATCH_START = "2026-09-20 23:00";

// Run directories are mmlupro100-<model> (an early run, implicitly s1) or
// mmlupro100-<model>-<subset>, with -think appended for the reasoning row
// (std_mmlupro.sh sets OUT=$OUT-think) and lg- before the model for a
// little-gemma run. Anything else — a smoke test, a .bak — must not be matched
// into a cell, so the pattern stays anchored.
const RUN_RE = /^mmlupro100-(lg-)?(e2b|e4b)(?:-(s\d))?(-think)?$/i;
const matches = (name, model, subset, thinking = "off", engine = "llama.cpp") => {
  const m = RUN_RE.exec((name || "").trim());
  if (!m) return false;
  return (m[1] ? "little-gemma" : "llama.cpp") === engine
      && m[2].toLowerCase() === model
      && (m[3] || "s1").toLowerCase() === subset
      && (m[4] ? "on" : "off") === thinking;
};

// States in which the queue, not the log, is the authority on a cell.
const LIVE = ["queued", "prechecking", "fingerprinting", "running", "blocked"];

export function cell(box, model, subset, thinking = "off", queue = null,
                     engine = "llama.cpp") {
  const d = box?.data;
  const is = (name) => matches(name, model, subset, thinking, engine);

  // The queue knows what it started; ask it before guessing. Without a daemon
  // (an older board, or one where the unit is down) fall through to the
  // process heuristic below so the matrix still renders. A finished job is
  // deliberately not matched here: once it is done the score comes from
  // lm-eval's own results, which is what the matrix shows.
  // The newest job for this run decides, whatever its state. A blocked job
  // that was requeued stays in queue.json as history: taking the first match
  // showed it over the requeued run, and taking the newest *live* match
  // brought it back once the requeued run completed. A newest job that has
  // finished means the queue has nothing to say; the results do.
  const newest = [...(queue?.jobs || [])].reverse().find(
    (j) => is(j.output_dir));
  const job = newest && LIVE.includes(newest.state) ? newest : null;
  if (job) {
    if (job.state === "blocked") {
      return { status: "blocked", job: job.id, note: job.note, run: job.output_dir };
    }
    if (job.state === "queued") {
      return { status: "queued", job: job.id, run: job.output_dir,
               notBefore: job.not_before_epoch };
    }
    return { status: "running", job: job.id, run: job.output_dir,
             pct: d?.progress && is(d.progress.run)
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
  if (live && d.progress && is(d.progress.run)) {
    return { status: "running", pct: d.progress.pct, eta: d.progress.eta,
             run: d.progress.run };
  }
  const done = (d.completed || []).find(
    (c) => c.task === "mmlu_pro" && is(c.run));
  if (!done) return { status: "pending" };
  return { status: done.at >= BATCH_START ? "done" : "prior", run: done.run,
           score: done.score, stderr: done.stderr, minutes: done.minutes, at: done.at };
}
