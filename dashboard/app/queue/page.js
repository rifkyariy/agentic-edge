"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

const POLL_MS = 5000;

const fmtTime = (epoch) =>
  epoch ? new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;

// Batches go out in rounds: every model and reasoning setting for s1, then
// s2, then s3. A complete paired slice (n=100 on both boards) exists after the
// first round, instead of after every subset of the first model.
const ROUND_ORDER = ["subset", "thinking", "model"];

// Every combination of the selected values, outermost parameter first.
function expand(spec, sel, text) {
  const names = Object.keys(spec.params).sort((a, b) => {
    const ia = ROUND_ORDER.indexOf(a), ib = ROUND_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  let combos = [{}];
  for (const name of names) {
    const values = spec.params[name].enum ? (sel[name] || []) : [text[name] ?? ""];
    combos = combos.flatMap((c) => values.map((v) => ({ ...c, [name]: v })));
  }
  return combos;
}

const MARK = (c) => (c.deferred ? "⏳" : c.ok ? "✓" : "✗");

function JobForm({ box, onQueued }) {
  const kinds = box.kinds || {};
  const [kind, setKind] = useState("mmlupro");
  const [sel, setSel] = useState({});        // enum param -> [selected values]
  const [text, setText] = useState({});      // free-text param -> value
  const [notBefore, setNotBefore] = useState("");
  const [waive, setWaive] = useState(false);
  const [reason, setReason] = useState("");
  const [pre, setPre] = useState(null);
  const [busy, setBusy] = useState(false);

  const spec = kinds[kind];

  // Reset to each kind's defaults when the kind changes, so the form can never
  // post a leftover parameter the new kind does not declare. `spec` is in the
  // key because the registry arrives in its own request: when the status poll
  // won that race, the form used to stay empty and never preflight.
  useEffect(() => {
    if (!spec) return;
    const s = {}, t = {};
    for (const [name, rule] of Object.entries(spec.params)) {
      if (rule.enum) s[name] = [rule.default ?? rule.enum[0]];
      else t[name] = "";
    }
    setSel(s); setText(t); setPre(null); setWaive(false); setReason("");
  }, [kind, box.id, Boolean(spec)]);        // eslint-disable-line react-hooks/exhaustive-deps

  const combos = spec ? expand(spec, sel, text) : [];
  const override = waive && reason.trim().length >= 8
    ? { checks: ["memory"], reason: reason.trim() } : null;

  const send = useCallback(async (preflight) => {
    if (!combos.length) return;
    setBusy(true);
    try {
      const jobs = combos.map((params) => ({
        kind, params, not_before: notBefore || null,
        ...(override ? { override } : {}) }));
      const res = await fetch(`/api/queue${preflight ? "?preflight=1" : ""}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ box: box.id, jobs }),
      });
      const data = await res.json();
      if (!res.ok) { setPre({ error: data.error, hint: data.hint }); return; }
      if (preflight) setPre(data);
      else { setPre(null); onQueued(); }
    } finally { setBusy(false); }
  }, [box.id, kind, JSON.stringify(combos), notBefore, JSON.stringify(override), onQueued]); // eslint-disable-line react-hooks/exhaustive-deps

  // One preflight for the whole batch, one ssh call: cheap, and the point is
  // to see every check before committing a night of board time.
  useEffect(() => {
    if (!spec || !combos.length) { setPre(null); return undefined; }
    const t = setTimeout(() => send(true), 250);
    return () => clearTimeout(t);
  }, [JSON.stringify(combos), notBefore, JSON.stringify(override)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!box.kinds) return <p className="sub">Loading this board&rsquo;s job kinds&hellip;</p>;
  if (!spec) return <p className="sub">This board reported no job kinds.</p>;

  const toggle = (name, v) => {
    const cur = sel[name] || [];
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
    // keep the declared order, and never let a parameter go empty
    if (next.length) setSel({ ...sel, [name]: spec.params[name].enum.filter((x) => next.includes(x)) });
  };

  const results = pre?.results || [];
  const memoryOnly = results.some((r) => !r.ok)
    && results.every((r) => r.ok || r.blocking.every((b) => b === "memory"));
  const waivable = memoryOnly || waive;
  const single = results.length === 1 ? results[0] : null;
  const allOk = pre?.ok === true;
  const n = combos.length;

  return (
    <div className="jobform">
      <div className="fields">
        <label>kind
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.keys(kinds).map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>

        {Object.entries(spec.params).map(([name, rule]) => rule.enum ? (
          <div key={name} className="field-chips">
            <span>{name}</span>
            <div className="chips" role="group" aria-label={name}>
              {rule.enum.map((v) => (
                <button key={v} type="button" aria-pressed={(sel[name] || []).includes(v)}
                        onClick={() => toggle(name, v)}>{v}</button>
              ))}
            </div>
          </div>
        ) : (
          <label key={name}>{name}
            <input value={text[name] ?? ""}
                   placeholder={rule.pattern ? "letters, digits, . _ -" : ""}
                   onChange={(e) => setText({ ...text, [name]: e.target.value })} />
          </label>
        ))}

        <label>not before <i className="tz">{box.timezone} · board time</i>
          <input value={notBefore} placeholder="HH:MM" size={6}
                 onChange={(e) => setNotBefore(e.target.value)} />
        </label>
      </div>

      {n > 1 && (
        <p className="batch-note">
          {n} runs, queued in rounds — every model and setting for one subset
          before the next — and run one at a time.
        </p>
      )}

      {pre?.error && (
        <p className="pre-error"><b>{pre.error}</b>{pre.hint ? <><br />{pre.hint}</> : null}</p>
      )}

      {single && (
        <ul className="prechecks">
          {single.prechecks.map((c) => (
            <li key={c.name} className={c.deferred ? "later" : c.ok ? "ok" : "bad"}>
              <i className="mark">{MARK(c)}</i>
              <b>{c.name}</b><span>{c.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {results.length > 1 && (
        <ol className="batch">
          {results.map((r) => (
            <li key={r.resolved.label} className={r.ok ? "ok" : "bad"}>
              <b>{r.resolved.label}</b>
              <span className="batch-checks">
                {r.prechecks.map((c) => (
                  <i key={c.name} className={c.deferred ? "later" : c.ok ? "ok" : "bad"}
                     title={c.detail}>{MARK(c)} {c.name}</i>
                ))}
              </span>
              {!r.ok && <em>{r.prechecks.filter((c) => r.blocking.includes(c.name))
                                .map((c) => c.detail).join("; ")}</em>}
            </li>
          ))}
        </ol>
      )}

      {results.some((r) => r.prechecks.some((c) => c.deferred)) && (
        <p className="batch-note">⏳ checked when that job starts: the board is busy
          now, so its memory and idleness today say nothing about then.</p>
      )}

      {waivable && (
        <div className="waive">
          <label className="waive-toggle">
            <input type="checkbox" checked={waive} onChange={(e) => setWaive(e.target.checked)} />
            run anyway — waive the memory check
          </label>
          {waive && (
            <input className="waive-reason" value={reason}
                   placeholder="why this is safe (recorded with the run)"
                   onChange={(e) => setReason(e.target.value)} />
          )}
          <p className="sub">Only memory can be waived. The reason is stored on
            the job and in its timeline, and the run is marked as overridden for
            good (AGENTS §5).</p>
        </div>
      )}

      {single?.resolved && (
        <div className="resolved"><span>resolves to</span>
          <pre>{single.resolved.command}</pre></div>
      )}

      <div className="submit-row">
        {results.length > 0 && (
          <span className={`check-sum ${allOk ? "ok" : "bad"}`}>
            {results.filter((r) => r.ok).length}/{results.length} ready
          </span>
        )}
        <button type="button" className="primary"
                disabled={busy || !pre || !allOk || !!pre.error || (waive && !override)}
                onClick={() => send(false)}>
          {!pre ? "checking…" : pre.error ? "fix the request first"
            : waive && !override ? "give a reason to waive"
            : !allOk ? "prechecks failed"
            : n > 1 ? `queue ${n} runs` : "queue this run"}
        </button>
      </div>
    </div>
  );
}

function QueueList({ box, onChange }) {
  const cancel = async (id) => {
    await fetch(`/api/queue?box=${box.id}&job=${id}`, { method: "DELETE" });
    onChange();
  };
  const jobs = (box.jobs || []).filter((j) => j.state !== "cancelled");
  if (!jobs.length) return <p className="empty">Nothing queued on this board.</p>;
  return (
    <div className="table-wrap">
    <table className="queue-table">
      <thead><tr><th>job</th><th>state</th><th>when</th><th /></tr></thead>
      <tbody>
        {jobs.slice().reverse().map((j) => (
          <tr key={j.id} className={`state-${j.state}`}>
            <td>
              <Link href={`/queue/${box.id}/${j.id}`}>{j.label}</Link>
              {j.note ? <i className="note"> {j.note}</i> : null}
            </td>
            <td><i className={`state-pill state-${j.state}`}>{j.state}</i></td>
            <td>{fmtTime(j.started || j.not_before_epoch || j.created) || "—"}</td>
            <td>{j.state === "queued"
              ? <button type="button" onClick={() => cancel(j.id)}>cancel</button>
              : null}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
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
      <header className="top">
        <div>
          <p className="eyebrow">Agentic Edge</p>
          <h1>Run queue</h1>
          <p className="sub qintro">
            One job per board at a time. Each run is prechecked for memory and a
            stale output directory, and its serving flags are diffed against the
            declared baseline before lm-eval starts.
          </p>
        </div>
        <div className="status">
          <Link className="pill muted nav" href="/">&larr; live monitor</Link>
          <Link className="pill muted nav" href="/history">history &rarr;</Link>
        </div>
      </header>

      {!boxes.length && <p className="empty">Asking both boards for their queues&hellip;</p>}
      <div className="qgrid">
      {boxes.map((box) => (
        <section key={box.id} className={`card qbox qbox-${box.id}`}>
          <div className="card-head">
            <div>
              <h2>{box.label}</h2>
              <p className="sub">{box.sub}
                {box.deployed
                  ? <> · <span className={`deployed${box.deployed.dirty || box.deployed.partial ? " stale" : ""}`}
                      title={`deployed ${box.deployed.at}`}>
                      code {box.deployed.commit}{box.deployed.dirty ? " (dirty)" : ""}
                      {box.deployed.partial ? " (control files only)" : ""}</span></>
                  : box.ok ? <> · <span className="deployed stale">code: not deployed by deploy.sh</span></> : null}
              </p>
            </div>
            {box.ok
              ? <span className={`pill ${box.daemon_alive ? "live" : "danger"}`}>
                  <i className="dot" />{box.daemon_alive ? "daemon running" : "daemon down"}
                </span>
              : <span className="pill danger">unreachable</span>}
          </div>
          {!box.ok && (
            <p className="pre-error"><b>{box.error}</b>{box.hint ? <><br />{box.hint}</> : null}</p>
          )}
          {box.ok && <h4 className="qsec">New run</h4>}
          {box.ok && <JobForm box={{ ...box, ...(specs[box.id] || {}) }} onQueued={load} />}
          {box.ok && <h4 className="qsec">Jobs</h4>}
          {box.ok && <QueueList box={box} onChange={load} />}
        </section>
      ))}
      </div>
    </main>
  );
}
