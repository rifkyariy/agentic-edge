"use client";
/* Every chart in the dashboard. Recharts, so axes/tooltips/legends come from
   the library rather than from hand-rolled SVG path strings. */
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export const fmt = (n, d = 0) =>
  n === null || n === undefined || Number.isNaN(n) ? "—"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

const TIP = {
  background: "var(--panel)", border: "1px solid var(--line-2)", borderRadius: "8px",
  font: "11px var(--mono)", padding: "6px 9px", boxShadow: "0 4px 14px rgba(0,0,0,.14)",
};
const axis = { stroke: "var(--line-2)", tick: { fill: "var(--ink-3)", fontSize: 9, fontFamily: "var(--mono)" } };

const clock = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const secs = (t) => `${fmt(t / 60, 0)}m`;

/* Live metric over the polling window: area + line, hover readout. */
export function MetricChart({ data, dataKey, color, unit, label, domainMax, decimals = 0, warnAt, windowMin }) {
  const vals = data.map((r) => r[dataKey]).filter((v) => v !== null && v !== undefined);
  const last = vals.length ? vals[vals.length - 1] : null;
  const hot = warnAt && last !== null && last >= warnAt;
  const id = `g-${dataKey}-${label.replace(/\W/g, "")}`;

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-label">{label}</span>
        <span className="panel-stats">
          {vals.length > 1 && <em>min {fmt(Math.min(...vals), decimals)} · max {fmt(Math.max(...vals), decimals)}</em>}
          <b className={hot ? "hot" : ""} style={{ color: hot ? "var(--danger)" : color }}>
            {fmt(last, decimals)}<i>{unit}</i>
          </b>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={96}>
        <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time"
                 tickFormatter={clock} minTickGap={44} {...axis} />
          <YAxis width={40} tickCount={4}
                 domain={[0, domainMax ?? (warnAt ? (m) => Math.max(m * 1.1, warnAt * 1.05) : "auto")]}
                 tickFormatter={(v) => fmt(v, decimals)} {...axis} />
          {warnAt && <ReferenceLine y={warnAt} stroke="var(--warn)" strokeDasharray="3 3" />}
          <Tooltip contentStyle={TIP} labelFormatter={(t) => new Date(t).toLocaleTimeString()}
                   formatter={(v) => [`${fmt(v, decimals)}${unit}`, label]} isAnimationActive={false} />
          <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.6}
                fill={`url(#${id})`} connectNulls={false} isAnimationActive={false}
                dot={false} activeDot={{ r: 3, strokeWidth: 0 }} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="panel-foot">last {windowMin} minutes</p>
    </div>
  );
}

/* One telemetry channel across a finished run, x in seconds since run start. */
export function TrackChart({ points, dataKey, color, unit, label, domainMax, decimals = 0, span }) {
  const vals = points.map((p) => p[dataKey]).filter((v) => v !== null && v !== undefined);
  if (!vals.length) return null;
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const throttles = points.filter((p) => p.thr);
  return (
    <div className="track-row">
      <div className="track-head">
        <span>{label}</span>
        <b style={{ color }}>
          mean {fmt(mean, decimals)}{unit} · peak {fmt(Math.max(...vals), decimals)}{unit}
        </b>
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <ComposedChart data={points} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="t" type="number" domain={[0, span || "dataMax"]}
                 tickFormatter={secs} minTickGap={40} {...axis} />
          <YAxis width={44} domain={[0, domainMax ?? "auto"]} tickCount={3}
                 tickFormatter={(v) => fmt(v, decimals)} {...axis} />
          <Tooltip contentStyle={TIP} labelFormatter={(t) => `${fmt(t / 60, 1)} min in`}
                   formatter={(v) => [`${fmt(v, decimals)}${unit}`, label]} isAnimationActive={false} />
          {throttles.map((p, i) => (
            <ReferenceLine key={i} x={p.t} stroke="var(--warn)" strokeWidth={1} opacity={0.7} />
          ))}
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.4}
                dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* Per-request: prefill/decode seconds stacked, decode tok/s on the right axis. */
export function TimelineChart({ rows, onPick }) {
  if (!rows?.length) return <p className="sub">No per-request timings recorded for this run.</p>;
  const data = rows.map((r, i) => ({
    n: r.i + 1, i,
    prefill: r.pms / 1000, decode: r.gms / 1000, tps: r.gts,
    pt: r.pt, gt: r.gt, pts: r.pts,
  }));
  const total = data.reduce((a, r) => a + r.prefill + r.decode, 0);
  const med = data.map((r) => r.tps).sort((a, b) => a - b)[Math.floor(data.length / 2)];

  const pick = onPick ? (d) => onPick(d?.i ?? d?.payload?.i) : undefined;

  const tip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const r = payload[0].payload;
    return (
      <div style={TIP}>
        <div><b>#{r.n}</b></div>
        <div>prefill {fmt(r.pt)} tok in {fmt(r.prefill, 1)}s ({fmt(r.pts, 1)} tok/s)</div>
        <div>decode {fmt(r.gt)} tok in {fmt(r.decode, 1)}s ({fmt(r.tps, 2)} tok/s)</div>
        {onPick && <div style={{ color: "var(--ink-3)", marginTop: 3 }}>click for this question</div>}
      </div>
    );
  };

  return (
    <>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 10, right: 6, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="n" type="category" interval="preserveStartEnd" minTickGap={30}
                 tickFormatter={(n) => `#${n}`} {...axis} />
          <YAxis yAxisId="s" width={44} tickFormatter={(v) => `${fmt(v)}s`} {...axis} />
          <YAxis yAxisId="t" orientation="right" width={40} tickFormatter={(v) => fmt(v, 1)}
                 stroke="var(--violet)" tick={{ ...axis.tick, fill: "var(--violet)" }} />
          <Tooltip content={tip} cursor={{ fill: "var(--line)", opacity: 0.5 }} isAnimationActive={false} />
          <Legend verticalAlign="bottom" height={26} iconType="square"
                  wrapperStyle={{ font: "11px var(--mono)", color: "var(--ink-3)" }} />
          <Bar yAxisId="s" dataKey="decode" name="decode" stackId="a" fill="var(--power)"
               isAnimationActive={false} onClick={pick} cursor={onPick ? "pointer" : undefined} />
          <Bar yAxisId="s" dataKey="prefill" name="prefill" stackId="a" fill="var(--cpu)"
               isAnimationActive={false} onClick={pick} cursor={onPick ? "pointer" : undefined} />
          <Line yAxisId="t" type="monotone" dataKey="tps" name="decode tok/s" stroke="var(--violet)"
                strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="tl-sum">
        {rows.length} requests · {fmt(total / 60)} min of model time · median {fmt(med, 2)} tok/s
      </p>
    </>
  );
}
