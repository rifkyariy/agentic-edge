import { exec } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(exec);

// Each box runs the same probe; ssh config supplies user and host.
const HOSTS = [
  { id: "pi", label: "Raspberry Pi 5", sub: "CPU only · Cortex-A76 ×4",
    host: "MITLAB-EDGE", probe: "~/Research/agentic-edge/benchmark/probe_status.py" },
  { id: "jetson", label: "Jetson Orin Nano", sub: "CUDA · 15W mode",
    host: "MITLAB-JETSON", probe: "~/research/agentic-edge/benchmark/probe_status.py" },
];

async function probe(h) {
  const cmd = `ssh -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new ${h.host} 'python3 ${h.probe}'`;
  try {
    const { stdout } = await run(cmd, { timeout: 20000, maxBuffer: 4 * 1024 * 1024 });
    return { ...h, ok: true, data: JSON.parse(stdout) };
  } catch (e) {
    return { ...h, ok: false, error: (e.stderr || e.message || "unreachable").toString().slice(0, 300) };
  }
}

export const dynamic = "force-dynamic";

export async function GET() {
  const boxes = await Promise.all(HOSTS.map(probe));
  return Response.json({ ts: Date.now(), boxes });
}
