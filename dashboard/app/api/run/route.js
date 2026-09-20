import { exec } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(exec);

// Per box: how to reach it, and which python has `datasets` (needed to map
// answers back to questions while a run is still in flight).
const BOXES = {
  pi: { host: "MITLAB-EDGE", py: "~/Research/eval-venv/bin/python3",
        script: "~/Research/agentic-edge/benchmark/run_detail.py" },
  jetson: { host: "MITLAB-JETSON", py: "~/venvs/eval/bin/python3",
            script: "~/research/agentic-edge/benchmark/run_detail.py" },
};

export const dynamic = "force-dynamic";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const box = BOXES[searchParams.get("box")];
  const runName = searchParams.get("run");
  if (!box || !runName || !/^[\w.-]+$/.test(runName)) {
    return Response.json({ error: "bad box or run" }, { status: 400 });
  }
  const cmd = `ssh -o BatchMode=yes -o ConnectTimeout=6 ${box.host} '${box.py} ${box.script} --run ${runName}'`;
  try {
    const { stdout } = await run(cmd, { timeout: 120000, maxBuffer: 32 * 1024 * 1024 });
    return Response.json(JSON.parse(stdout.slice(stdout.indexOf("{"))));
  } catch (e) {
    return Response.json({ error: (e.stderr || e.message || "failed").toString().slice(0, 400) },
                         { status: 502 });
  }
}
