// The iPhone arm (benchmark/apps/ios) has no ssh and no queue: the app POSTs each
// run to /api/phone when it ends, and the API serves it as a third box, "iphone",
// next to the boards. One JSON file per run on the Mac, in run_detail.py --run's
// shape, so /api/run and the run sheet need nothing new. Re-uploading a run
// (after attaching power data) overwrites its file.
import { mkdir, readdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const DIR = () => process.env.PHONE_DIR?.trim() || path.join(process.cwd(), "data", "phone");

export const PHONE = { id: "iphone", label: "iPhone", sub: "MLX · Metal", host: "app upload",
                       repo: "benchmark/apps/ios" };
export const RUN_RE = /^\w[\w.-]*$/;
export const MAX_BYTES = 32 << 20;

// Trust boundary: whatever arrives here is written to the Mac's disk and served
// back to every client. Only the fields the pages read are checked; the rest is
// the app's own record and is passed through.
export function invalid(r) {
  if (!r || typeof r !== "object" || Array.isArray(r)) return "body must be a JSON object";
  if (typeof r.run !== "string" || !RUN_RE.test(r.run) || r.run.length > 120) return "bad run name";
  if (!["e2b", "e4b"].includes(r.model)) return "model must be e2b or e4b";
  if (!["s1", "s2", "s3"].includes(r.subset)) return "subset must be s1, s2 or s3";
  if (!Array.isArray(r.questions) || !Array.isArray(r.timeline)) return "questions and timeline must be arrays";
  return null;
}

export async function saveRun(r) {
  await mkdir(DIR(), { recursive: true });
  const file = path.join(DIR(), `${r.run}.json`);
  // write-then-rename, so a reader never sees half a file
  await writeFile(`${file}.tmp`, JSON.stringify({ ...r, received_at: new Date().toISOString() }));
  await rename(`${file}.tmp`, file);
}

export async function loadRun(name) {
  if (!RUN_RE.test(name)) return null;
  try {
    return JSON.parse(await readFile(path.join(DIR(), `${name}.json`), "utf8"));
  } catch {
    return null;
  }
}

// ponytail: reads every file per call — fine for tens of runs; index if it reaches thousands.
async function all() {
  let names = [];
  try { names = (await readdir(DIR())).filter((f) => f.endsWith(".json")); } catch { /* none yet */ }
  const runs = (await Promise.all(names.map((f) => loadRun(f.slice(0, -5))))).filter(Boolean);
  const ended = (r) => r.timeline?.at(-1)?.end_epoch ?? 0;
  return runs.sort((a, b) => ended(b) - ended(a)); // newest first: canonical() keeps the first per cell
}

const done = (r) => r.status === "done";
const row = (r) => ({
  run: r.run, engine: "mlx", model: r.model, subset: r.subset, thinking: "off",
  done: done(r), score: done(r) ? r.summary?.score ?? null : null,
  stderr: r.summary?.stderr ?? null, minutes: r.summary?.minutes ?? null,
  at: r.received_at?.slice(0, 16).replace("T", " "), device: r.device ?? null,
});

/** The iPhone as a box, in the shape each board route returns for `view`. */
export async function phoneBox(view) {
  const runs = await all();
  const latest = runs[0];
  const box = { ...PHONE, ok: true,
                label: latest?.host_name || PHONE.label,
                sub: latest ? `MLX · ${latest.os ?? "iOS"} · ${latest.ram_gb ?? "?"} GB` : PHONE.sub };
  if (view === "baseline") return { ...box, runs: runs.filter(done).map(row), failed: [] };
  if (view === "history") {
    return { ...box, runs: runs.map((r) => ({
      ...row(r), place: "current", status: r.status, tag: null, task: "mmlu_pro",
      ended: r.timeline?.at(-1)?.end_epoch ?? null })) };
  }
  if (view === "paired") {
    return { ...box, runs: runs.map((r) => {
      const correct = Object.fromEntries((r.questions || []).filter((q) => q.question_id != null)
        .map((q) => [String(q.question_id), q.ok ? 1 : 0]));
      return { run: r.run, engine: "mlx", model: r.model, subset: r.subset, thinking: "off", done: done(r),
               correct: Object.keys(correct).length ? correct : null,
               no_answer: (r.questions || []).filter((q) => !q.got).length };
    }) };
  }
  return box;
}
