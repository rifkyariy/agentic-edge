import { byId } from "../../lib/hosts";
import { onBoard } from "../../lib/ssh";

export const dynamic = "force-dynamic";

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
  const r = await onBoard(box, "queue_ctl.py",
                          ["--log", job, "--stream", stream, "--from", String(from)],
                          { python: "venv", maxBuffer: 16 << 20 });
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error, hint: r.hint }, { status: 502 });
}
