"use client";
import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const POLL_MS = 5000;
const STREAMS = ["lm_eval", "server", "command"];

const ts = (t) => new Date(t * 1000).toLocaleTimeString([], {
  hour: "2-digit", minute: "2-digit", second: "2-digit" });

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

  useEffect(() => { offset.current = 0; setText(""); }, [stream, job]);

  useEffect(() => {
    if (!active) return undefined;
    let stop = false;
    const tick = async () => {
      const res = await fetch(
        `/api/logs?box=${box}&job=${job}&stream=${stream}&from=${offset.current}`);
      const data = await res.json();
      if (stop) return;
      if (data.error) { setText((t) => t || `— ${data.error}`); return; }
      if (data.text) {
        offset.current = data.offset;
        setText((t) => (t + data.text).slice(-200000));
        if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
      }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, [box, job, stream, active]);

  if (!active) return null;
  return <pre className="logview" ref={pre}>{text || "— empty —"}</pre>;
}

export default function JobDetail({ params }) {
  const { box: boxId, job: jobId } = use(params);
  const [box, setBox] = useState(null);
  const [stream, setStream] = useState("lm_eval");

  const load = useCallback(async () => {
    const res = await fetch("/api/queue");
    const data = await res.json();
    setBox((data.boxes || []).find((b) => b.id === boxId) || null);
  }, [boxId]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const job = (box?.jobs || []).find((j) => j.id === jobId);
  const evts = (box?.events || []).filter((e) => e.job === jobId);
  const fp = job?.fingerprint;

  if (!box) return <main><p className="sub">Loading&hellip;</p></main>;
  if (!job) {
    return (
      <main><p className="sub">No job {jobId} on {box.label}.{" "}
        <Link href="/queue">&larr; queue</Link></p></main>
    );
  }

  return (
    <main>
      <header className="card-head">
        <h2>{job.label} <i className={`state-pill state-${job.state}`}>{job.state}</i></h2>
        <p className="sub">{box.label} &middot; {job.kind} &middot;{" "}
          {Object.entries(job.params).map(([k, v]) => `${k}=${v}`).join(" ")}{" "}
          <Link href="/queue">&larr; queue</Link></p>
        {job.override_fingerprint && (
          <p className="pre-error">
            This run was started with a fingerprint override. It is not
            comparable to runs that matched the baseline.
          </p>
        )}
      </header>

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
          <div className="tabs">
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
