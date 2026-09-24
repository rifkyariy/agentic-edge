import { onEveryBoard } from "../../lib/ssh";
import { shared } from "../../lib/shared";

export const dynamic = "force-dynamic";

// Tabs poll every 5 s; a slightly shorter ttl keeps one tab's ticks from
// landing on its own previous answer, while any other tab shares it.
const TTL_MS = 4000;

export async function GET() {
  return Response.json(await shared("status", TTL_MS, async () => ({
    ts: Date.now(),
    boxes: await onEveryBoard("probe_status.py", [], { timeout: 20000, maxBuffer: 4 << 20, wrap: "data" }),
  })));
}
