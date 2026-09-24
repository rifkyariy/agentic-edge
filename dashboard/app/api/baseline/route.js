import { onEveryBoard } from "../../lib/ssh";

export const dynamic = "force-dynamic";

// Heavier than /api/status and not polled — every finished run on a box, with
// the device cost that produced it. run_detail.py is the documented home for
// on-demand work like this (AGENTS §7), so nothing new is sshed ad hoc.
export async function GET() {
  const boxes = await onEveryBoard("run_detail.py", ["--baseline"],
                                   { python: "venv", timeout: 60000 }, { runs: [] });
  return Response.json({ ts: Date.now(), boxes });
}
