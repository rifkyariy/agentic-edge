"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { PLAN, cell, BATCH_START } from "./lib/plan";
import RunDetail from "./RunDetail";
import { MetricChart } from "./Charts";
import { fmt, durSeconds as dur } from "./lib/format";
import { usePoll } from "./lib/usePoll";
import { useQueue } from "./lib/queue-context";
import PageHeader from "./components/PageHeader";
import { ago, PHONE_STATE } from "./components/Nav";

const POLL_MS = 5000;
const WINDOW_MIN = 20;                       // charted history
const HISTORY = (WINDOW_MIN * 60) / (POLL_MS / 1000);

// One row per model and reasoning condition. The thinking row is the S2
// experiment (THINKING=on, budget 320); it stays empty until those runs exist.
const ROWS = PLAN.thinking.flatMap((t) => PLAN.models.map((m) => ({ m, t })));
// Then one group of those rows per engine the board runs: llama.cpp on both,
// little-gemma (S3) on the Jetson alone.
const enginesFor = (boxId) => PLAN.engines.filter((e) => e.boards.includes(boxId));

function Matrix({ boxes, queues, onOpen }) {
  return (
    <section className="matrix card">
      <div className="card-head">
        <div>
          <h2>MMLU-Pro</h2>
          <p className="sub">Three 100-question subsets per model. Click a cell to open its run.</p>
        </div>
        <details className="flags">
          <summary>Serving flags</summary>
          <dl>
            <dt>Baseline</dt><dd>llama.cpp <code>-rea off --reasoning-budget -1</code>, greedy</dd>
            <dt>think</dt><dd><code>-rea on --reasoning-budget 320 --reasoning-format none</code></dd>
            <dt>LG</dt><dd>little-gemma, <code>-think -1</code> or <code>-think 320</code> (Jetson only)</dd>
            <dt>TQ</dt><dd>llama.cpp with a TurboQuant KV cache, <code>-ctk turbo3 -ctv turbo3</code></dd>
          </dl>
          <Link href="/compare">Scope and caveats</Link>
        </details>
      </div>
      <div className="matrix-grid">
        {boxes.map((box) => (
          <div key={box.id} className="matrix-box">
            <h3>{box.label}</h3>
            <table>
              <thead>
                <tr><th />{PLAN.subsets.map((s) => <th key={s}>{s}</th>)}</tr>
              </thead>
              {enginesFor(box.id).map((e, _, all) => (
              <tbody key={e.id}>
                {all.length > 1 && (
                  <tr className="engine-row"><th colSpan={PLAN.subsets.length + 1}>{e.id}</th></tr>
                )}
                {ROWS.filter(({ t }) => !e.thinking || e.thinking.includes(t)).map(({ m, t }) => (
                  <tr key={`${m}-${t}`}>
                    <th>{e.short ? <i className="row-tag">{e.short} </i> : null}{m.toUpperCase()}{t === "on" ? <i className="row-tag"> think</i> : null}</th>
                    {PLAN.subsets.map((s) => {
                      const c = cell(box, m, s, t, queues[box.id], e.id);
                      // Queued and blocked jobs have no results yet; their
                      // page is the job's timeline, not the run drill-down.
                      const open = c.job && (c.status === "queued" || c.status === "blocked")
                        ? () => { window.location.href = `/queue/${box.id}/${c.job}`; }
                        : c.run ? () => onOpen(box, c.run) : null;
                      return (
                        <td key={s}>
                          <button type="button"
                            className={`cellbox ${c.status}`}
                            disabled={!open}
                            onClick={() => open && open()}
                            title={`${e.id} ${m} ${s} thinking ${t}: ${c.status}${c.note ? ` — ${c.note}` : ""}`}>
                            {c.status === "done" && <><b>{fmt(c.score, 1)}%</b><i>±{fmt(c.stderr, 1)}</i></>}
                            {c.status === "prior" && <><b>{fmt(c.score, 1)}%</b><i>{c.at?.slice(5, 10)} · earlier batch</i></>}
                            {c.status === "running" && <><b>{c.pct ?? "…"}{c.pct != null ? "%" : ""}</b><i>{c.eta ? `${c.eta} left` : "starting"}</i></>}
                            {c.status === "queued" && <i>queued</i>}
                            {c.status === "blocked" && <><b>blocked</b><i>see job</i></>}
                            {c.status === "pending" && <i>not run</i>}
                            {c.status === "unknown" && <i>—</i>}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              ))}
            </table>
          </div>
        ))}
      </div>
      <div className="legend">
        <span><i className="sw done" />complete</span>
        <span><i className="sw running" />running</span>
        <span><i className="sw queued" />queued</span>
        <span><i className="sw blocked" />blocked</span>
        <span title={`results from before ${BATCH_START}, without telemetry`}><i className="sw prior" />earlier batch</span>
        <span><i className="sw pending" />not run</span>
        <span className="ref" title="Google's published MMLU-Pro scores, for reference">published: E2B 60.0% · E4B 69.4%</span>
      </div>
    </section>
  );
}

function Progress({ p, tag, onOpen }) {
  return (
    <div className="run">
      <div className="run-top">
        <button type="button" className="run-name link" onClick={onOpen}
          title="open this run's timeline and answers">
          {p.run}{tag ? <em> · {tag}</em> : null}
        </button>
        <span className="run-count">{p.done}<i>/{p.total}</i></span>
      </div>
      <div className="track"><i style={{ width: `${p.pct}%` }} /></div>
      <div className="run-foot">
        <span>{p.elapsed} elapsed</span>
        <span>{fmt(p.s_per_item, 0)}s/question</span>
        <span className="eta">{p.eta} remaining</span>
      </div>
    </div>
  );
}

// iOS's ProcessInfo.ThermalState, which is all the phone says about heat.
const THERMAL = ["nominal", "fair", "serious", "critical"];

/* The iPhone is not a board: no power rails, no temperatures, no ssh. It reports
   the app's own CPU and memory, iOS's thermal state and the battery level, by
   upload (dashboard/app/lib/phone.js), so its card shows those and says how
   fresh they are. Energy comes after a run, measured or estimated. */
function PhoneDevice({ box, hist, onOpen }) {
  const d = box.data || {};
  const ph = d.phone || {};
  const p = d.progress, m = d.measured;
  const live = Boolean(d.procs?.lm_eval);
  const state = ph.state || (live ? "running" : "never");
  const PILL = { running: ["live", "running"], lost: ["danger", "lost contact"],
                 idle: ["muted", "idle"], never: ["muted", "no uploads"] };
  const sum = m?.summary;
  const th = ph.thermal;
  const measured = sum?.energy_source?.startsWith("measured");
  return (
    <section className="card device phone">
      <div className="card-head">
        <div>
          <h2>{box.label}</h2>
          <p className="sub">{box.sub}</p>
        </div>
        <span className={`pill ${PILL[state][0]}`}
              title={PHONE_STATE[state]?.({ age_s: ph.upload_age_s })}>
          {state === "running" && <i className="dot" />}{PILL[state][1]}
        </span>
      </div>

      {p && <Progress p={p} tag="MLX" onOpen={() => onOpen(box, p.run)} />}

      <div className="kpis">
        <div className="kpi" title="the app's CPU, summed over its threads, as % of one core (can pass 100)">
          <span>app cpu</span><b>{fmt(ph.cpu_pct, 0)}<i>%</i></b></div>
        <div className="kpi" title="phys_footprint: what iOS's memory limit (jetsam) is measured against">
          <span>app memory</span><b>{fmt(ph.footprint_mb == null ? null : ph.footprint_mb / 1024, 1)}
            <i>{ph.ram_gb ? `/${ph.ram_gb}G` : "G"}</i></b></div>
        <div className={`kpi thermal t${th ?? "x"}`} title="iOS thermal state; the phone exposes no temperature">
          <span>thermal</span><b className="word">{th == null ? "—" : THERMAL[th] ?? th}</b></div>
        <div className="kpi"><span>battery</span><b>{fmt(ph.battery_pct, 0)}<i>%</i></b></div>
      </div>

      <div className="panels">
        <MetricChart data={hist} dataKey="cpu" color="var(--cpu)" unit="%"
          label="app cpu (% of one core)" windowMin={WINDOW_MIN} />
        <MetricChart data={hist} dataKey="mem" color="var(--iphone)" unit="MB"
          label="app memory" windowMin={WINDOW_MIN} />
        <MetricChart data={hist} dataKey="battery" color="var(--power)" unit="%"
          label="battery" domainMax={100} windowMin={WINDOW_MIN} />
      </div>

      <div className="meta">
        {sum ? (
          <>
            <span title={sum.energy_source}>energy <b>{fmt(sum.energy_wh, 2)} Wh</b>
              {sum.energy_wh != null && !measured ? <i className="est"> est.</i> : null}</span>
            <span>J/token <b>{fmt(sum.j_per_token, 2)}</b></span>
            <span>decode <b>{fmt(sum.decode_tok_s, 1)} tok/s</b></span>
            <span>battery used <b>{fmt(sum.battery_used_pct, 0)}%</b></span>
            <span>worst thermal <b>{sum.thermal_max == null ? "—" : THERMAL[sum.thermal_max]}</b></span>
          </>
        ) : m?.samples ? (
          <span>telemetry <b>{fmt(m.samples)}</b> samples · energy after the run</span>
        ) : <span>no runs uploaded yet</span>}
      </div>

      <footer>
        <span>{[ph.model_id, ph.os].filter(Boolean).join(" · ") || "iPhone"}</span>
        <span className="dim">last upload {ago(ph.upload_age_s)}</span>
      </footer>
    </section>
  );
}

function Device({ box, hist, onOpen }) {
  const d = box.data;
  if (!box.ok || !d) {
    return (
      <section className="card offline">
        <div className="card-head">
          <h2>{box.label}</h2><span className="pill danger">unreachable</span>
        </div>
        <pre className="err">{box.error}</pre>
        {box.hint && (
          <p className="setup-hint">{box.hint}</p>
        )}
      </section>
    );
  }
  const p = d.progress, m = d.measured, s = d.setup, procs = d.procs || {};
  const throttled = d.throttled && d.throttled !== "0x0";
  // Whichever engine is serving: llama-server, or little-gemma's run-cuda-i8.
  const engine = procs.little_gemma ? "little-gemma" : procs.llama_server ? "llama.cpp" : null;
  const model = (procs.little_gemma || procs.llama_server)?.model
    ?.replace(/gemma-4-|-it-qat-UD-Q4_K_XL\.gguf/g, "");
  const activity = procs.lm_eval ? "benchmark" : procs.build ? "building" :
    procs.download ? "downloading" : "idle";
  const live = activity !== "idle";

  return (
    <section className="card device">
      <div className="card-head">
        <div>
          <h2>{box.label}</h2>
          <p className="sub">{box.sub}</p>
        </div>
        <span className={`pill ${live ? "live" : "muted"}`}>
          {live && <i className="dot" />}{activity}
        </span>
      </div>

      {p && <Progress p={p} tag={model ? `${model} · ${engine}` : null} onOpen={() => onOpen(box, p.run)} />}

      {s?.build_pct !== undefined && !s.build_done && (
        <div className="run">
          <div className="run-top">
            <span className="run-name">llama.cpp CUDA build<em> · sm_87</em></span>
            <span className="run-count">{s.build_pct}<i>%</i></span>
          </div>
          <div className="track"><i className="alt" style={{ width: `${s.build_pct}%` }} /></div>
        </div>
      )}

      <div className="kpis">
        <div className="kpi hero">
          <span title="Board DC draw (Pi PMIC rails summed, Jetson INA3221 VDD_IN), excluding power-supply loss; not wall power">power</span>
          <b>{fmt(d.power_w, 2)}<i>W</i></b>
        </div>
        <div className="kpi"><span>cpu</span><b>{fmt(d.cpu_pct, 0)}<i>%</i></b></div>
        <div className={`kpi ${throttled ? "danger" : ""}`}>
          <span>temp</span><b>{fmt(d.temp_c, 1)}<i>°C</i></b>
        </div>
        <div className="kpi"><span>memory</span><b>{fmt(d.mem_used_mb / 1024, 1)}<i>/{fmt(d.mem_total_mb / 1024, 0)}G</i></b></div>
        {d.gpu_pct !== null && d.gpu_pct !== undefined && (
          <div className="kpi gpu" title={`GPU clock ${fmt(d.gpu_mhz)} MHz`}><span>gpu</span><b>{fmt(d.gpu_pct, 0)}<i>%</i></b></div>
        )}
      </div>

      <div className="panels">
        {/* Like gpu below: a series a box never reports (the iPhone has no power or
            temperature sensor) gets no empty chart. */}
        {hist.some((r) => r.power !== null && r.power !== undefined) && (
          <MetricChart data={hist} dataKey="power" color="var(--power)" unit="W"
            label="board power" decimals={2} windowMin={WINDOW_MIN} />
        )}
        <MetricChart data={hist} dataKey="cpu" color="var(--cpu)" unit="%"
          label="cpu utilisation" domainMax={100} windowMin={WINDOW_MIN} />
        {hist.some((r) => r.gpu !== null && r.gpu !== undefined) && (
          <MetricChart data={hist} dataKey="gpu" color="var(--gpu)" unit="%"
            label="gpu utilisation" domainMax={100} windowMin={WINDOW_MIN} />
        )}
        {hist.some((r) => r.temp !== null && r.temp !== undefined) && (
          <MetricChart data={hist} dataKey="temp" color="var(--temp)" unit="°C"
            label="soc temperature" decimals={1} warnAt={80} windowMin={WINDOW_MIN} />
        )}
      </div>

      {d.rails && Object.keys(d.rails).length > 1 && (
        <div className="rails">
          <span className="rails-label">rails</span>
          {Object.entries(d.rails).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => (
            <span key={k} className="rail">{k.replace(/_A$|_V$/, "")} <b>{fmt(v, 2)}W</b></span>
          ))}
        </div>
      )}

      <div className="meta">
        {m?.summary ? (
          <>
            <span>energy <b>{fmt(m.summary.energy_wh, 3)} Wh</b></span>
            <span>idle <b>{fmt(m.summary.idle_w, 2)} W</b></span>
            <span>J/token <b>{fmt(m.summary.j_per_token, 2)}</b></span>
            <span>tok/s/W <b>{fmt(m.summary.tok_s_per_w, 3)}</b></span>
          </>
        ) : m?.samples ? (
          <span>telemetry <b>{fmt(m.samples)}</b> samples · summary after the run</span>
        ) : s?.models?.length ? (
          s.models.map((f) => (
            <span key={f.name}>{f.name.replace(/gemma-4-|-it-qat-UD-Q4_K_XL\.gguf|\.gguf/g, "")} <b>{fmt(f.gb, 2)}GB</b></span>
          ))
        ) : <span>no telemetry yet</span>}
      </div>

      <footer>
        {Object.entries(d.disks || {}).map(([mnt, v]) => (
          <span key={mnt}>{mnt} <b>{fmt(v.free_gb, 0)}G</b></span>
        ))}
        <span className="dim">{d.host} · up {dur(d.uptime_s)}</span>
      </footer>
    </section>
  );
}

export default function Page() {
  const [state, setState] = useState({ boxes: [], ts: null });
  const [err, setErr] = useState(null);
  const [detail, setDetail] = useState(null);   // {box, run}
  const hist = useRef({});

  // The queue is the authority on what is queued, running or blocked; without
  // it the matrix can only guess from process names. It comes from the app's
  // one queue feed (lib/queue-context), and cell() falls back to the process
  // heuristic for a board that did not answer.
  const { boxes: queueBoxes } = useQueue();
  const queues = Object.fromEntries(
    queueBoxes.filter((b) => b.ok).map((b) => [b.id, { jobs: b.jobs }]));

  // The charts' history is a time axis, so a paused tab must come back to a
  // gap, not a line drawn straight across the minutes it was hidden: a null
  // row after the last sample breaks the area (connectNulls is off).
  usePoll(async () => {
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(r.status === 401 ? "no API token — open this page once with ?token=<API_TOKEN>" : j.error);
      const now = j.ts ? new Date(j.ts).getTime() : Date.now();
      for (const b of j.boxes) {
        // a fresh array each tick: Recharts holds on to the one it was
        // handed, and mutating that one throws in dev.
        const prev = hist.current[b.id] || [];
        const last = prev[prev.length - 1];
        const gap = last && now - last.t > 3 * POLL_MS
          ? [{ t: last.t + 1, power: null, cpu: null, temp: null, gpu: null, mem: null, battery: null }] : [];
        const h = [...prev, ...gap, {
          t: now,
          power: b.data?.power_w ?? null,
          cpu: b.data?.cpu_pct ?? null,
          temp: b.data?.temp_c ?? null,
          gpu: b.data?.gpu_pct ?? null,
          mem: b.data?.phone?.footprint_mb ?? null,
          battery: b.data?.phone?.battery_pct ?? null,
        }];
        hist.current[b.id] = h.slice(-HISTORY);
      }
      setState(j); setErr(null);
    } catch (e) { setErr(String(e)); }
  }, POLL_MS);

  const any = state.boxes.some((b) => b.ok);
  return (
    <main>
      <PageHeader title="Monitor">
        <span className={`pill ${any ? "live" : "danger"}`}>
          <i className="dot" />{any ? "polling" : "offline"}
        </span>
        <p className="clock">
          {state.ts ? new Date(state.ts).toLocaleTimeString() : "connecting…"}
          {err ? <em className="warn"> · {err}</em> : null}
        </p>
      </PageHeader>

      {state.boxes.length > 0 && (
        <Matrix boxes={state.boxes} queues={queues} onOpen={(box, run) => setDetail({ box, run })} />
      )}

      <div className="grid">
        {state.boxes.map((b) => {
          const Card = b.id === "iphone" ? PhoneDevice : Device;
          return <Card key={b.id} box={b} hist={hist.current[b.id] || []}
                       onOpen={(box, run) => setDetail({ box, run })} />;
        })}
        {!state.boxes.length && <p className="sub">Connecting to the boards…</p>}
      </div>

      {detail && (
        <RunDetail boxId={detail.box.id} boxLabel={detail.box.label} run={detail.run}
                   onClose={() => setDetail(null)} />
      )}

    </main>
  );
}
