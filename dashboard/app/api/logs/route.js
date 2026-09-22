import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { byId, SSH, hint } from "../../lib/hosts";

const run = promisify(execFile);

export const dynamic = "force-dynamic";

const SSH_ARGS = SSH.trim().split(/\s+/);
const STREAMS = new Set(["command", "lm_eval", "server"]);

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const box = byId(searchParams.get("box"));
  const job = searchParams.get("job");
  const stream = searchParams.get("stream");
  const from = Number.parseInt(searchParams.get("from") || "0", 10) || 0;

  if (!box || !job || !/^[\w.-]+$/.test(job) || !STREAMS.has(stream)) {
    return Response.json({ error: "bad box, job or stream" }, { status: 400 });
  }

  // Offset-based: a three-hour lm_eval.log is not re-sent on every poll.
  const remote = `${box.py} ${box.repo}/benchmark/queue_ctl.py `
               + `--log ${job} --stream ${stream} --from ${from}`;
  try {
    const { stdout } = await run("ssh", [...SSH_ARGS, box.host, remote],
                                 { timeout: 30000, maxBuffer: 16 * 1024 * 1024 });
    return Response.json(JSON.parse(stdout));
  } catch (e) {
    let parsed = null;
    try { parsed = JSON.parse(e.stdout || ""); } catch { /* not ours */ }
    const error = parsed?.error
      || (e.stderr || e.message || "failed").toString().trim().slice(0, 300);
    return Response.json({ error, hint: hint(error, box) }, { status: 502 });
  }
}
