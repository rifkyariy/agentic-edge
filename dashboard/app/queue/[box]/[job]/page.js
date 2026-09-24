"use client";
import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQueue } from "../../../lib/queue-context";
import { usePoll } from "../../../lib/usePoll";
import { clock } from "../../../lib/format";
import StatePill from "../../../components/StatePill";
import PageHeader from "../../../components/PageHeader";

const POLL_MS = 5000;
const STREAMS = ["lm_eval", "server", "command"];

const ts = (t) => clock(t, true);

function Fingerprint({ fp }) {
  if (!fp) return null;

  // A kind with no declared baseline (raw) is not checked at all. Saying
  // "matches baseline" there would claim a check that never ran, which is the
  // exact failure this whole mechanism exists to prevent.
  if (!fp.baseline) {
    return (
      <div className="fingerprint unchecked">
        <h4>Fingerprint <i>not checked — this job kind declares no baseline</i></h4>
        <pre className="resolved">
          {fp.captured?.server_args || "(no llama-server was running)"}
        </pre>
      </div>
    );
  }

  return (
    <div className={`fingerprint ${fp.agrees ? "ok" : "drift"}`}>
      <h4>Fingerprint {fp.agrees ? "✓ matches baseline" : "⚠ drift"}
        <i> {fp.baseline}</i></h4>
      <table>
        <tbody>
          {(fp.diff || []).map((r) => (
            <tr key={r.key} className={r.ok ? "ok" : "bad"}>
              <td>{r.key}</td>
              <td>{r.ok ? "✓" : "✗"}</td>
              <td>{String(r.actual ?? "MISSING")}</td>
              <td className="sub">expected {String(r.expected)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <pre className="resolved">{fp.captured?.server_args || "(no server was running)"}</pre>
    </div>
  );
}

function LogTab({ box, job, stream, active }) {
  const [text, setText] = useState("");
  const offset = useRef(0);
  const pre = useRef(null);

  // Bumped on every reset, so a response that was in flight for the old
  // stream or job is dropped instead of appended to the new one.
  const gen = useRef(0);
  useEffect(() => { offset.current = 0; gen.current += 1; setText(""); }, [stream, job]);

  // usePoll stops in a hidden tab; the offset keeps its place, so coming back
  // fetches everything written meanwhile in one go.
  usePoll(async () => {
    if (!active) return;
    const mine = gen.current;
    const res = await fetch(
      `/api/logs?box=${box}&job=${job}&stream=${stream}&from=${offset.current}`);
    const data = await res.json();
    if (mine !== gen.current) return;
    if (data.error) { setText((t) => t || `— ${data.error}`); return; }
    if (data.text) {
      offset.current = data.offset;
      setText((t) => (t + data.text).slice(-200000));
      if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
    }
  }, POLL_MS, { deps: [box, job, stream, active] });

  if (!active) return null;
  return <pre className="logview" ref={pre}>{text || "— empty —"}</pre>;
}

export default function JobDetail({ params }) {
  const { box: boxId, job: jobId } = use(params);
  const [stream, setStream] = useState("lm_eval");
  // The app's one queue feed; the page no longer polls on its own.
  const { boxes, loaded } = useQueue();
  const box = loaded ? boxes.find((b) => b.id === boxId) || null : null;

  const job = (box?.jobs || []).find((j) => j.id === jobId);
  const evts = (box?.events || []).filter((e) => e.job === jobId);
  const fp = job?.fingerprint;

  if (!loaded) return <main><p className="sub">Loading&hellip;</p></main>;
  if (!box) {
    return (
      <main><p className="sub">No board &ldquo;{boxId}&rdquo;.{" "}
        <Link href="/queue">&larr; queue</Link></p></main>
    );
  }
  if (!job) {
    return (
      <main><p className="sub">No job {jobId} on {box.label}.{" "}
        <Link href="/queue">&larr; queue</Link></p></main>
    );
  }

  return (
    <main>
      <PageHeader eyebrow={<><Link href="/queue">Queue</Link> · {box.label}</>}
                  title={job.label}
                  sub={`${job.kind} · ${Object.entries(job.params).map(([k, v]) => `${k}=${v}`).join(" ")}`}>
        <StatePill state={job.state} />
      </PageHeader>
      {job.override_prechecks && (
        <p className="pre-error">
          Queued with the {job.override_prechecks.checks.join(", ")} check
          waived: &ldquo;{job.override_prechecks.reason}&rdquo;. Report it as
          such (AGENTS §5).
        </p>
      )}
      {job.override_fingerprint && (
        <p className="pre-error">
          This run was started with a fingerprint override. It is not
          comparable to runs that matched the baseline.
        </p>
      )}

      <section className="card">
        <div className="card-head"><h3>Timeline</h3></div>
        <ul className="timeline">
          {evts.map((e, i) => (
            <li key={i}><b>{ts(e.ts)}</b> {e.event}
              {e.detail ? <i> &mdash; {e.detail}</i> : null}</li>
          ))}
          {!evts.length && <li className="sub">No events recorded yet.</li>}
        </ul>
      </section>

      {fp && <section className="card"><Fingerprint fp={fp} /></section>}

      <section className="card">
        <div className="card-head">
          <h3>Logs</h3>
          <div className="tabs jobtabs">
            {STREAMS.map((s) => (
              <button key={s} type="button"
                      className={s === stream ? "on" : ""}
                      onClick={() => setStream(s)}>{s}</button>
            ))}
          </div>
        </div>
        {STREAMS.map((s) => (
          <LogTab key={s} box={boxId} job={jobId} stream={s} active={s === stream} />
        ))}
      </section>
    </main>
  );
}
