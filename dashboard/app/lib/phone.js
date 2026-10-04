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
  // Live snapshots are fire-and-forget, so one sent before the final upload can
  // land after it. A finished run is never put back to "running".
  const prev = r.status === "running" ? await loadRun(r.run) : null;
  if (prev && prev.status !== "running") return false;
  // write-then-rename, so a reader never sees half a file
  await writeFile(`${file}.tmp`, JSON.stringify({ ...r, received_at: new Date().toISOString() }));
  await rename(`${file}.tmp`, file);
  return true;
}

// The matrix and the Monitor card name runs the way the boards do,
// mmlupro100-<engine>-<model>-<subset>; that alias means the newest upload for the cell.
// engine is mlx, or mlx-oq4 for E4B quantized small enough for an 8 GB iPhone: a different
// quantization of the same model, so it gets its own cells and never stands in for mlx.
const ENGINES = ["mlx", "mlx-oq4"];
const engineOf = (r) => (ENGINES.includes(r.engine) ? r.engine : "mlx");
const CELL_RE = /^mmlupro100-(mlx|mlx-oq4)-(e2b|e4b)-(s\d)$/;
export const cellName = (r) => `mmlupro100-${engineOf(r)}-${r.model}-${r.subset}`;

export async function loadRun(name) {
  const cellHit = CELL_RE.exec(name || "");
  if (cellHit) {
    return (await all()).find((r) => engineOf(r) === cellHit[1] && r.model === cellHit[2] && r.subset === cellHit[3]) ?? null;
  }
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
  run: r.run, engine: engineOf(r), model: r.model, subset: r.subset, thinking: "off",
  done: done(r), score: done(r) ? r.summary?.score ?? null : null,
  stderr: r.summary?.stderr ?? null, minutes: r.summary?.minutes ?? null,
  at: r.received_at?.slice(0, 16).replace("T", " "), device: r.device ?? null,
});

// tqdm-style, like the boards' progress: "12:34" or "1:02:03".
const hms = (s) => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
};
// A run the phone stopped reporting on is not "running": the app uploads every 10 questions
// (~4 min for E2B), so 15 min of silence means it died, was stopped, or lost the network.
export const STALE_S = 15 * 60;
export const TOTAL = 100; // every subset is 100 questions (findings/stdbench)

/** The phone's device status. It has no ssh to probe, so its uploads are the only
 * sign of life: running (a live snapshot inside STALE_S), lost (a run that stopped
 * uploading mid-way), idle (its last run ended), or never (nothing uploaded). */
export function statusOf(runs, now) {
  const latest = runs.reduce((a, r) => (!a || Date.parse(r.received_at) > Date.parse(a.received_at) ? r : a), null);
  if (!latest) return { state: "never", age_s: null };
  const age = Math.round(now - Date.parse(latest.received_at) / 1000);
  const state = latest.status !== "running" ? "idle" : age < STALE_S ? "running" : "lost";
  return { state, age_s: age, run: latest.run, name: latest.host_name ?? null };
}

export async function phoneStatus() {
  return { id: PHONE.id, ...statusOf(await all(), Date.now() / 1000) };
}

/** probe_status.py's shape, from the uploads: what the Monitor card and matrix read. */
function probe(runs, now) {
  const latest = runs[0];
  const live = runs.find((r) => r.status === "running" && now - Date.parse(r.received_at) / 1000 < STALE_S);
  const tl = live?.timeline || [];
  const elapsed = tl.length ? tl.at(-1).end_epoch - tl[0].start_epoch : 0;
  const per = tl.length ? elapsed / tl.length : 0;
  const t = ((live ?? latest)?.telemetry || []).at(-1) || {}; // the run in progress, if any, is "now"
  const seen = new Set();
  const completed = runs.filter(done).filter((r) => !seen.has(cellName(r)) && seen.add(cellName(r)))
    .map((r) => ({ run: cellName(r), task: "mmlu_pro", score: r.summary?.score ?? null, stderr: r.summary?.stderr ?? null,
                   minutes: r.summary?.minutes ?? null, at: r.received_at?.slice(0, 16).replace("T", " ") }));
  return {
    host: latest?.host || "iphone", ts: now,
    cpu_pct: t.cpu ?? null, power_w: null, temp_c: null, gpu_pct: null, throttled: null,
    mem_used_mb: t.rss ?? null, mem_total_mb: latest?.ram_gb ? latest.ram_gb * 1024 : null,
    procs: live ? { lm_eval: { model: live.model } } : {},
    progress: live ? { run: cellName(live), pct: Math.round((100 * tl.length) / TOTAL), done: tl.length, total: TOTAL,
                       elapsed: hms(elapsed), eta: hms((TOTAL - tl.length) * per), s_per_item: per,
                       age_s: Math.round(now - Date.parse(live.received_at) / 1000) } : null,
    measured: live ? { dir: live.run, samples: live.telemetry?.length ?? 0 }
      : latest && done(latest) ? { dir: latest.run, summary: latest.device } : null,
    completed, disks: {},
    // What the phone measures instead of rails and temperatures (Telemetry.swift):
    // the app's CPU (% of one core, can pass 100), its memory footprint, iOS's
    // thermal state (0 nominal .. 3 critical) and the battery level.
    phone: {
      cpu_pct: t.cpu ?? null, footprint_mb: t.rss ?? null,
      thermal: t.thermal ?? null, battery_pct: t.battery ?? null,
      ram_gb: latest?.ram_gb ?? null, os: latest?.os ?? null, model_id: latest?.host ?? null,
      upload_age_s: latest?.received_at ? Math.round(now - Date.parse(latest.received_at) / 1000) : null,
      state: statusOf(runs, now).state,
    },
  };
}

/** The iPhone as a box, in the shape each board route returns for `view`. */
export async function phoneBox(view) {
  const runs = await all();
  const latest = runs[0];
  const box = { ...PHONE, ok: true,
                label: latest?.host_name || PHONE.label,
                sub: latest ? `MLX · ${latest.os ?? "iOS"} · ${latest.ram_gb ?? "?"} GB` : PHONE.sub };
  if (view === "status") return { ...box, data: probe(runs, Date.now() / 1000) };
  if (view === "baseline") return { ...box, runs: runs.filter(done).map(row), failed: [] };
  if (view === "history") {
    return { ...box, runs: runs.map((r) => ({
      // A run that went silent mid-way (killed, stopped, out of network) is reported, not "running".
      ...row(r), place: "current",
      status: r.status === "running" && Date.now() / 1000 - Date.parse(r.received_at) / 1000 >= STALE_S ? "incomplete" : r.status, tag: null, task: "mmlu_pro",
      ended: r.timeline?.at(-1)?.end_epoch ?? null })) };
  }
  if (view === "paired") {
    return { ...box, runs: runs.map((r) => {
      const correct = Object.fromEntries((r.questions || []).filter((q) => q.question_id != null)
        .map((q) => [String(q.question_id), q.ok ? 1 : 0]));
      return { run: r.run, engine: engineOf(r), model: r.model, subset: r.subset, thinking: "off", done: done(r),
               correct: Object.keys(correct).length ? correct : null,
               no_answer: (r.questions || []).filter((q) => !q.got).length };
    }) };
  }
  return box;
}
