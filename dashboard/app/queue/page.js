"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

const POLL_MS = 5000;

const fmtTime = (epoch) =>
  epoch ? new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;

function JobForm({ box, onQueued }) {
  const kinds = box.kinds || {};
  const [kind, setKind] = useState("mmlupro");
  const [params, setParams] = useState({});
  const [notBefore, setNotBefore] = useState("");
  const [pre, setPre] = useState(null);
  const [busy, setBusy] = useState(false);

  const spec = kinds[kind];

  // Reset parameters to each kind's defaults when the kind changes, so the
  // form can never post a leftover parameter the new kind does not declare.
  useEffect(() => {
    if (!spec) return;
    const next = {};
    for (const [name, rule] of Object.entries(spec.params)) {
      next[name] = rule.default ?? rule.enum?.[0] ?? "";
    }
    setParams(next);
    setPre(null);
  }, [kind, box.id]);                       // eslint-disable-line react-hooks/exhaustive-deps

  const send = useCallback(async (preflight) => {
    setBusy(true);
    try {
      const res = await fetch(`/api/queue${preflight ? "?preflight=1" : ""}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ box: box.id, kind, params,
                               not_before: notBefore || null }),
      });
      const data = await res.json();
      if (!res.ok) { setPre({ error: data.error, hint: data.hint }); return; }
      if (preflight) setPre(data);
      else { setPre(null); onQueued(); }
    } finally { setBusy(false); }
  }, [box.id, kind, params, notBefore, onQueued]);

  // Preflight on every change: the answer is cheap and the point is to see the
  // memory and stale-directory checks before committing three hours.
  useEffect(() => {
    if (!spec || !Object.keys(params).length) return;
    const t = setTimeout(() => send(true), 250);
    return () => clearTimeout(t);
  }, [params, notBefore]);                  // eslint-disable-line react-hooks/exhaustive-deps

  if (!spec) return <p className="sub">This board reported no job kinds.</p>;

  return (
    <div className="jobform">
      <label>kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.keys(kinds).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </label>

      {Object.entries(spec.params).map(([name, rule]) => (
        <label key={name}>{name}
          {rule.enum ? (
            <select value={params[name] ?? ""}
                    onChange={(e) => setParams({ ...params, [name]: e.target.value })}>
              {rule.enum.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input value={params[name] ?? ""}
                   placeholder={rule.pattern ? "letters, digits, . _ -" : ""}
                   onChange={(e) => setParams({ ...params, [name]: e.target.value })} />
          )}
        </label>
      ))}

      <label>not before
        <input value={notBefore} placeholder="HH:MM" size={6}
               onChange={(e) => setNotBefore(e.target.value)} />
        <i className="sub"> {box.timezone} (board time)</i>
      </label>

      {pre?.error && (
        <p className="pre-error"><b>{pre.error}</b>{pre.hint ? <><br />{pre.hint}</> : null}</p>
      )}

      {pre?.prechecks && (
        <ul className="prechecks">
          {pre.prechecks.map((c) => (
            <li key={c.name} className={c.ok ? "ok" : "bad"}>
              <b>{c.ok ? "✓" : "✗"} {c.name}</b> {c.detail}
            </li>
          ))}
        </ul>
      )}

      {pre?.resolved && <pre className="resolved">{pre.resolved.command}</pre>}

      <button type="button" disabled={busy || (pre && pre.ok === false)}
              onClick={() => send(false)}>
        {pre && pre.ok === false ? "prechecks failed" : "queue this run"}
      </button>
    </div>
  );
}

function QueueList({ box, onChange }) {
  const cancel = async (id) => {
    await fetch(`/api/queue?box=${box.id}&job=${id}`, { method: "DELETE" });
    onChange();
  };
  const jobs = (box.jobs || []).filter((j) => j.state !== "cancelled");
  if (!jobs.length) return <p className="sub">Nothing queued.</p>;
  return (
    <table className="queue-table">
      <thead><tr><th>job</th><th>state</th><th>when</th><th /></tr></thead>
      <tbody>
        {jobs.slice().reverse().map((j) => (
          <tr key={j.id} className={`state-${j.state}`}>
            <td>
              <Link href={`/queue/${box.id}/${j.id}`}>{j.label}</Link>
              {j.note ? <i className="note"> {j.note}</i> : null}
            </td>
            <td>{j.state}</td>
            <td>{fmtTime(j.started || j.not_before_epoch || j.created) || "—"}</td>
            <td>{j.state === "queued"
              ? <button type="button" onClick={() => cancel(j.id)}>cancel</button>
              : null}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function QueuePage() {
  const [boxes, setBoxes] = useState([]);
  const [specs, setSpecs] = useState({});   // board id -> {kinds, timezone}

  const load = useCallback(async () => {
    const res = await fetch("/api/queue");
    const data = await res.json();
    setBoxes(data.boxes || []);
  }, []);

  // The registry does not change while the page is open, so it is fetched once
  // rather than on every poll.
  useEffect(() => {
    (async () => {
      const res = await fetch("/api/queue?describe=1");
      const data = await res.json();
      const byBox = {};
      for (const b of data.boxes || []) {
        if (b.ok) byBox[b.id] = { kinds: b.kinds, timezone: b.timezone };
      }
      setSpecs(byBox);
    })();
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  return (
    <main>
      <header className="card-head">
        <h2>Queue</h2>
        <p className="sub">
          One job per board at a time. Each run is prechecked for memory and a
          stale output directory, and its serving flags are diffed against the
          declared baseline before lm-eval starts.{" "}
          <Link href="/">&larr; live monitor</Link>
        </p>
      </header>

      {boxes.map((box) => (
        <section key={box.id} className="card">
          <div className="card-head">
            <h3>{box.label}</h3>
            {box.ok
              ? <p className="sub">{box.daemon_alive
                  ? "queue daemon running" : "⚠ queue daemon is not running"}</p>
              : <p className="pre-error"><b>{box.error}</b>{box.hint ? <><br />{box.hint}</> : null}</p>}
          </div>
          {box.ok && <JobForm box={{ ...box, ...(specs[box.id] || {}) }} onQueued={load} />}
          {box.ok && <QueueList box={box} onChange={load} />}
        </section>
      ))}
    </main>
  );
}
