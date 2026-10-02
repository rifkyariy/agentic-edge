import { byId } from "../../lib/hosts";
import { onBoard } from "../../lib/ssh";
import { loadRun } from "../../lib/phone";

export const dynamic = "force-dynamic";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const runName = searchParams.get("run");
  // The iPhone's runs are uploaded files on the Mac, already in run_detail.py's shape.
  if (searchParams.get("box") === "iphone") {
    const r = runName && await loadRun(runName);
    return r ? Response.json(r) : Response.json({ error: "no such iPhone run" }, { status: 404 });
  }
  const box = byId(searchParams.get("box"));
  // failed/ and archive/ hold past runs the history page opens; nothing else
  // may carry a slash, and a leading \w rules out "." and "..".
  if (!box || !runName || !/^(?:(?:failed|archive)\/)?\w[\w.-]*$/.test(runName)) {
    return Response.json({ error: "bad box or run" }, { status: 400 });
  }
  // run_detail.py needs `datasets` to map answers to questions mid-run, so it
  // goes through the eval venv rather than the system python the probe uses.
  const r = await onBoard(box, "run_detail.py", ["--run", runName],
                          { python: "venv", timeout: 120000, maxBuffer: 32 << 20 });
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error, hint: r.hint }, { status: 502 });
}
