import { exec } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, SSH, hint } from "../../lib/hosts";
import { shared } from "../../lib/shared";

const run = promisify(exec);

async function probe(h) {
  const cmd = `ssh ${SSH} ${h.host} 'python3 ${h.repo}/benchmark/probe_status.py'`;
  try {
    const { stdout } = await run(cmd, { timeout: 20000, maxBuffer: 4 * 1024 * 1024 });
    return { ...h, ok: true, data: JSON.parse(stdout) };
  } catch (e) {
    const error = (e.stderr || e.message || "unreachable").toString().trim().slice(0, 300);
    return { ...h, ok: false, error, hint: hint(error, h) };
  }
}

export const dynamic = "force-dynamic";

// Tabs poll every 5 s; a slightly shorter ttl keeps one tab's ticks from
// landing on its own previous answer, while any other tab shares it.
const TTL_MS = 4000;

export async function GET() {
  return Response.json(await shared("status", TTL_MS, async () => ({
    ts: Date.now(), boxes: await Promise.all(HOSTS.map(probe)),
  })));
}
