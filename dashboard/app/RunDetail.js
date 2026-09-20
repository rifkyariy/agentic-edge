"use client";
import { useEffect, useState } from "react";

const fmt = (n, d = 0) =>
  n === null || n === undefined || Number.isNaN(n) ? "—"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

/* Device conditions during the run, on the same x geometry as the request
   timeline above so a spike lines up with the question that caused it. */
function DeviceTrack({ points, timeline, field, color, unit, label, max, decimals = 0 }) {
  const vals = points.map((p) => p[field]).filter((v) => v !== null && v !== undefined);
  if (!vals.length) return null;
  const W = 900, H = 74, ml = 46, mr = 44, mt = 8, mb = 14;
  const iw = W - ml - mr, ih = H - mt - mb;
  const span = timeline.length ? (timeline[timeline.length - 1].t + timeline[timeline.length - 1].pms / 1000
    + timeline[timeline.length - 1].gms / 1000) : (points[points.length - 1]?.t || 1);
  const hi = max ?? (Math.max(...vals) * 1.15 || 1);
  const X = (t) => ml + Math.min(1, t / span) * iw;
  const Y = (v) => mt + ih - (Math.min(v, hi) / hi) * ih;
  let d = "", open = false;
  for (const p of points) {
    const v = p[field];
    if (v === null || v === undefined) { open = false; continue; }
    d += `${open ? "L" : "M"}${X(p.t).toFixed(1)} ${Y(v).toFixed(1)} `;
    open = true;
  }
  return (
    <div className="track-row">
      <div className="track-head">
        <span>{label}</span>
        <b style={{ color }}>
          mean {fmt(vals.reduce((a, b) => a + b, 0) / vals.length, decimals)}{unit} ·
          peak {fmt(Math.max(...vals), decimals)}{unit}
        </b>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="tl">
        {[0, 1].map((f) => (
          <g key={f}>
            <line x1={ml} x2={ml + iw} y1={Y(hi * f)} y2={Y(hi * f)} className="gridline" />
            <text x={ml - 7} y={Y(hi * f) + 3.5} className="tick" textAnchor="end">{fmt(hi * f, decimals)}</text>
          </g>
        ))}
        <path d={d} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        {points.filter((p) => p.thr).map((p, i) => (
          <line key={i} x1={X(p.t)} x2={X(p.t)} y1={mt} y2={mt + ih} stroke="var(--warn)" strokeWidth="1" />
        ))}
      </svg>
    </div>
  );
}

/* Per-request timeline: prefill vs decode per question, decode tok/s overlaid. */
function Timeline({ rows }) {
  if (!rows?.length) return <p className="sub">No per-request timings recorded for this run.</p>;
  const W = 900, H = 200, ml = 46, mr = 44, mt = 10, mb = 22;
  const iw = W - ml - mr, ih = H - mt - mb;
  const maxSec = Math.max(...rows.map((r) => (r.pms + r.gms) / 1000)) * 1.08 || 1;
  const maxTps = Math.max(...rows.map((r) => r.gts)) * 1.15 || 1;
  const bw = iw / rows.length;
  const Y = (v) => mt + ih - (v / maxSec) * ih;
  const total = rows.reduce((a, r) => a + r.pms + r.gms, 0) / 1000;
  const med = [...rows.map((r) => r.gts)].sort((a, b) => a - b)[Math.floor(rows.length / 2)];
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="tl">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={ml} x2={ml + iw} y1={Y(maxSec * f)} y2={Y(maxSec * f)} className="gridline" />
            <text x={ml - 7} y={Y(maxSec * f) + 3.5} className="tick" textAnchor="end">{fmt(maxSec * f)}s</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x = ml + i * bw, w = Math.max(1, bw - 1.4);
          const gh = (r.gms / 1000 / maxSec) * ih, ph = (r.pms / 1000 / maxSec) * ih;
          return (
            <g key={i}>
              <rect x={x} y={mt + ih - gh} width={w} height={Math.max(0.6, gh)} fill="var(--power)" rx="1" />
              <rect x={x} y={mt + ih - gh - ph} width={w} height={Math.max(0.6, ph)} fill="var(--cpu)" rx="1" />
              <rect x={x} y={mt} width={w} height={ih} fill="transparent">
                <title>{`#${i + 1}\nprefill ${fmt(r.pt)} tok in ${fmt(r.pms / 1000, 1)}s (${fmt(r.pts, 1)} tok/s)\ndecode ${fmt(r.gt)} tok in ${fmt(r.gms / 1000, 1)}s (${fmt(r.gts, 2)} tok/s)`}</title>
              </rect>
            </g>
          );
        })}
        <polyline fill="none" stroke="var(--violet)" strokeWidth="1.5" opacity="0.9"
          points={rows.map((r, i) => `${ml + i * bw + bw / 2},${mt + ih - (r.gts / maxTps) * ih}`).join(" ")} />
        {[0, 1].map((f) => (
          <text key={f} x={ml + iw + 8} y={mt + ih - f * ih + 4} className="tick tps">{fmt(maxTps * f, 1)}</text>
        ))}
        <text x={ml} y={H - 6} className="tick">#1</text>
        <text x={ml + iw} y={H - 6} className="tick" textAnchor="end">#{rows.length}</text>
      </svg>
      <div className="tl-legend">
        <span><i style={{ background: "var(--cpu)" }} />prefill</span>
        <span><i style={{ background: "var(--power)" }} />decode</span>
        <span><i style={{ background: "var(--violet)" }} />decode tok/s</span>
        <span className="tl-sum">{rows.length} requests · {fmt(total / 60)} min of model time · median {fmt(med, 2)} tok/s</span>
      </div>
    </>
  );
}

function RequestTable({ rows }) {
  const [open, setOpen] = useState(false);
  if (!rows?.length) return null;
  const shown = open ? rows : rows.slice(0, 8);
  const anyGpu = rows.some((r) => r.dev?.gpu !== null && r.dev?.gpu !== undefined);
  return (
    <div className="reqtable">
      <table>
        <thead>
          <tr>
            <th>#</th><th>in</th><th>out</th><th>prefill</th><th>decode</th><th>tok/s</th>
            <th>mean W</th><th>peak W</th><th>energy</th><th>J/tok</th>
            <th>cpu</th>{anyGpu && <th>gpu</th>}<th>temp</th><th>rss</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className={r.dev?.throttled ? "thr" : ""}>
              <td>{r.i + 1}</td>
              <td>{fmt(r.pt)}</td><td>{fmt(r.gt)}</td>
              <td>{fmt(r.pms / 1000, 1)}s</td><td>{fmt(r.gms / 1000, 1)}s</td>
              <td>{fmt(r.gts, 2)}</td>
              <td>{fmt(r.dev?.w_mean, 2)}</td><td>{fmt(r.dev?.w_max, 2)}</td>
              <td>{fmt(r.dev?.j, 0)}J</td><td>{fmt(r.dev?.j_per_token, 2)}</td>
              <td>{fmt(r.dev?.cpu, 0)}%</td>
              {anyGpu && <td>{fmt(r.dev?.gpu, 0)}%</td>}
              <td>{fmt(r.dev?.temp_max, 1)}°</td>
              <td>{fmt(r.dev?.rss_mb)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 8 && (
        <button type="button" className="more" onClick={() => setOpen(!open)}>
          {open ? "show fewer" : `show all ${rows.length} requests`}
        </button>
      )}
    </div>
  );
}

export default function RunDetail({ boxId, boxLabel, run, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null); setErr(null);
    fetch(`/api/run?box=${boxId}&run=${encodeURIComponent(run)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => { if (alive) (j.error ? setErr(j.error) : setData(j)); })
      .catch((e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [boxId, run]);

  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const qs = (data?.questions || []).filter((q) =>
    filter === "all" || (filter === "ok" && q.ok) || (filter === "bad" && q.ok === false)
    || (filter === "none" && !q.got));

  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-label={`${run} detail`}>
        <div className="sheet-head">
          <div>
            <h2>{run}</h2>
            <p className="sub">
              {boxLabel}
              {data && <> · {data.status === "done" ? "complete" : "in progress"}
                {data.summary?.score !== undefined &&
                  <> · <b>{fmt(data.summary.score, 1)}%</b>
                    {data.summary.provisional ? ` provisional on ${data.summary.graded} graded`
                      : ` ±${fmt(data.summary.stderr, 1)} · ${fmt(data.summary.minutes)} min`}</>}
              </>}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close">esc ✕</button>
        </div>

        {!data && !err && <p className="sub loading">Reading the run off the device…</p>}
        {err && <pre className="err">{err}</pre>}

        {data && (
          <div className="sheet-body">
            {data.note && <p className="note-partial">{data.note}</p>}

            {data.device && (
              <div className="devstrip">
                <span>energy <b>{fmt(data.device.energy_wh, 2)} Wh</b></span>
                <span>idle <b>{fmt(data.device.idle_w, 2)} W</b></span>
                <span>working <b>{fmt(data.device.mean_w, 2)} W</b></span>
                <span>peak <b>{fmt(data.device.peak_w, 2)} W</b></span>
                <span>J/token <b>{fmt(data.device.j_per_token, 2)}</b></span>
                <span>tok/s/W <b>{fmt(data.device.tok_s_per_w, 3)}</b></span>
                <span>cpu <b>{fmt(data.device.cpu_mean, 0)}%</b></span>
                <span>peak temp <b>{fmt(data.device.temp_max, 1)}°C</b></span>
                <span className={data.device.throttled ? "warnspan" : ""}>
                  throttling <b>{data.device.throttled ? `${data.device.throttled} samples` : "none"}</b>
                </span>
              </div>
            )}

            <section>
              <h3>Request timeline <em>and device conditions through the run</em></h3>
              <Timeline rows={data.timeline} />
              {data.telemetry?.length > 0 && (
                <div className="tracks">
                  <DeviceTrack points={data.telemetry} timeline={data.timeline} field="w"
                    color="var(--power)" unit="W" label="board power" decimals={2} />
                  <DeviceTrack points={data.telemetry} timeline={data.timeline} field="cpu"
                    color="var(--cpu)" unit="%" label="cpu" max={100} />
                  <DeviceTrack points={data.telemetry} timeline={data.timeline} field="gpu"
                    color="var(--gpu)" unit="%" label="gpu" max={100} />
                  <DeviceTrack points={data.telemetry} timeline={data.timeline} field="temp"
                    color="var(--temp)" unit="°C" label="temperature" decimals={1} />
                </div>
              )}
            </section>

            <section>
              <h3>Per request <em>tokens and what the board was doing</em></h3>
              <RequestTable rows={data.timeline} />
            </section>

            <section>
              <div className="qhead">
                <h3>Questions and answers <em>{qs.length} shown</em></h3>
                <div className="tabs">
                  {[["all", "All"], ["ok", "Correct"], ["bad", "Wrong"], ["none", "No answer letter"]]
                    .map(([v, l]) => (
                      <button key={v} type="button" aria-pressed={String(filter === v)}
                        onClick={() => setFilter(v)}>{l}</button>
                    ))}
                </div>
              </div>
              <div className="qlist">
                {qs.map((q, i) => (
                  <div key={i} className={`qrow ${open === i ? "open" : ""}`}>
                    <button type="button" className="qsum" onClick={() => setOpen(open === i ? null : i)}>
                      <span className="qsubject">{q.subject || "unmatched"}</span>
                      <span className="qtext">{q.q ? (q.q.length > 90 ? q.q.slice(0, 90) + "…" : q.q)
                        : q.resp.slice(0, 90) + "…"}</span>
                      <span className={`tag ${q.ok === true ? "ok" : q.ok === false ? "bad" : "unk"}`}>
                        {q.got || "none"}{q.gold ? ` / ${q.gold}` : ""}
                      </span>
                    </button>
                    {open === i && (
                      <div className="qdetail">
                        {q.q && <p className="qfull">{q.q}</p>}
                        {q.options?.length > 0 && (
                          <ol className="opts">
                            {q.options.map((o, j) => {
                              const L = "ABCDEFGHIJ"[j];
                              return <li key={j} className={`${L === q.gold ? "gold " : ""}${L === q.got ? "picked" : ""}`}>
                                {L}. {o}</li>;
                            })}
                          </ol>
                        )}
                        <h4>Model answer <em>{fmt(q.chars)} characters</em></h4>
                        <pre className="resp" dangerouslySetInnerHTML={{
                          __html: q.resp.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
                            .replace(/([Tt]he answer is \(?[A-J]\)?\.?)/g, "<mark>$1</mark>")
                        }} />
                      </div>
                    )}
                  </div>
                ))}
                {!qs.length && <p className="sub">No answers recorded yet.</p>}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
