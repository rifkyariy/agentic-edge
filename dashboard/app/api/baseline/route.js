import { exec } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, SSH, hint } from "../../lib/hosts";

const run = promisify(exec);

// Heavier than /api/status and not polled — every finished run on a box, with
// the device cost that produced it. run_detail.py is the documented home for
// on-demand work like this (AGENTS §7), so nothing new is sshed ad hoc.
async function baseline(h) {
  const cmd = `ssh ${SSH} ${h.host} '${h.py} ${h.repo}/benchmark/run_detail.py --baseline'`;
  try {
    const { stdout } = await run(cmd, { timeout: 60000, maxBuffer: 8 * 1024 * 1024 });
    return { ...h, ok: true, ...JSON.parse(stdout.slice(stdout.indexOf("{"))) };
  } catch (e) {
    const error = (e.stderr || e.message || "unreachable").toString().trim().slice(0, 300);
    return { ...h, ok: false, error, hint: hint(error, h), runs: [] };
  }
}

export const dynamic = "force-dynamic";

export async function GET() {
  const boxes = await Promise.all(HOSTS.map(baseline));
  return Response.json({ ts: Date.now(), boxes });
}
