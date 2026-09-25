// Paired accuracy comparisons, computed from per-question correctness.
//
// Both boards and both conditions answer the identical question subsets
// (AGENTS §5), so two runs are compared question by question, not score
// against score: only the questions where exactly one of them is right carry
// information, and McNemar tests whether those split evenly. This is the
// computation behind the p-values in findings/RESULTS.md §7, done live so a
// thinking run is compared the moment it finishes.

export const MODELS = ["e2b", "e4b"];
export const SUBSETS = ["s1", "s2", "s3"];
export const ALPHA = 0.05;

// Exact McNemar: a two-sided binomial test of b against c at p = 1/2. Exact
// rather than chi-squared because the discordant counts here are small (tens),
// where the approximation is poor. The pmf is built up iteratively from 2^-n,
// which stays representable for n < 1000 — far above 3 subsets x 2 models.
export function mcnemar(b, c) {
  const n = b + c;
  if (n === 0) return 1;
  const k = Math.min(b, c);
  let pmf = Math.pow(0.5, n), tail = pmf;
  for (let i = 1; i <= k; i++) {
    pmf = (pmf * (n - i + 1)) / i;
    tail += pmf;
  }
  return Math.min(1, 2 * tail);
}

// Two runs' {question_id: 0|1} maps, on the questions both answered. `missing`
// counts questions only one of them has: on matched subsets it must be zero,
// and anything else means a partial or mismatched run.
export function pair(a, b) {
  const t = { n: 0, both: 0, neither: 0, aOnly: 0, bOnly: 0, missing: 0 };
  for (const [q, x] of Object.entries(a)) {
    if (!(q in b)) { t.missing++; continue; }
    const y = b[q];
    t.n++;
    if (x && y) t.both++;
    else if (!x && !y) t.neither++;
    else if (x) t.aOnly++;
    else t.bOnly++;
  }
  for (const q of Object.keys(b)) if (!(q in a)) t.missing++;
  return t;
}

const add = (s, t) => {
  for (const k of Object.keys(t)) s[k] = (s[k] || 0) + t[k];
  return s;
};

function finish(t) {
  if (!t.n) return null;
  const p = mcnemar(t.aOnly, t.bOnly);
  const aAcc = (100 * (t.both + t.aOnly)) / t.n;
  const bAcc = (100 * (t.both + t.bOnly)) / t.n;
  const sig = p < ALPHA;
  return { ...t, p, aAcc, bAcc, delta: bAcc - aAcc, sig,
           winner: !sig ? null : t.bOnly > t.aOnly ? "b" : "a" };
}

// Every finished run, indexed box:engine:model:subset:thinking. `boxes` is the
// /api/compare answer: [{id, ok, runs: [{engine, model, subset, thinking,
// done, correct, no_answer}]}]. A run without an engine comes from a board
// whose run_detail.py predates S3, and was served by llama.cpp.
export function index(boxes) {
  const ready = {}, waiting = {};
  for (const box of boxes) {
    for (const r of box.runs || []) {
      const key = `${box.id}:${r.engine || "llama.cpp"}:${r.model}:${r.subset}:${r.thinking}`;
      if (r.done && r.correct) ready[key] = r;
      else waiting[key] = r;
    }
  }
  return { ready, waiting };
}

// One comparison: side A against side B, per subset and pooled over the
// subsets both sides have finished. A subset with only one side finished is
// named in `pending` rather than silently left out.
function compare(ready, label, keyA, keyB, models) {
  const rows = [];
  const pool = { n: 0, both: 0, neither: 0, aOnly: 0, bOnly: 0, missing: 0 };
  const pending = [], noAnswer = { a: 0, b: 0 };
  let subsets = 0;
  for (const m of models) {
    for (const s of SUBSETS) {
      const a = ready[keyA(m, s)], b = ready[keyB(m, s)];
      if (!a || !b) {
        if (a || b) pending.push(`${m.toUpperCase()} ${s}`);
        continue;
      }
      const t = pair(a.correct, b.correct);
      add(pool, t);
      subsets++;
      noAnswer.a += a.no_answer || 0;
      noAnswer.b += b.no_answer || 0;
      rows.push({ model: m, subset: s, ...finish(t) });
    }
  }
  return { label, rows, pending, subsets, noAnswer, pooled: finish(pool) };
}

const DEVICE = [["pi", "Pi 5"], ["jetson", "Orin Nano"]];
const LLAMA = "llama.cpp", LG = "little-gemma";

// The questions the paper asks of MMLU-Pro:
//   board:    Pi against Orin, same model and condition, both on llama.cpp.
//   thinking: baseline against thinking-on, same board, engine and model.
//   engine:   llama.cpp against little-gemma (S3), on the Orin, same model
//             and condition — the Pi has no little-gemma runs.
// Each is given per model and pooled over both models.
export function comparisons(boxes) {
  const { ready, waiting } = index(boxes);
  const k = (box, t, e = LLAMA) => (m, s) => `${box}:${e}:${m}:${s}:${t}`;
  const scopes = [...MODELS.map((m) => [m.toUpperCase(), [m]]), ["both models", MODELS]];

  const board = ["off", "on"].map((t) => ({
    condition: t,
    a: "Pi 5", b: "Orin Nano",
    groups: scopes.map(([label, ms]) => compare(ready, label, k("pi", t), k("jetson", t), ms)),
  }));
  const thinking = [...DEVICE.map(([id, name]) => [id, name, LLAMA]),
                    ["jetson", "Orin Nano", LG]].map(([id, name, e]) => ({
    board: id, engine: e,
    a: `${name} baseline`, b: `${name} thinking`,
    groups: scopes.map(([label, ms]) => compare(ready, label, k(id, "off", e), k(id, "on", e), ms)),
  }));
  const engine = ["off", "on"].map((t) => ({
    condition: t,
    a: LLAMA, b: LG,
    groups: scopes.map(([label, ms]) =>
      compare(ready, label, k("jetson", t, LLAMA), k("jetson", t, LG), ms)),
  }));
  return { board, thinking, engine, running: Object.keys(waiting) };
}
