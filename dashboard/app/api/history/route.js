import { exec } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, SSH, hint } from "../../lib/hosts";

const run = promisify(exec);

export const dynamic = "force-dynamic";

// Every run each board has on disk — current, failed and superseded. Heavier
// than /api/status and fetched on demand, so it goes through run_detail.py
// like the other on-demand views (AGENTS §7), not a new ad-hoc ssh command.
async function history(h) {
  const cmd = `ssh ${SSH} ${h.host} '${h.py} ${h.repo}/benchmark/run_detail.py --history'`;
  try {
    const { stdout } = await run(cmd, { timeout: 60000, maxBuffer: 8 * 1024 * 1024 });
    return { ...h, ok: true, ...JSON.parse(stdout.slice(stdout.indexOf("{"))) };
  } catch (e) {
    const error = (e.stderr || e.message || "unreachable").toString().trim().slice(0, 300);
    return { ...h, ok: false, error, hint: hint(error, h), runs: [] };
  }
}

export async function GET() {
  const boxes = await Promise.all(HOSTS.map(history));
  return Response.json({ ts: Date.now(), boxes });
}
