import { byId } from "../../lib/hosts";
import { onBoard, onEveryBoard, shq } from "../../lib/ssh";
import { shared, invalidate } from "../../lib/shared";

export const dynamic = "force-dynamic";

// Everything goes through queue_ctl.py, which prints one JSON object and exits
// 0, or prints {"error": ...} and exits 1 (AGENTS §7 — no ad-hoc ssh here).
const ctl = (box, args) => onBoard(box, "queue_ctl.py", args, { python: "venv" });

// ?describe=1 returns each board's job-kind registry. It is static per board,
// so the page fetches it once on mount rather than shipping it with every 5s
// status poll.
export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const describe = searchParams.get("describe") === "1";
  // Every page polls this (monitor, queue, job detail), so it is shared across
  // tabs like /api/status. The registry only changes on a deploy.
  const key = describe ? "queue:describe" : "queue:status";
  const ttl = describe ? 60000 : 4000;
  return Response.json(await shared(key, ttl, async () => ({
    ts: Date.now(),
    boxes: await onEveryBoard("queue_ctl.py", [describe ? "--describe" : "--status"],
                              { python: "venv" }, { jobs: [] }),
  })));
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
  if (!preflight) invalidate("queue:status");
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
  invalidate("queue:status");
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error }, { status: 400 });
}
