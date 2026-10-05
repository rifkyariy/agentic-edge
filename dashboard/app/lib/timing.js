// How long each finished MMLU-Pro run took, for the Compare page's time table.
// Read from /api/history, which lists every run on disk; only current runs
// whose name parses as a grid cell count, so smoke tests, tagged experiments
// and failed or superseded runs never stand in for a real one.
import { parseRun } from "./plan.js";

// One entry per (box, engine, model, subset, thinking). The Pi still has an
// early mmlupro100-<model> directory, implicitly s1; an explicit -s1 wins.
export function collectRuns(boxes) {
  const by = {};
  for (const box of boxes || []) {
    for (const r of box.runs || []) {
      if (r.place !== "current" || r.minutes == null || r.score == null) continue;
      const p = parseRun(r.run);
      if (!p) continue;
      const k = [box.id, p.engine, p.model, p.subset, p.thinking].join(":");
      if (by[k] && (by[k].explicitSubset || !p.explicitSubset)) continue;
      by[k] = { box: box.id, ...p, minutes: r.minutes, run: r.run };
    }
  }
  return Object.values(by);
}
