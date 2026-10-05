import { onEveryBoard } from "../../lib/ssh";
import { phoneBox } from "../../lib/phone";
import { isForeign } from "../../lib/plan";

export const dynamic = "force-dynamic";

// Every run each board has on disk — current, failed and superseded. Heavier
// than /api/status and fetched on demand, so it goes through run_detail.py
// like the other on-demand views (AGENTS §7), not a new ad-hoc ssh command.
export async function GET() {
  const boards = await onEveryBoard("run_detail.py", ["--history"],
                                    { python: "venv", timeout: 60000 }, { runs: [] });
  // Other projects' runs (edge-grader) share stdbench/; they are not ours.
  const boxes = [...boards.map((b) => (Array.isArray(b.runs)
                   ? { ...b, runs: b.runs.filter((r) => !isForeign(r.run)) } : b)),
                 await phoneBox("history")];
  return Response.json({ ts: Date.now(), boxes });
}
