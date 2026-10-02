import { invalid, MAX_BYTES, saveRun } from "../../lib/phone";
import { invalidate } from "../../lib/shared";

export const dynamic = "force-dynamic";

// The iPhone app's upload: one run, run_detail.py --run's shape (see lib/phone.js).
// Guarded by API_TOKEN like every /api route (middleware.js).
export async function POST(request) {
  const text = await request.text();
  if (text.length > MAX_BYTES) {
    return Response.json({ error: "run too large", hint: `limit is ${MAX_BYTES >> 20} MB` }, { status: 413 });
  }
  let run;
  try { run = JSON.parse(text); } catch { run = null; }
  const why = invalid(run);
  if (why) return Response.json({ error: why }, { status: 400 });
  await saveRun(run);
  invalidate("compare");
  invalidate("status"); // a live upload should show on the next Monitor poll, not 4 s later
  return Response.json({ ok: true, run: run.run });
}
