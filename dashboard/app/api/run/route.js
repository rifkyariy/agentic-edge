import { exec } from "node:child_process";
import { promisify } from "node:util";
import { byId, SSH, hint } from "../../lib/hosts";

const run = promisify(exec);

export const dynamic = "force-dynamic";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const box = byId(searchParams.get("box"));
  const runName = searchParams.get("run");
  // failed/ and archive/ hold past runs the history page opens; nothing else
  // may carry a slash, and a leading \w rules out "." and "..".
  if (!box || !runName || !/^(?:(?:failed|archive)\/)?\w[\w.-]*$/.test(runName)) {
    return Response.json({ error: "bad box or run" }, { status: 400 });
  }
  // run_detail.py needs `datasets` to map answers to questions mid-run, so it
  // goes through the eval venv rather than the system python the probe uses.
  const cmd = `ssh ${SSH} ${box.host} '${box.py} ${box.repo}/benchmark/run_detail.py --run ${runName}'`;
  try {
    const { stdout } = await run(cmd, { timeout: 120000, maxBuffer: 32 * 1024 * 1024 });
    return Response.json(JSON.parse(stdout.slice(stdout.indexOf("{"))));
  } catch (e) {
    const error = (e.stderr || e.message || "failed").toString().trim().slice(0, 400);
    return Response.json({ error, hint: hint(error, box) }, { status: 502 });
  }
}
