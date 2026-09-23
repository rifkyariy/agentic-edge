import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, byId, SSH, hint } from "../../lib/hosts";

const run = promisify(execFile);

export const dynamic = "force-dynamic";

// execFile, not exec: the local shell never sees this, so the JSON payload
// cannot be re-parsed on its way out. Only the REMOTE shell needs quoting,
// which is the one level shq handles.
const SSH_ARGS = SSH.trim().split(/\s+/);
const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

// Everything goes through queue_ctl.py, which prints one JSON object and exits
// 0, or prints {"error": ...} and exits 1 (AGENTS §7 — no ad-hoc ssh here).
async function ctl(box, args, timeout = 30000) {
  const remote = `${box.py} ${box.repo}/benchmark/queue_ctl.py ${args.join(" ")}`;
  try {
    const { stdout } = await run("ssh", [...SSH_ARGS, box.host, remote],
                                 { timeout, maxBuffer: 8 * 1024 * 1024 });
    return { ok: true, data: JSON.parse(stdout) };
  } catch (e) {
    // A handled error still prints JSON on stdout and exits 1, so prefer it
    // over the raw stderr: "e9b is not one of e2b, e4b" beats "exit code 1".
    let parsed = null;
    try { parsed = JSON.parse(e.stdout || ""); } catch { /* not ours */ }
    const error = parsed?.error
      || (e.stderr || e.message || "failed").toString().trim().slice(0, 400);
    return { ok: false, error, hint: hint(error, box) };
  }
}

// ?describe=1 returns each board's job-kind registry. It is static per board,
// so the page fetches it once on mount rather than shipping it with every 5s
// status poll.
export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const describe = searchParams.get("describe") === "1";
  const boxes = await Promise.all(HOSTS.map(async (h) => {
    const r = await ctl(h, [describe ? "--describe" : "--status"]);
    return r.ok ? { ...h, ok: true, ...r.data }
                : { ...h, ok: false, error: r.error, hint: r.hint, jobs: [] };
  }));
  return Response.json({ ts: Date.now(), boxes });
}

export async function POST(request) {
  const { searchParams } = new URL(request.url);
  const preflight = searchParams.get("preflight") === "1";
  const body = await request.json().catch(() => null);
  const box = byId(body?.box);
  if (!box || !(body?.kind || (Array.isArray(body?.jobs) && body.jobs.length))) {
    return Response.json({ error: "bad box or kind" }, { status: 400 });
  }
  // A batch ({jobs: [...]}) goes out as one queue_ctl call — one ssh round
  // trip, and queue_ctl checks the jobs against each other as well.
  const one = (j) => ({
    kind: j.kind, params: j.params || {}, not_before: j.not_before || null,
    ...(j.override ? { override: { ...j.override, by: "dashboard" } } : {}),
    by: "dashboard",
  });
  const payload = JSON.stringify(Array.isArray(body.jobs)
    ? { jobs: body.jobs.map(one) } : one(body));
  const r = await ctl(box, [preflight ? "--preflight" : "--add", shq(payload)]);
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error, hint: r.hint }, { status: 400 });
}

export async function DELETE(request) {
  const { searchParams } = new URL(request.url);
  const box = byId(searchParams.get("box"));
  const job = searchParams.get("job");
  if (!box || !job || !/^[\w.-]+$/.test(job)) {
    return Response.json({ error: "bad box or job" }, { status: 400 });
  }
  const r = await ctl(box, ["--cancel", job]);
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error }, { status: 400 });
}
