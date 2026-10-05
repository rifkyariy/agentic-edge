"use client";
import { useEffect, useState } from "react";
import { Check, RotateCcw } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt } from "../lib/format";
import { PLAN } from "../lib/plan";
import { collectRuns } from "../lib/timing";

const DEVICES = [["pi", "Pi 5"], ["jetson", "Orin Nano"], ["iphone", "iPhone"]];
const COLOR = { pi: "var(--pi)", jetson: "var(--jetson)", iphone: "var(--iphone)" };
const MODELS = [["e2b", "E2B"], ["e4b", "E4B"]];
const THINKING = [["off", "Thinking off"], ["on", "Thinking on"]];
const ENGINE_LABEL = { "llama.cpp": "llama.cpp", "little-gemma": "little-gemma",
                       turboquant: "TurboQuant", mlx: "MLX" };
const engineLabel = (e) => ENGINE_LABEL[e] || (e.startsWith("ae-") ? `proposed · ${e.slice(3)}` : e);

// Total hours: the time a setup cost on a device, summed over the subsets
// shown — all three (300 questions) by default, or one 100-question run.
const U = { label: "total hours", unit: "h", d: 1 };
const SUBSETS = [["all", "All (s1–s3)"], ["s1", "s1"], ["s2", "s2"], ["s3", "s3"]];

// A round upper bound, so both models' charts share one readable scale.
const niceMax = (v) => {
  if (!(v > 0)) return 1;
  const step = 10 ** Math.floor(Math.log10(v));
  return [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((k) => k * step).find((x) => x >= v);
};

const TIP = {
  background: "var(--panel)", border: "1px solid var(--line-2)", borderRadius: "8px",
  padding: "8px 10px", boxShadow: "0 4px 14px rgba(0,0,0,.14)", font: "11.5px var(--mono)",
};

// The category label: the engine, and under it the thinking mode.
function SetupTick({ x, y, payload, data }) {
  const row = data[payload.index];
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={-8} y={-2} textAnchor="end" className="tt-tick">{payload.value}</text>
      <text x={-8} y={12} textAnchor="end" className="tt-tick sub">thinking {row?.think}</text>
    </g>
  );
}

// Hovering a setup reads out every device for it, against the fastest.
function TimeTip({ active, payload, cols }) {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  return (
    <div style={TIP}>
      <b className="tt-tip-head">{row.name} · thinking {row.think}</b>
      {cols.map(([id, l]) => {
        const c = row.cells[id];
        if (!c) return null;
        const best = row.best === id;
        return (
          <div key={id} className="tt-tip-row">
            <i style={{ background: COLOR[id] }} />
            <span>{l}</span>
            <b>{fmt(c.v, U.d)} {U.unit}</b>
            <em>{best ? "fastest" : row.best ? `${fmt(c.v / row.cells[row.best].v, 1)}× slower` : ""}
              {c.n < c.of && ` · only ${c.n} of ${c.of} subsets`}</em>
          </div>
        );
      })}
    </div>
  );
}

/* One horizontal bar chart per model, on a shared scale: setups down the side,
   one bar per device, the time written at the end of each bar and the fastest
   ticked. Short bars win, so the eye goes to the shortest in each group. */
function TimeCharts({ rows, cols }) {
  const models = [...new Set(rows.map((r) => r.m))];
  const max = niceMax(Math.max(0, ...rows.flatMap((r) => cols.map(([id]) => r.cells[id]?.v ?? 0))));
  const bar = 12, gap = 2;
  const band = cols.length * bar + (cols.length - 1) * gap + 16;
  // Room for the value label, and for the warning when a total is short.
  const short = rows.some((r) => cols.some(([id]) => r.cells[id] && r.cells[id].n < r.cells[id].of));
  return (
    <div className="tt-charts">
      {models.map((m) => {
        const rs = rows.filter((r) => r.m === m);
        const data = rs.map((r) => ({
          name: engineLabel(r.e), think: r.t, best: r.best, cells: r.cells,
          ...Object.fromEntries(cols.map(([id]) => [id, r.cells[id]?.v ?? null])),
        }));
        return (
          <figure key={m} className="tt-chart">
            <figcaption><b>{rs[0].ml}</b><span>{U.label}</span></figcaption>
            <ResponsiveContainer width="100%" height={data.length * band + 30}>
              <BarChart data={data} layout="vertical" barGap={gap} barCategoryGap={8}
                        margin={{ top: 0, right: short ? 150 : 70, bottom: 0, left: 0 }}>
                <CartesianGrid horizontal={false} stroke="var(--line)" />
                <XAxis type="number" domain={[0, max]} allowDecimals={false} stroke="var(--line-2)"
                       tick={{ fill: "var(--ink-3)", fontSize: 10, fontFamily: "var(--mono)" }}
                       tickFormatter={(v) => fmt(v, Number.isInteger(v) ? 0 : 1)} />
                <YAxis type="category" dataKey="name" width={124} axisLine={false} tickLine={false}
                       interval={0} tick={<SetupTick data={data} />} />
                <Tooltip content={<TimeTip cols={cols} />} isAnimationActive={false}
                         cursor={{ fill: "var(--ink)", opacity: 0.05 }} />
                {cols.map(([id]) => (
                  <Bar key={id} dataKey={id} fill={COLOR[id]} barSize={bar} radius={[0, 4, 4, 0]}
                       isAnimationActive={false}>
                    {/* Recharts numbers labels over the bars it drew, skipping devices
                        with no run, so `index` is not a row index. Hand the label its
                        own row instead (valueAccessor without a dataKey). */}
                    <LabelList valueAccessor={(entry) => entry.payload} content={({ x, y, width, height, value: row }) => {
                      const c = row?.cells?.[id];
                      if (!c) return null;
                      const best = row.best === id;
                      const partial = c.n < c.of;
                      const tx = x + width + 6, ty = y + height / 2;
                      return (
                        <g>
                          {best && <Check x={tx} y={ty - 6} width={12} height={12}
                                          stroke="var(--better)" strokeWidth={3} />}
                          <text x={tx + (best ? 15 : 0)} y={ty} dy="0.35em"
                                className={`tt-barlab ${best ? "best" : ""}`}>
                            {fmt(c.v, U.d)} h{partial && <tspan className="tt-few"> · {c.n}/{c.of} subsets</tspan>}
                          </text>
                        </g>
                      );
                    }} />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </figure>
        );
      })}
    </div>
  );
}

/* A row of toggle chips. Every value starts on (state null means "all");
   clicking flips one, and the last one on cannot be turned off, so a filter
   never empties the table. */
function Toggles({ label, options, on, set }) {
  return (
    <div className="tt-filter">
      <span>{label}</span>
      <div className="chips" role="group" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={on.includes(v)}
                  onClick={() => set((prev) => {
                    const cur = prev ?? options.map(([x]) => x);
                    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
                    return next.length ? options.map(([x]) => x).filter((x) => next.includes(x)) : prev;
                  })}>{l}</button>
        ))}
      </div>
    </div>
  );
}

// One of several, for the subset and the view.
function Choice({ label, options, value, set }) {
  return (
    <div className="tt-filter">
      <span>{label}</span>
      <div className="chips" role="radiogroup" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v}
                  aria-pressed={value === v} onClick={() => set(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

/* How long each model takes on each device, per engine and thinking mode.
   A chart by default, the same numbers as a table one click away. In the
   table, rows are the setups and columns the devices; the fastest in a row
   gets a tick, and every other cell says how many times slower it is. */
export default function TimeTable() {
  const [runs, setRuns] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    fetch("/api/history", { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => setRuns(collectRuns(j.boxes.filter((b) => b.ok !== false))))
      .catch((e) => setErr(String(e)));
  }, []);

  const engines = runs
    ? PLAN.engines.map((e) => e.id).filter((e) => runs.some((r) => r.engine === e)) : [];
  const devices = runs ? DEVICES.filter(([id]) => runs.some((r) => r.box === id)) : [];

  const [dev, setDev] = useState(null);
  const [model, setModel] = useState(MODELS.map(([v]) => v));
  const [eng, setEng] = useState(null);
  const [think, setThink] = useState(THINKING.map(([v]) => v));
  const [subset, setSubset] = useState("all");
  const [view, setView] = useState("chart");
  // Engines and devices are known only once the runs arrive; until the reader
  // touches them, "all of them" is the filter.
  const devOn = dev ?? devices.map(([id]) => id);
  const engOn = eng ?? engines;
  const filtered = dev || eng || model.length < 2 || think.length < 2
    || subset !== "all" || view !== "chart";
  const reset = () => {
    setDev(null); setEng(null); setModel(MODELS.map(([v]) => v));
    setThink(THINKING.map(([v]) => v)); setSubset("all"); setView("chart");
  };

  const cols = devices.filter(([id]) => devOn.includes(id));
  const value = (box, e, m, t) => {
    const v = runs.filter((r) => r.box === box && r.engine === e && r.model === m && r.thinking === t
      && (subset === "all" || r.subset === subset));
    if (!v.length) return null;
    const mins = v.map((r) => r.minutes);
    return { v: mins.reduce((a, b) => a + b, 0) / 60, of: subset === "all" ? 3 : 1,
             n: v.length, runs: v.map((r) => r.run) };
  };

  const rows = runs ? MODELS.filter(([m]) => model.includes(m)).flatMap(([m, ml]) =>
    engines.filter((e) => engOn.includes(e)).flatMap((e) =>
      THINKING.filter(([t]) => think.includes(t)).map(([t, tl]) => {
        const cells = Object.fromEntries(cols.map(([id]) => [id, value(id, e, m, t)]));
        const have = cols.filter(([id]) => cells[id]);
        if (!have.length) return null;
        const best = have.length > 1
          ? have.reduce((a, b) => (cells[b[0]].v < cells[a[0]].v ? b : a))[0] : null;
        return { key: `${m}-${e}-${t}`, m, ml, e, t, tl, cells, best };
      }))).filter(Boolean) : [];

  return (
    <section className="card timetable">
      <div>
        <h2>How long it takes</h2>
        <p className="sub">Total wall-clock hours for all 300 MMLU-Pro questions (three
          100-question subsets), by model, setup and device. Shorter bars are faster.</p>
      </div>

      {err && <p className="pre-error"><b>{err}</b></p>}
      {!runs && !err && <p className="sub">Reading every run from the boards…</p>}

      {runs && (
        <>
          <div className="tt-filters">
            <Toggles label="Device" options={devices} on={devOn} set={setDev} />
            <Toggles label="Model" options={MODELS} on={model} set={setModel} />
            <Toggles label="Engine" options={engines.map((e) => [e, engineLabel(e)])} on={engOn} set={setEng} />
            <Toggles label="Thinking" options={[["off", "off"], ["on", "on"]]} on={think} set={setThink} />
            <Choice label="Subset" options={SUBSETS} value={subset} set={setSubset} />
            <Choice label="View" value={view} set={setView}
                    options={[["chart", "chart"], ["table", "table"]]} />
            {filtered && (
              <button type="button" className="tt-reset" onClick={reset}>
                <RotateCcw className="ic" /> reset
              </button>
            )}
          </div>

          {rows.length > 0 && view === "chart" && (
            <ul className="vs-key">
              {cols.map(([id, l]) => <li key={id}><i style={{ background: COLOR[id] }} />{l}</li>)}
              {cols.length > 1 && <li><Check className="ic" /> fastest</li>}
            </ul>
          )}
          {rows.length === 0 ? (
            <p className="empty">No finished runs match these filters.</p>
          ) : view === "chart" ? (
            <TimeCharts rows={rows} cols={cols} />
          ) : (
            <div className="table-wrap">
              <table className="tt">
                <thead>
                  <tr>
                    <th>Model</th><th>Engine</th><th>Thinking</th>
                    {cols.map(([id, l]) => <th key={id} className="num">{l}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const first = i === 0 || rows[i - 1].m !== r.m;
                    return (
                      <tr key={r.key} className={first ? "tt-first" : ""}>
                        <th>{first ? r.ml : ""}</th>
                        <td>{engineLabel(r.e)}</td>
                        <td className="tt-think">{r.t}</td>
                        {cols.map(([id]) => {
                          const c = r.cells[id];
                          if (!c) return <td key={id} className="num tt-none">—</td>;
                          const fastest = r.best === id;
                          const slower = r.best && !fastest ? c.v / r.cells[r.best].v : null;
                          return (
                            <td key={id} className={`num ${fastest ? "tt-best" : ""}`}
                                title={`${c.n} run${c.n > 1 ? "s" : ""}: ${c.runs.join(", ")}`}>
                              <b>{fastest && <Check className="ic" aria-label="fastest" />}{fmt(c.v, U.d)}<i>{U.unit}</i></b>
                              {slower && <em>{fmt(slower, 1)}× slower</em>}
                              {c.n < c.of && <em className="tt-few">only {c.n} of {c.of} subsets</em>}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="foot">Shorter is faster; the fastest device for each setup is ticked.
            {view === "chart" ? " Hover a setup for every device side by side." : " Hover a cell for the runs it sums."}
            {" "}Only finished runs count — smoke tests, failed and superseded runs are left out.</p>
        </>
      )}
    </section>
  );
}
