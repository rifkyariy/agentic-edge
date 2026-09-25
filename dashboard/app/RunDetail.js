"use client";
import { useEffect, useState } from "react";
import { TrackChart, TimelineChart, fmt } from "./Charts";


/* What one question cost the board. Stat tiles rather than a run of text: the
   number is the thing being read, and each one is placed against the run's own
   baseline so "is this question expensive?" is answerable at a glance. */
function Delta({ value, base, decimals = 1, goodWhen = "lower", unit = "", vs = "run avg" }) {
  if (value === null || value === undefined || !base) return null;
  const diff = value - base;
  const pct = (diff / base) * 100;
  if (Math.abs(pct) < 2) return <em className="delta flat">level with {vs}</em>;
  const good = goodWhen === "lower" ? diff < 0 : diff > 0;
  return (
    <em className={`delta ${good ? "good" : "poor"}`}>
      {diff > 0 ? "▲" : "▼"} {fmt(Math.abs(diff), decimals)}{unit} vs {vs}
    </em>
  );
}

function Tile({ label, value, unit, sub, accent, wide }) {
  return (
    <div className={`tile ${wide ? "wide" : ""}`}>
      <span className="tile-label">{label}</span>
      <b className="tile-value" style={accent ? { color: accent } : undefined}>
        {value}{unit && <i>{unit}</i>}
      </b>
      {sub}
    </div>
  );
}

/* What the whole run cost the board. Energy leads because device cost is the
   measurement the experiment exists to make; the rest sits under it as tiles. */
function RunCost({ d, minutes }) {
  const span = d.peak_w || 1;
  return (
    <div className="reqcard runcost">
      <div className="reqcard-head">
        <span className="reqcard-title">Device cost</span>
        {minutes ? <span className="reqcard-when">over {fmt(minutes)} min</span> : null}
        {d.provisional && <span className="chip warn">so far — run still in progress</span>}
        {d.throttled
          ? <span className="chip warn">⚠ thermally throttled · {fmt(d.throttled)} samples</span>
          : <span className="chip ok">✓ never throttled</span>}
      </div>

      <div className="reqcard-hero">
        <div>
          <span className="tile-label">Energy</span>
          <b className="hero-value">{fmt(d.energy_wh, 2)}<i>Wh</i></b>
          <em className="delta flat">board DC draw, not wall power</em>
        </div>
        {/* Idle, working and peak on one 0→peak scale: how much of the draw is
            the model rather than the board simply being switched on. */}
        <div className="split">
          <div className="split-head">
            <span>Board power</span>
            <span className="split-keys">0 – {fmt(d.peak_w, 2)} W peak</span>
          </div>
          <div className="meter" role="img"
               aria-label={`idle ${fmt(d.idle_w, 2)} watts, working ${fmt(d.mean_w, 2)} watts, peak ${fmt(d.peak_w, 2)} watts`}>
            <span className="meter-fill" style={{ width: `${(d.mean_w / span) * 100}%` }} />
            <span className="meter-mark idle" style={{ left: `${(d.idle_w / span) * 100}%` }} />
          </div>
          <div className="meter-keys">
            {/* clamp(): centred on its mark, except where that would run off
                an edge. The peak is named in the head, not labelled again. */}
            <span style={{ left: `clamp(34px, ${(d.idle_w / span) * 100}%, calc(100% - 150px))` }}>
              idle {fmt(d.idle_w, 2)} W</span>
            <span className="work" style={{ left: `clamp(52px, ${(d.mean_w / span) * 100}%, calc(100% - 52px))` }}>
              working {fmt(d.mean_w, 2)} W</span>
          </div>
        </div>
      </div>

      <div className="tiles">
        <Tile label="Energy per token" value={fmt(d.j_per_token, 2)} unit="J/tok"
              sub={<em className="delta flat">generated tokens</em>} />
        <Tile label="Throughput per watt" value={fmt(d.tok_s_per_w, 3)} unit="tok/s/W"
              sub={<em className="delta flat">decode</em>} />
        <Tile label="CPU" value={fmt(d.cpu_mean, 0)} unit="%" accent="var(--cpu)"
              sub={<em className="delta flat">mean over the run</em>} />
        {/* Jetson only — the Pi has no discrete GPU to sample. */}
        {d.gpu_mean !== null && d.gpu_mean !== undefined && (
          <Tile label="GPU" value={fmt(d.gpu_mean, 0)} unit="%" accent="var(--gpu)"
                sub={<><em className="delta flat">{fmt(d.gpu_max, 0)}% peak</em>
                  {d.gpu_mhz_mean ? <em className="delta flat">{fmt(d.gpu_mhz_mean)} MHz mean</em> : null}</>} />
        )}
        <Tile label="Peak temperature" value={fmt(d.temp_max, 1)} unit="°C" accent="var(--temp)"
              sub={<em className={`delta ${d.throttled ? "poor" : "good"}`}>
                {d.throttled ? `clock capped on ${fmt(d.throttled)} samples`
                             : "clock never capped"}</em>} />
      </div>
    </div>
  );
}

function ReqStats({ r, run, median }) {
  if (!r) return null;
  const d = r.dev || {};
  const pre = r.pms / 1000, dec = r.gms / 1000, tot = pre + dec;
  const gpu = d.gpu !== null && d.gpu !== undefined;

  return (
    <div className="reqcard">
      <div className="reqcard-head">
        <span className="reqcard-title">Request #{r.i + 1}</span>
        <span className="reqcard-when">{fmt(r.t / 60, 1)} min into the run</span>
        {d.throttled && <span className="chip warn">⚠ thermally throttled</span>}
        {d.samples ? <span className="reqcard-when">{fmt(d.samples)} telemetry samples</span> : null}
      </div>

      {/* The headline: how fast the board generated this answer. */}
      <div className="reqcard-hero">
        <div>
          <span className="tile-label">Decode speed</span>
          <b className="hero-value">{fmt(r.gts, 2)}<i>tok/s</i></b>
          <Delta value={r.gts} base={median} decimals={2} goodWhen="higher" unit=" tok/s" vs="run median" />
        </div>
        {/* Where the time went. One bar, two segments, both labelled — the
            split is the point, so it gets a mark rather than two numbers. */}
        <div className="split">
          <div className="split-head">
            <span>{fmt(tot, 1)}s total</span>
            <span className="split-keys">
              <i style={{ background: "var(--cpu)" }} />prefill {fmt(pre, 1)}s
              <i style={{ background: "var(--power)" }} />decode {fmt(dec, 1)}s
            </span>
          </div>
          <div className="split-bar" role="img"
               aria-label={`prefill ${fmt(pre, 1)} seconds, decode ${fmt(dec, 1)} seconds`}>
            <span style={{ width: `${(pre / tot) * 100}%`, background: "var(--cpu)" }} />
            <span style={{ width: `${(dec / tot) * 100}%`, background: "var(--power)" }} />
          </div>
        </div>
      </div>

      <div className="tiles">
        <Tile label="Tokens in" value={fmt(r.pt)} unit="tok"
              sub={<em className="delta flat">{fmt(r.pts, 1)} tok/s prefill</em>} />
        <Tile label="Tokens out" value={fmt(r.gt)} unit="tok"
              sub={r.gt >= 2048 ? <em className="delta poor">hit the 2,048 cap</em> : null} />
        <Tile label="Board power" value={fmt(d.w_mean, 2)} unit="W" accent="var(--power)"
              sub={<><Delta value={d.w_mean} base={run?.mean_w} decimals={2} unit=" W" />
                     <em className="delta flat">{fmt(d.w_max, 2)} W peak</em></>} />
        <Tile label="Energy" value={fmt(d.j, 0)} unit="J"
              sub={<em className="delta flat">{fmt(d.j / 3600, 4)} Wh</em>} />
        <Tile label="Energy per token" value={fmt(d.j_per_token, 2)} unit="J/tok"
              sub={<Delta value={d.j_per_token} base={run?.j_per_token} decimals={2} />} />
        <Tile label="CPU" value={fmt(d.cpu, 0)} unit="%" accent="var(--cpu)"
              sub={<Delta value={d.cpu} base={run?.cpu_mean} decimals={0} unit="%" />} />
        {gpu && <Tile label="GPU" value={fmt(d.gpu, 0)} unit="%" accent="var(--gpu)" />}
        <Tile label="Peak temperature" value={fmt(d.temp_max, 1)} unit="°C" accent="var(--temp)"
              sub={<Delta value={d.temp_max} base={run?.temp_max} decimals={1} unit="°C" vs="run peak" />} />
        <Tile label="Server memory" value={fmt(d.rss_mb / 1024, 2)} unit="GB"
              sub={<em className="delta flat">{fmt(d.rss_mb)} MB resident</em>} />
      </div>
    </div>
  );
}

/* The table view for the timeline above: every request, every column, plus the
   run's own aggregate underneath. The four columns the experiment turns on —
   slowest decode, highest peak draw, highest energy per token, hottest — mark
   the request that set the record, so an outlier is findable without sorting. */
const median = (v) => [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)];
const mean = (v) => v.reduce((a, b) => a + b, 0) / v.length;

/* One numeric cell. `rec` marks it as the run's extreme in that column, with
   the direction the extreme runs — every one of these is the adverse end, so it
   wears the status colour and an arrow, never colour alone. */
function Cell({ v, d, rec, why }) {
  return (
    <td className={rec ? "rec" : ""} title={rec ? why : undefined}>
      {rec && <i aria-hidden="true">{rec === "high" ? "\u25b2" : "\u25bc"}</i>}
      {fmt(v, d)}
      {rec && <span className="sr">{` — ${why}`}</span>}
    </td>
  );
}

function RequestTable({ rows, onPick }) {
  const [open, setOpen] = useState(false);
  if (!rows?.length) return null;
  const shown = open ? rows : rows.slice(0, 8);
  const anyGpu = rows.some((r) => r.dev?.gpu !== null && r.dev?.gpu !== undefined);

  const col = (f) => rows.map(f).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  const tps = col((r) => r.gts), wmax = col((r) => r.dev?.w_max);
  const jpt = col((r) => r.dev?.j_per_token), temp = col((r) => r.dev?.temp_max);
  const agg = {
    pt: col((r) => r.pt), gt: col((r) => r.gt),
    pms: col((r) => r.pms), gms: col((r) => r.gms),
    wmean: col((r) => r.dev?.w_mean), j: col((r) => r.dev?.j),
    cpu: col((r) => r.dev?.cpu), gpu: col((r) => r.dev?.gpu),
    rss: col((r) => r.dev?.rss_mb),
  };
  // the record-holder in each of the four columns that matter
  const rec = {
    tps: Math.min(...tps), w: Math.max(...wmax),
    jpt: Math.max(...jpt), temp: Math.max(...temp),
  };
  const sum = (v) => v.length ? v.reduce((a, b) => a + b, 0) : null;

  return (
    <div className="reqtable">
      <div className="reqtable-scroll">
        <table>
          <thead>
            <tr>
              <th className="grp" /><th className="grp" colSpan={2}>tokens</th>
              <th className="grp" colSpan={3}>timing</th>
              <th className="grp" colSpan={4}>power &amp; energy</th>
              <th className="grp" colSpan={anyGpu ? 4 : 3}>board</th>
            </tr>
            <tr>
              <th>#</th>
              <th>in</th><th>out</th>
              <th>prefill<i>s</i></th><th>decode<i>s</i></th><th>decode<i>tok/s</i></th>
              <th>mean<i>W</i></th><th>peak<i>W</i></th><th>energy<i>J</i></th><th>per token<i>J</i></th>
              <th>cpu<i>%</i></th>{anyGpu && <th>gpu<i>%</i></th>}
              <th>temp<i>°C</i></th><th>server rss<i>MB</i></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className={`${r.dev?.throttled ? "thr" : ""} ${onPick ? "pick" : ""}`}
                  onClick={() => onPick?.(r.i)}
                  title={onPick ? "show this question" : undefined}>
                <td>{r.i + 1}</td>
                <td>{fmt(r.pt)}</td><td>{fmt(r.gt)}</td>
                <td>{fmt(r.pms / 1000, 1)}</td><td>{fmt(r.gms / 1000, 1)}</td>
                <Cell v={r.gts} d={2} rec={r.gts === rec.tps && "low"}
                      why="slowest decode of the run" />
                <td>{fmt(r.dev?.w_mean, 2)}</td>
                <Cell v={r.dev?.w_max} d={2} rec={r.dev?.w_max === rec.w && "high"}
                      why="highest draw of the run" />
                <td>{fmt(r.dev?.j, 0)}</td>
                <Cell v={r.dev?.j_per_token} d={2} rec={r.dev?.j_per_token === rec.jpt && "high"}
                      why="least efficient request of the run" />
                <td>{fmt(r.dev?.cpu, 0)}</td>
                {anyGpu && <td>{fmt(r.dev?.gpu, 0)}</td>}
                <Cell v={r.dev?.temp_max} d={1} rec={r.dev?.temp_max === rec.temp && "high"}
                      why="hottest the board got all run" />
                <td>{fmt(r.dev?.rss_mb)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th>all {rows.length}</th>
              <td>{fmt(sum(agg.pt))}</td><td>{fmt(sum(agg.gt))}</td>
              <td>{fmt(sum(agg.pms) / 1000, 0)}</td><td>{fmt(sum(agg.gms) / 1000, 0)}</td>
              <td>{fmt(median(tps), 2)}</td>
              <td>{fmt(mean(agg.wmean), 2)}</td><td>{fmt(rec.w, 2)}</td>
              <td>{fmt(sum(agg.j), 0)}</td><td>{fmt(mean(jpt), 2)}</td>
              <td>{fmt(mean(agg.cpu), 0)}</td>
              {anyGpu && <td>{agg.gpu.length ? fmt(mean(agg.gpu), 0) : "—"}</td>}
              <td>{fmt(rec.temp, 1)}</td>
              <td>{fmt(Math.max(...agg.rss))}</td>
            </tr>
            <tr className="aggkey">
              <th />
              <td>total</td><td>total</td><td>total</td><td>total</td>
              <td>median</td>
              <td>mean</td><td>max</td><td>total</td><td>mean</td>
              <td>mean</td>{anyGpu && <td>mean</td>}<td>max</td><td>max</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="reqtable-foot">
        {rows.length > 8 && (
          <button type="button" className="more" onClick={() => setOpen(!open)}>
            {open ? "show fewer" : `show all ${rows.length} requests`}
          </button>
        )}
        <span className="reclegend">
          <i>{"\u25b2"}</i><i>{"\u25bc"}</i> the run&apos;s extreme in that column
        </span>
      </div>
    </div>
  );
}

export default function RunDetail({ boxId, boxLabel, run, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [hintText, setHint] = useState(null);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);
  const [tab, setTab] = useState("device");

  useEffect(() => {
    let alive = true;
    setData(null); setErr(null); setHint(null);
    fetch(`/api/run?box=${boxId}&run=${encodeURIComponent(run)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => { if (!alive) return; if (j.error) { setErr(j.error); setHint(j.hint); } else setData(j); })
      .catch((e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [boxId, run]);

  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  // shared x domain for the device tracks: end of the last request, so a
  // spike lines up with the question that caused it.
  const tl = data?.timeline;
  const lastReq = tl?.length ? tl[tl.length - 1] : null;
  const runSpan = lastReq ? lastReq.t + (lastReq.pms + lastReq.gms) / 1000
    : data?.telemetry?.length ? data.telemetry[data.telemetry.length - 1].t : undefined;

  // Every per-request number is read against the run's own average, so the
  // baselines are computed once here rather than per question.
  const medianTps = tl?.length
    ? [...tl.map((r) => r.gts)].sort((a, b) => a - b)[Math.floor(tl.length / 2)] : null;

  // Requests and answers are both in the order the model produced them, so
  // request #i is question #i. Jumping between them is that index.
  const pick = (i) => {
    if (i === null || i === undefined) return;
    setTab("questions"); setFilter("all"); setOpen(i);
    requestAnimationFrame(() =>
      document.getElementById(`q-${i}`)?.scrollIntoView({ block: "center", behavior: "smooth" }));
  };

  const qs = (data?.questions || []).map((q, i) => ({ ...q, _i: i })).filter((q) =>
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
              {data?.engine && <> · {data.engine}</>}
              {data && <> · {data.status === "done" ? "complete" : data.status === "incomplete" ? "did not finish" : "in progress"}
                {data.summary?.score !== undefined &&
                  <> · <b>{fmt(data.summary.score, 1)}%</b>
                    {data.summary.provisional ? ` provisional on ${data.summary.graded} graded`
                      : ` ±${fmt(data.summary.stderr, 1)} · ${fmt(data.summary.minutes)} min`}</>}
              </>}
            </p>
          </div>
          <div className="sheet-actions">
            {data && (
              <nav className="sheet-tabs" role="tablist">
                {[["device", "Device"], ["questions", `Questions${data.n ? ` (${data.n})` : ""}`]]
                  .map(([v, l]) => (
                    <button key={v} type="button" role="tab" aria-selected={String(tab === v)}
                      onClick={() => setTab(v)}>{l}</button>
                  ))}
              </nav>
            )}
            <button type="button" onClick={onClose} aria-label="Close">esc ✕</button>
          </div>
        </div>

        {!data && !err && <p className="sub loading">Reading the run off the device…</p>}
        {err && <><pre className="err">{err}</pre>{hintText && <p className="setup-hint">{hintText}</p>}</>}

        {data && (
          <div className="sheet-body">
            {data.note && <p className="note-partial">{data.note}</p>}

            {tab === "device" && (<>
            {data.device && <RunCost d={data.device} minutes={data.summary?.minutes} />}

            <section>
              <h3>Request timeline <em>and device conditions through the run</em></h3>
              <TimelineChart rows={data.timeline} onPick={pick} />
              {data.telemetry?.length > 0 && (
                <div className="tracks">
                  <TrackChart points={data.telemetry} span={runSpan} dataKey="w"
                    color="var(--power)" unit="W" label="board power" decimals={2} />
                  <TrackChart points={data.telemetry} span={runSpan} dataKey="cpu"
                    color="var(--cpu)" unit="%" label="cpu" domainMax={100} />
                  <TrackChart points={data.telemetry} span={runSpan} dataKey="gpu"
                    color="var(--gpu)" unit="%" label="gpu" domainMax={100} />
                  <TrackChart points={data.telemetry} span={runSpan} dataKey="temp"
                    color="var(--temp)" unit="°C" label="temperature" decimals={1} />
                </div>
              )}
            </section>

            <section>
              <h3>Per request <em>tokens and what the board was doing</em></h3>
              <RequestTable rows={data.timeline} onPick={pick} />
            </section>

            </>)}

            {tab === "questions" && (
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
                {qs.map((q) => (
                  <div key={q._i} id={`q-${q._i}`} className={`qrow ${open === q._i ? "open" : ""}`}>
                    <button type="button" className="qsum" onClick={() => setOpen(open === q._i ? null : q._i)}>
                      <span className="qnum">#{q._i + 1}</span>
                      <span className="qsubject">{q.subject || "unmatched"}</span>
                      <span className="qtext">{q.q ? (q.q.length > 90 ? q.q.slice(0, 90) + "…" : q.q)
                        : q.resp.slice(0, 90) + "…"}</span>
                      <span className={`tag ${q.ok === true ? "ok" : q.ok === false ? "bad" : "unk"}`}>
                        {q.got || "none"}{q.gold ? ` / ${q.gold}` : ""}
                      </span>
                    </button>
                    {open === q._i && (
                      <div className="qdetail">
                        <ReqStats r={data.timeline?.[q._i]} run={data.device} median={medianTps} />
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
            )}
          </div>
        )}
      </div>
    </div>
  );
}
