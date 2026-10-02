import { onEveryBoard } from "../../lib/ssh";
import { phoneBox } from "../../lib/phone";

export const dynamic = "force-dynamic";

// Every run each board has on disk — current, failed and superseded. Heavier
// than /api/status and fetched on demand, so it goes through run_detail.py
// like the other on-demand views (AGENTS §7), not a new ad-hoc ssh command.
export async function GET() {
  const boxes = [...await onEveryBoard("run_detail.py", ["--history"],
                                       { python: "venv", timeout: 60000 }, { runs: [] }),
                 await phoneBox("history")];
  return Response.json({ ts: Date.now(), boxes });
}
