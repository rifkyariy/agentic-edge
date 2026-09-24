import { exec } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, SSH, hint } from "../../lib/hosts";
import { shared } from "../../lib/shared";

const run = promisify(exec);

export const dynamic = "force-dynamic";

// Per-question correctness of every current MMLU-Pro run on each board, for
// the paired tests on /compare. On demand through run_detail.py like the other
// heavy views (AGENTS §7). Stdlib only on the board: it reads samples files.
async function paired(h) {
  const cmd = `ssh ${SSH} ${h.host} 'python3 ${h.repo}/benchmark/run_detail.py --paired'`;
  try {
    const { stdout } = await run(cmd, { timeout: 60000, maxBuffer: 16 * 1024 * 1024 });
    return { ...h, ok: true, ...JSON.parse(stdout.slice(stdout.indexOf("{"))) };
  } catch (e) {
    const error = (e.stderr || e.message || "unreachable").toString().trim().slice(0, 300);
    // The board answers but its run_detail.py predates --paired: that is a
    // deploy away, not a network problem.
    const stale = /unrecognized arguments: --paired/.test(error);
    return { ...h, ok: false, runs: [], stale,
             error: stale ? "run_detail.py on this board has no --paired yet" : error,
             hint: stale ? "commit, then run benchmark/deploy.sh from the Mac" : hint(error, h) };
  }
}

// A run takes hours; a minute of staleness costs nothing and keeps several
// open compare tabs from each reading every samples file on both boards.
const TTL_MS = 60000;

export async function GET() {
  return Response.json(await shared("compare", TTL_MS, async () => ({
    ts: Date.now(), boxes: await Promise.all(HOSTS.map(paired)),
  })));
}
