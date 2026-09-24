"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import RunDetail from "../RunDetail";
import { fmt, durMinutes as dur } from "../lib/format";
import PageHeader from "../components/PageHeader";
import StatePill from "../components/StatePill";

// What each status means, in the words the table shows. AGENTS §5: every run
// is reported, failures and superseded ones included, so none are hidden by
// default — the filters narrow, they never drop a run silently.
const STATUS = {
  done: "complete",
  running: "running",
  incomplete: "did not finish",
  failed: "failed",
  superseded: "superseded",
  extra: "smoke / copy",
};


function Chips({ label, value, options, onChange }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      <span>{label}</span>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v}
                onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

export default function HistoryPage() {
  const [boxes, setBoxes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [board, setBoard] = useState("all");
  const [status, setStatus] = useState("all");
  const [thinking, setThinking] = useState("all");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState(null);   // {box, run}

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/history", { cache: "no-store" });
      const data = await res.json();
      setBoxes(data.boxes || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => boxes.flatMap((b) =>
    (b.runs || []).map((r) => ({ ...r, box: b }))), [boxes]);

  const shown = rows.filter((r) =>
    (board === "all" || r.box.id === board)
    && (status === "all" || r.status === status)
    && (thinking === "all" || r.thinking === thinking)
    && (!q || r.run.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (b.ended ?? Infinity) - (a.ended ?? Infinity));

  const counts = rows.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] || 0) + 1 }), {});
  const statusOptions = [["all", `all ${rows.length}`],
    ...Object.keys(STATUS).filter((s) => counts[s]).map((s) => [s, `${STATUS[s]} ${counts[s]}`])];

  return (
    <main>
      <PageHeader title="Experiment history"
                  sub="Every benchmark run on disk on both boards — complete, failed and superseded alike, each with the telemetry of the run that produced it. Click a run for its answers, timeline and device cost." />

      <section className="card">
        <div className="filters">
          <Chips label="board" value={board} onChange={setBoard}
                 options={[["all", "both"], ...boxes.map((b) => [b.id, b.label])]} />
          <Chips label="thinking" value={thinking} onChange={setThinking}
                 options={[["all", "any"], ["off", "off"], ["on", "on"]]} />
          <Chips label="status" value={status} onChange={setStatus} options={statusOptions} />
          <input className="search" value={q} placeholder="search run name…"
                 onChange={(e) => setQ(e.target.value)} aria-label="search run name" />
          <button type="button" className="refresh" onClick={load} disabled={loading}>
            {loading ? "loading…" : "refresh"}
          </button>
        </div>

        {boxes.filter((b) => !b.ok).map((b) => (
          <p key={b.id} className="pre-error"><b>{b.label}: {b.error}</b>
            {b.hint ? <><br />{b.hint}</> : null}</p>
        ))}

        {loading && !rows.length && <p className="empty">Reading both boards&hellip;</p>}
        {!loading && !shown.length && <p className="empty">No runs match these filters.</p>}

        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>board</th><th>run</th><th>model</th><th>subset</th><th>think</th>
                  <th>status</th><th className="num">score</th><th className="num">time</th>
                  <th className="num">energy</th><th className="num">J/token</th><th>finished</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={`${r.box.id}/${r.run}`} className={`st-${r.status}`}
                      tabIndex={0} role="button"
                      onClick={() => setDetail({ box: r.box, run: r.run })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault(); setDetail({ box: r.box, run: r.run });
                        }
                      }}>
                    <td><i className={`board-dot b-${r.box.id}`} />{r.box.id}</td>
                    <td className="runname">
                      {r.run}
                      {r.job && (
                        <Link className="joblink" href={`/queue/${r.box.id}/${r.job.id}`}
                              onClick={(e) => e.stopPropagation()}>queue job</Link>
                      )}
                    </td>
                    <td>{r.model?.toUpperCase() ?? "—"}</td>
                    <td>{r.subset ?? "—"}</td>
                    <td>{r.thinking === "on" ? <b className="think-on">on</b> : r.thinking ?? "—"}</td>
                    <td><StatePill family="hist" state={r.status} label={STATUS[r.status] ?? r.status} /></td>
                    <td className="num">
                      {r.score != null
                        ? <><b>{fmt(r.score, 1)}%</b>{r.stderr != null && <i> ±{fmt(r.stderr, 1)}</i>}</>
                        : "—"}
                    </td>
                    <td className="num">{dur(r.minutes)}</td>
                    <td className="num">{r.device ? `${fmt(r.device.energy_wh, 1)} Wh` : "—"}</td>
                    <td className="num">{r.device ? fmt(r.device.j_per_token, 2) : "—"}</td>
                    <td className="when">{r.at ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="foot">
          Energy and J/token come from the matching measured run&rsquo;s
          <code>summary.json</code>; &ldquo;—&rdquo; means that run was never
          wrapped in telemetry, or was killed before its summary was written.
          Power is board DC draw, not wall power.
        </p>
      </section>

      {detail && (
        <RunDetail boxId={detail.box.id} boxLabel={detail.box.label} run={detail.run}
                   onClose={() => setDetail(null)} />
      )}
    </main>
  );
}
