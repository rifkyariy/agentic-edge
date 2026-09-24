import { onEveryBoard } from "../../lib/ssh";
import { shared } from "../../lib/shared";

export const dynamic = "force-dynamic";

// A run takes hours; a minute of staleness costs nothing and keeps several
// open compare tabs from each reading every samples file on both boards.
const TTL_MS = 60000;

// Per-question correctness of every current MMLU-Pro run on each board, for
// the paired tests on /compare. On demand through run_detail.py like the other
// heavy views (AGENTS §7). Stdlib only on the board: it reads samples files.
export async function GET() {
  return Response.json(await shared("compare", TTL_MS, async () => {
    const boxes = await onEveryBoard("run_detail.py", ["--paired"],
                                     { timeout: 60000, maxBuffer: 16 << 20 }, { runs: [] });
    // A board that answers but whose run_detail.py predates --paired is a
    // deploy away, not a network problem.
    for (const b of boxes) {
      if (!b.ok && /unrecognized arguments: --paired/.test(b.error)) {
        Object.assign(b, { stale: true,
          error: "run_detail.py on this board has no --paired yet",
          hint: "commit, then run benchmark/deploy.sh from the Mac" });
      }
    }
    return { ts: Date.now(), boxes };
  }));
}
