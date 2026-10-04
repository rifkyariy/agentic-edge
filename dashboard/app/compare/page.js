"use client";
import { useEffect, useState } from "react";
import {
  Check, Gauge, Lightbulb, MemoryStick, Plug, Target, Thermometer, Zap,
} from "lucide-react";
import { fmt } from "../lib/format";
import PageHeader from "../components/PageHeader";
import { comparisons } from "../lib/paired";
import Paired from "./Paired";

const MODELS = [["e2b", "Gemma 4 E2B"], ["e4b", "Gemma 4 E4B"]];
const DEV = {
  pi: { label: "Raspberry Pi 5", short: "Pi 5", color: "var(--pi)" },
  jetson: { label: "Jetson Orin Nano", short: "Orin Nano", color: "var(--jetson)" },
  iphone: { label: "iPhone", short: "iPhone", color: "var(--iphone)" },
};

/* One run per (device, model, subset). The Pi has runs named without a subset
   from before the subsets existed — those are s1, but an explicit -s1 wins. */
function canonical(runs) {
  const by = {};
  for (const r of runs) {
    const k = `${r.model}-${r.subset}`;
    const explicit = /-s\d$/.test(r.run);
    if (!by[k] || (explicit && !/-s\d$/.test(by[k].run))) by[k] = r;
  }
  return by;
}

const mean = (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : null);

/* Pooled across the subsets that have finished. Uncertainty comes from question
   sampling, so the 95% interval is on the pooled n, not an average of the
   per-subset ones. */
function pooled(rows) {
  const scored = rows.filter((r) => r.score !== null && r.score !== undefined);
  if (!scored.length) return null;
  const n = scored.length * 100;
  const p = mean(scored.map((r) => r.score)) / 100;
  return { pct: p * 100, n, subsets: scored.length,
           ci95: 1.96 * Math.sqrt((p * (1 - p)) / n) * 100 };
}

/* One answer per measure, in big type: the thing a reader came for. */
function Headline({ icon: Icon, label, big, who, color, detail }) {
  return (
    <div className="hl">
      <span className="hl-label"><Icon className="ic" /> {label}</span>
      <b className="hl-big" style={color ? { color } : undefined}>{big}</b>
      <span className="hl-who">{who}</span>
      {detail && <span className="hl-detail">{detail}</span>}
    </div>
  );
}

/* Side by side on one shared scale per measure, every bar labelled with its
   value. Bars carry the device's own colour, so the legend is the same on every
   card; which one is better is a tick next to the number, never colour alone.
   "Better" is decided only by `goodWhen`, and a tie must be passed in (`tied`,
   from the paired test) rather than inferred from a small gap, so a
   statistical dead heat is never marked as a win. */
function Versus({ title, unit, rows, decimals = 1, goodWhen = "higher", tied = false,
                  verdict, ids = ["pi", "jetson"] }) {
  const max = Math.max(0, ...rows.flatMap((r) => ids.map((id) => r[id] ?? 0))) || 1;
  return (
    <figure className="vs">
      <figcaption><h3>{title}</h3><span>{unit}</span></figcaption>
      {rows.map((r, i) => {
        const tie = Array.isArray(tied) ? tied[i] : tied;
        const have = ids.filter((id) => r[id] != null);
        const best = tie || have.length < 2 ? null : have.reduce((x, y) =>
          ((goodWhen === "lower" ? r[y] < r[x] : r[y] > r[x]) ? y : x));
        return (
          <div className="vs-group" key={r.label ?? i}>
            {r.label && <span className="vs-model">{r.label}</span>}
            {ids.map((id) => (
              <div key={id} className={`vs-row ${best === id ? "best" : ""}`}>
                <span className="vs-dev">{DEV[id].short}</span>
                <span className="vs-track">
                  <i style={{ width: `${r[id] == null ? 0 : (100 * r[id]) / max}%`, background: DEV[id].color }} />
                </span>
                <b>{fmt(r[id], decimals)}{best === id && <Check className="ic" aria-label="better" />}</b>
              </div>
            ))}
          </div>
        );
      })}
      {verdict && <p className="vs-verdict">{verdict}</p>}
    </figure>
  );
}

// iOS's ProcessInfo.ThermalState, the phone's only heat signal.
const THERMAL = ["nominal", "fair", "serious", "critical"];

/* The iPhone against both boards, baseline only. Not the same experiment as
   Pi vs Orin: the engine (MLX, not llama.cpp) and the quantisation (MLX 4-bit
   of the same QAT checkpoint) differ too, and its energy is whole-phone battery
   drain, usually estimated from battery %. So it gets its own card, with those
   differences named, instead of a third bar in the board charts. */
function PhoneCompare({ rowsFor, devMean }) {
  const ids = ["pi", "jetson", "iphone"];
  if (!MODELS.some(([m]) => rowsFor("iphone", m).length)) return null;
  const estimated = MODELS.some(([m]) => rowsFor("iphone", m)
    .some((r) => r.device?.energy_source?.startsWith("estimate")));
  const rows = (f) => MODELS.map(([m, label]) =>
    ({ label, ...Object.fromEntries(ids.map((id) => [id, f(id, m)])) }));
  const dev = (key) => rows((id, m) => devMean(id, m, key));
  const heat = MODELS.map(([m]) => {
    const v = rowsFor("iphone", m).map((r) => r.device?.thermal_max).filter((x) => x != null);
    return v.length ? THERMAL[Math.max(...v)] ?? "—" : "—";
  });
  return (
    <section className="card">
      <div>
        <h2>iPhone against the boards</h2>
        <p className="sub">Same questions on MLX, thinking off. The engine and quantisation differ
          too, so this compares device and runtime together.</p>
      </div>
      <div className="vs-grid">
        <Versus title="Accuracy" unit="% correct" ids={ids} tied
                rows={rows((id, m) => pooled(rowsFor(id, m))?.pct)}
                verdict="Paired tests above decide any winner" />
        <Versus title="Decode speed" unit="tokens / s" ids={ids} rows={dev("decode_tok_s")} />
        <Versus title="Energy per token" unit={estimated ? "J · iPhone estimated" : "J"} ids={ids}
                decimals={2} goodWhen="lower" rows={dev("j_per_token")} />
      </div>
      <p className="foot">iPhone worst thermal state: E2B {heat[0]}, E4B {heat[1]}.
        {estimated && " iPhone energy is whole-phone battery drain estimated from battery %, at 1% resolution; the boards' is measured board DC draw. Compare the order of magnitude, not decimals."}</p>
    </section>
  );
}

export default function Compare() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  // Per-question answers for the paired tests. Its own request: reading every
  // samples file is slower than /api/baseline, and the page should not wait.
  const [pairedData, setPaired] = useState(null);
  const [pairedErr, setPairedErr] = useState(null);
  useEffect(() => {
    fetch("/api/compare", { cache: "no-store" })
      .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.error); return j; })
      .then((j) => setPaired({
        ...comparisons(j.boxes.filter((b) => b.ok)),
        ts: j.ts,
        unreachable: j.boxes.filter((b) => !b.ok)
          .map((b) => `${b.label} (${b.error}${b.hint ? ` — ${b.hint}` : ""})`),
      }))
      .catch((e) => setPairedErr(String(e)));
  }, []);

  useEffect(() => {
    fetch("/api/baseline", { cache: "no-store" })
      .then((r) => r.json())
      .then(setD)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <main><p className="err">{err}</p></main>;
  if (!d) return <main><p className="sub">Reading both boards…</p></main>;

  const runs = Object.fromEntries(d.boxes.map((b) => [b.id, canonical(b.runs || [])]));

  const rowsFor = (id, model) =>
    ["s1", "s2", "s3"].map((s) => runs[id]?.[`${model}-${s}`]).filter(Boolean);
  const devMean = (id, model, key) => {
    const v = rowsFor(id, model).map((r) => r.device?.[key])
      .filter((x) => x !== null && x !== undefined);
    return v.length ? mean(v) : null;
  };

  const series = (key) => MODELS.map(([m, label]) => ({
    label: label.replace("Gemma 4 ", ""),
    pi: devMean("pi", m, key), jetson: devMean("jetson", m, key),
  }));

  const acc = MODELS.map(([m, label]) => ({
    label: label.replace("Gemma 4 ", ""),
    pi: pooled(rowsFor("pi", m))?.pct ?? null, jetson: pooled(rowsFor("jetson", m))?.pct ?? null,
  }));

  /* Who leads on a measure, and by how much — computed from the runs, never
     written down. Only a lead on both models counts; otherwise it is mixed. */
  const lead = (key, goodWhen = "higher") => {
    const pairs = MODELS.map(([m]) => [devMean("pi", m, key), devMean("jetson", m, key)])
      .filter(([p, j]) => p && j);
    if (!pairs.length) return null;
    const better = (x, y) => (goodWhen === "lower" ? x < y : x > y);
    const id = pairs.every(([p, j]) => better(p, j)) ? "pi"
      : pairs.every(([p, j]) => better(j, p)) ? "jetson" : null;
    return { id, x: mean(pairs.map(([p, j]) => Math.max(p, j) / Math.min(p, j))) };
  };
  const speed = lead("decode_tok_s");
  const energy = lead("j_per_token", "lower");
  const power = lead("mean_w", "lower");
  const perW = lead("tok_s_per_w");
  const tempGap = mean(MODELS.map(([m]) => devMean("pi", m, "temp_max") - devMean("jetson", m, "temp_max"))
    .filter((v) => !Number.isNaN(v)));
  const name = (l) => (l?.id ? DEV[l.id].short : "neither");
  const color = (l) => (l?.id ? DEV[l.id].color : undefined);

  /* Campaign totals: what running the whole grid actually cost each board.
     canonical() has already dropped the Pi's duplicate pre-subset directory,
     so nothing is counted twice. */
  const totals = (id) => {
    const rows = MODELS.flatMap(([m]) => rowsFor(id, m));
    const sum = (f) => rows.reduce((a, r) => a + (f(r) || 0), 0);
    const idle = rows.map((r) => r.device?.idle_w).filter(Boolean);
    return {
      runs: rows.length,
      minutes: sum((r) => r.minutes),
      wh: sum((r) => r.device?.energy_wh),
      tokens: sum((r) => r.device?.gen_tokens),
      idle_w: idle.length ? mean(idle) : null,
    };
  };
  const T = { pi: totals("pi"), jetson: totals("jetson") };

  /* Where the trade turns over. Under load the Orin is far cheaper per token;
     at rest it costs more than twice what the Pi does. Over a 24h day doing T
     tokens, total energy is work + idle for the remainder, and the two curves
     cross at the token count below which the Pi's low floor wins. */
  const breakeven = (() => {
    const g = (id, k) => devMean(id, "e2b", k);
    const [pd, pw, pi_] = [g("pi", "decode_tok_s"), g("pi", "mean_w"), T.pi.idle_w];
    const [jd, jw, ji] = [g("jetson", "decode_tok_s"), g("jetson", "mean_w"), T.jetson.idle_w];
    if (![pd, pw, pi_, jd, jw, ji].every(Boolean)) return null;
    const day = 86400;
    const slopeP = (pw - pi_) / pd, slopeJ = (jw - ji) / jd;
    if (slopeP <= slopeJ) return null;
    const tokens = (day * (ji - pi_)) / (slopeP - slopeJ);
    // What each board could produce decoding flat out for 24h. The Pi's
    // ceiling sits close to the crossover, which bounds how much of the
    // "Orin wins on energy" range is even reachable on a Pi.
    return { tokens, piHours: tokens / pd / 3600, jetHours: tokens / jd / 3600,
             piCeiling: pd * day, jetCeiling: jd * day };
  })();

  const gpu = {
    mean: devMean("jetson", "e4b", "gpu_mean"),
    max: devMean("jetson", "e4b", "gpu_max"),
    mhz: devMean("jetson", "e4b", "gpu_mhz_mean"),
  };

  // The baseline accuracy verdict, from the paired test rather than typed in:
  // tied only while neither model's McNemar p falls below alpha.
  const [pE2b, pE4b] = pairedData?.board[0].groups || [];
  const accP = pE2b?.pooled && pE4b?.pooled ? [pE2b.pooled, pE4b.pooled] : null;
  const accTied = accP ? accP.every((r) => !r.sig) : true;
  const accLine = accP
    ? `E2B ${fmt(accP[0].aAcc, 1)} vs ${fmt(accP[0].bAcc, 1)}% · E4B ${fmt(accP[1].aAcc, 1)} vs ${fmt(accP[1].bAcc, 1)}%`
    : `E2B ${fmt(acc[0].pi, 1)} vs ${fmt(acc[0].jetson, 1)}% · E4B ${fmt(acc[1].pi, 1)} vs ${fmt(acc[1].jetson, 1)}%`;

  const pending = MODELS.flatMap(([m, label]) =>
    Object.entries(runs).filter(([id]) => id !== "iphone").flatMap(([id, r]) =>
      ["s1", "s2", "s3"].filter((s) => !r[`${m}-${s}`]?.score)
        .map((s) => `${DEV[id].short} ${label} ${s}`)));

  const allRuns = d.boxes.flatMap((b) => MODELS.flatMap(([m]) => ["s1", "s2", "s3"]
    .map((s) => ({ b, m, s, r: runs[b.id]?.[`${m}-${s}`] })))).filter((x) => x.r);

  return (
    <main className="cmp">
      <PageHeader title="Compare"
                  sub="Pi 5 against Orin Nano, same MMLU-Pro questions, same model files." />

      {/* The short answer: one sentence, then one card per measure. */}
      <section className="card answer">
        <p className="answer-lede">
          <b>{accTied ? "Same accuracy." : "Accuracy differs."}</b>{" "}
          The {name(speed)} is <b>{fmt(speed?.x, 1)}× faster</b> and{" "}
          {energy?.id === speed?.id ? "" : `the ${name(energy)} `}
          <b>{fmt(energy?.x, 1)}× cheaper per token</b>. The {name(power)} draws less power,
          idles lower and has memory to spare.
        </p>
        <div className="hl-grid">
          <Headline icon={Target} label="Accuracy" big={accTied ? "Tie" : "Differ"}
                    color={accTied ? "var(--ink-3)" : undefined}
                    who={accTied ? "no real difference" : "a significant difference"}
                    detail={accLine} />
          <Headline icon={Gauge} label="Speed" big={`${fmt(speed?.x, 1)}×`} color={color(speed)}
                    who={`faster on the ${name(speed)}`} detail="tokens generated per second" />
          <Headline icon={Zap} label="Energy per token" big={`${fmt(energy?.x, 1)}×`} color={color(energy)}
                    who={`cheaper on the ${name(energy)}`} detail="joules for each word-piece" />
          <Headline icon={Plug} label="Power draw" big={`${fmt(power?.x, 1)}×`} color={color(power)}
                    who={`lower on the ${name(power)}`} detail="watts while working" />
          <Headline icon={Thermometer} label="Heat" big={`${fmt(Math.abs(tempGap))} °C`}
                    color={tempGap > 0 ? DEV.jetson.color : DEV.pi.color}
                    who={`cooler on the ${tempGap > 0 ? "Orin Nano" : "Pi 5"}`} detail="peak, neither throttled" />
          <Headline icon={MemoryStick} label="Memory headroom" big="3.9 GB" color={DEV.pi.color}
                    who="spare on the Pi 5" detail="Orin: 165 MB, OOM-killed twice" />
        </div>
      </section>

      {/* The same measures as bars, one card each. */}
      <section className="card">
        <div className="card-head">
          <div>
            <h2>Side by side</h2>
            <p className="sub">Averaged over three 100-question runs per model.</p>
          </div>
          <ul className="vs-key">
            <li><i style={{ background: DEV.pi.color }} />Pi 5</li>
            <li><i style={{ background: DEV.jetson.color }} />Orin Nano</li>
            <li><Check className="ic" /> better</li>
          </ul>
        </div>
        <div className="vs-grid">
          {/* tied comes from the paired test, never from the size of the gap:
              a 1-point bar gap is not a win and is not drawn as one. */}
          <Versus title="Accuracy" unit="% correct" rows={acc}
                  tied={accP ? accP.map((r) => !r.sig) : true}
                  verdict={accTied ? "Within noise: no winner" : "Significant on at least one model"} />
          <Versus title="Speed" unit="tokens / s" rows={series("decode_tok_s")} decimals={1}
                  verdict={`${name(speed)} ${fmt(speed?.x, 1)}× faster`} />
          <Versus title="Energy per token" unit="joules, lower is better" rows={series("j_per_token")}
                  decimals={2} goodWhen="lower"
                  verdict={`${name(energy)} ${fmt(energy?.x, 1)}× cheaper`} />
          <Versus title="Work per watt" unit="tokens / s / W" rows={series("tok_s_per_w")} decimals={2}
                  verdict={`${name(perW)} ${fmt(perW?.x, 1)}× more`} />
          <Versus title="Power while working" unit="watts, lower is better" rows={series("mean_w")}
                  decimals={1} goodWhen="lower"
                  verdict={`${name(power)} draws less, but for far longer`} />
          <Versus title="Peak temperature" unit="°C, lower is better" rows={series("temp_max")}
                  decimals={0} goodWhen="lower" verdict="Neither board throttled" />
        </div>
      </section>

      <Paired data={pairedData} err={pairedErr} />

      {/* Totals, because per-token rates hide what a campaign actually costs. */}
      <section className="card">
        <div>
          <h2>What the whole benchmark cost</h2>
          <p className="sub">All {T.pi.runs} baseline runs per board, {fmt(T.pi.runs * 100)} questions.
            Both did the same work: {fmt(T.pi.tokens / 1000)}k vs {fmt(T.jetson.tokens / 1000)}k tokens.</p>
        </div>
        <div className="vs-grid">
          <Versus title="Time" unit="hours" decimals={1} goodWhen="lower"
                  rows={[{ pi: T.pi.minutes / 60, jetson: T.jetson.minutes / 60 }]}
                  verdict={`${fmt(T.pi.minutes / T.jetson.minutes, 1)}× quicker on the Orin`} />
          <Versus title="Energy used" unit="Wh" decimals={0} goodWhen="lower"
                  rows={[{ pi: T.pi.wh, jetson: T.jetson.wh }]}
                  verdict={`${fmt(T.pi.wh / T.jetson.wh, 1)}× less on the Orin`} />
          <Versus title="Idle draw" unit="watts at rest" decimals={2} goodWhen="lower"
                  rows={[{ pi: T.pi.idle_w, jetson: T.jetson.idle_w }]}
                  verdict={`${fmt(T.jetson.idle_w / T.pi.idle_w, 1)}× lower on the Pi`} />
        </div>

        {breakeven && (
          <>
            <p className="callout">
              <Lightbulb className="ic" />
              <span>
                <b>Rule of thumb:</b> a board busy for more than about{" "}
                <b>{fmt(breakeven.tokens / 1000)}k tokens a day</b> uses less energy as an
                Orin. Below that, the Pi wins, because the Orin idles at{" "}
                {fmt(T.jetson.idle_w / T.pi.idle_w, 1)}× its draw. Answering all day: Orin.
                Waiting for a wake word: Pi.
              </span>
            </p>
            <details className="tradeoff">
              <summary>How that is worked out</summary>
              <p>
                It idles at {fmt(T.jetson.idle_w, 2)} W against the Pi&apos;s{" "}
                {fmt(T.pi.idle_w, 2)} W. Over a 24-hour day the two cross at roughly{" "}
                <b>{fmt(breakeven.tokens / 1000)}k generated tokens</b> — about{" "}
                {fmt(breakeven.jetHours, 1)} h of Orin decoding, or{" "}
                {fmt(breakeven.piHours, 1)} h of the Pi&apos;s.
              </p>
              <p>
                That sits near the Pi&apos;s ceiling: flat out for a whole day it tops
                out at <b>{fmt(breakeven.piCeiling / 1000)}k tokens</b> against the
                Orin&apos;s <b>{fmt(breakeven.jetCeiling / 1000)}k</b>, so break-even already
                takes {fmt(100 * breakeven.piHours / 24)}% of the Pi&apos;s day. Past that the
                question is not which board is cheaper but whether the Pi can keep up.
              </p>
              <p className="tradeoff-note">
                From these runs&apos; E2B decode rate, working watts and idle baseline.
                Assumes the board is idle whenever it is not decoding, so it is a floor
                for the Orin rather than an exact duty cycle.
              </p>
            </details>
          </>
        )}
      </section>

      {/* What the Orin actually brings: the GPU the Pi does not have. */}
      <section className="card gpucard">
        <div>
          <h2>Why the Orin is faster</h2>
          <p className="sub">Its GPU does the work. The Pi has no CUDA device, so its CPU does.</p>
        </div>
        <div className="tiles">
          <div className="tile">
            <span className="tile-label">Orin GPU busy</span>
            <b className="tile-value" style={{ color: "var(--jetson)" }}>
              {fmt(gpu.mean, 1)}<i>%</i></b>
            <em className="delta flat">{fmt(Math.min(100, gpu.max), 0)}% peak · E4B runs</em>
          </div>
          <div className="tile">
            <span className="tile-label">Orin CPU busy</span>
            <b className="tile-value" style={{ color: "var(--jetson)" }}>
              {fmt(devMean("jetson", "e4b", "cpu_mean"), 1)}<i>%</i></b>
            <em className="delta flat">every layer on the GPU</em>
          </div>
          <div className="tile">
            <span className="tile-label">Pi CPU busy</span>
            <b className="tile-value" style={{ color: "var(--pi)" }}>
              {fmt(devMean("pi", "e4b", "cpu_mean"), 0)}<i>%</i></b>
            <em className="delta flat">doing all of it</em>
          </div>
          <div className="tile">
            <span className="tile-label">GPU clock</span>
            <b className="tile-value">{fmt(gpu.mhz, 0)}<i>MHz</i></b>
            <em className="delta flat">306–612 MHz observed</em>
          </div>
        </div>

        <details className="gpunote">
          <summary>GPU and memory notes</summary>
          <p>
            <b>Ampere GPU, sm_87</b>, on a Jetson Orin Nano Super in its <b>15 W</b> mode.
            llama.cpp is built for sm_87 and offloads every layer (<code>-ngl 99</code>).
          </p>
          <p>
            Memory is the catch, and not capacity: <b>8,062 MB</b> on the Pi against{" "}
            <b>7,485 MB</b> on the Orin. The Pi mmaps the model, so the weights sit in
            evictable page cache and an E4B run peaks at <b>4,118–4,294 MB</b> in use. The
            Orin pins them in its shared pool, which has no swap: E4B peaked at{" "}
            <b>6,874–7,320 MB</b>, leaving as little as <b>165 MB</b>. Two E4B runs were
            OOM-killed when a second user logged in; both are kept under{" "}
            <code>stdbench/failed/</code>. So <code>queue_jetson.sh</code> refuses to start
            E4B below 5,400 MB free. The Pi&apos;s limit is speed, the Orin&apos;s is memory.
          </p>
        </details>
      </section>

      <PhoneCompare rowsFor={rowsFor} devMean={devMean} />

      {/* The fine print: one line each until opened. */}
      <details className="card design fold">
        <summary><h2>Setup</h2><span>question set, models, serving flags, power method</span></summary>
        <dl className="design-grid">
          <div><dt>Question set</dt>
            <dd>MMLU-Pro, three disjoint 100-question stratified subsets
              (<code>s1</code>/<code>s2</code>/<code>s3</code>, seeds 20260918/19/20),
              <b> n=300 per model per board</b> — 1,200 answers in total.</dd></div>
          <div><dt>Models</dt>
            <dd>Gemma 4 <b>E2B</b> and <b>E4B</b>, identical Unsloth Q4_K_XL QAT
              GGUFs on both boards.</dd></div>
          <div><dt>Serving</dt>
            <dd>llama.cpp, 5-shot CoT, greedy, <code>max_gen_toks</code> 2048,{" "}
              <code>-c 8192 --cache-ram 0 -rea off --reasoning-budget -1</code>.
              Differs only in <code>-t 3</code> (Pi) against <code>-ngl 99</code> (Orin).</dd></div>
          <div><dt>Measured together</dt>
            <dd>Accuracy and device cost in the same run: 1 Hz telemetry for power,
              CPU, GPU, thermals and memory, plus per-request token timings.</dd></div>
          <div><dt>Boards</dt>
            <dd><b>Pi 5</b> — 4× Cortex-A76, 8,062 MB, CPU only.{" "}
              <b>Orin Nano</b> — sm_87 Ampere GPU + 6× Cortex-A78AE, 7,485 MB
              shared, 15 W mode.</dd></div>
          <div><dt>Power method</dt>
            <dd>Board DC draw — the Pi&apos;s PMIC rails summed, the Orin&apos;s
              INA3221 <code>VDD_IN</code>. Excludes PSU conversion loss; not wall
              power.</dd></div>
        </dl>
      </details>

      <details className="card scope fold">
        <summary><h2>Scope</h2><span>what these numbers cover, and what is still open</span></summary>
        <p>
          The figures above are the <b>baseline on both boards</b>: llama.cpp, thinking
          off (<code>-rea off</code>), greedy decoding, same weights, same questions. Only
          the board varies.
        </p>
        <ul className="scope-list">
          <li>
            <span className="scope-tag done">run</span>
            <div><b>Thinking on</b> (<code>-rea on</code>, budget 320,{" "}
              <code>--reasoning-format none</code>) has run on both boards; it is in the
              accuracy tests, not the bars.</div>
          </li>
          <li>
            <span className="scope-tag undecided">undecided</span>
            <div><b>Engine.</b> llama.cpp is what these runs use, not a conclusion.
              little-gemma runs on the Orin only (CUDA) and appears in the accuracy tests,
              never in the Pi-vs-Orin bars. LiteRT-LM was dropped.</div>
          </li>
          <li>
            <span className="scope-tag open">planned</span>
            <div><b>Capability (b) and (c).</b> IFEval and BFCL are installed but unrun;
              tool calling rests on the custom 10-case suite. No safety benchmark chosen.</div>
          </li>
        </ul>
      </details>

      <details className="card caveats fold">
        <summary><h2>Caveats</h2><span>significance, answer agreement, superseded runs, serving parity</span></summary>
        <ul>
          <li className="bad">
            <b>The accuracy gap is not significant.</b> Paired over all 600 questions: 321
            right on both, 213 wrong on both, 31 only the Pi, 35 only the Orin — McNemar{" "}
            <b>p = 0.71</b>. Per model: E2B p = 0.76 (51.7% vs 52.7%), E4B p = 1.00
            (65.7% vs 66.0%).
          </li>
          <li>
            <b>The boards still pick different answers.</b> Same letter on <b>475 of 600</b>{" "}
            (79%): E4B 86%, E2B 72%. Same weights and greedy decoding, so CPU vs CUDA
            arithmetic tips near-ties — and it cancels out (31 to the Pi, 35 to the Orin).
          </li>
          <li>
            <b>Every Orin run is a re-run.</b> The first six lacked{" "}
            <code>-rea off --reasoning-budget -1</code>, so the thinking went to{" "}
            <code>reasoning_content</code>, which lm-eval never reads: <b>73 of 600 answers
            came back empty</b>. Re-run on 21–22 September with matched flags: zero empty,
            and <b>+5.2 points</b> (E2B 48.3→52.7, E4B 60.0→66.0). Five originals are under{" "}
            <code>stdbench/failed/</code>; the E4B s1 original is under{" "}
            <code>stdbench/archive/</code>, which this page does not read. The broken runs
            were also slower (E4B 158–167 min vs 98–102).
          </li>
          <li>
            <b>Both boards were served identically.</b> Checked from the real command line
            (the Pi&apos;s <code>command.log</code>, the Orin&apos;s live process): only{" "}
            <code>-t 3</code> vs <code>-ngl 99</code> differs. The Pi&apos;s{" "}
            <code>meta.json</code> is not evidence — it snapshots the server before the run
            switches models.
          </li>
          <li>
            <b>Uncertainty comes from question sampling</b>, not repeats: ±9.7 points at
            n=100, ±5.6 pooled at n=300 (95%). Smaller gaps are not differences.
          </li>
          {pending.length > 0 && (
            <li><b>Not finished yet:</b> {pending.join(", ")}. Those pool over fewer than
              three subsets, so their interval is wider.</li>
          )}
          <li>
            <b>Power is board DC draw</b> (Pi PMIC rails, Orin INA3221 <code>VDD_IN</code>).
            Same method on both, but not wall power.
          </li>
          {d.boxes.some((b) => b.failed?.length > 0) && (
            <li>
              <b>Failed runs are kept, not hidden.</b>{" "}
              {d.boxes.flatMap((b) => (b.failed || []).map((f) => `${DEV[b.id].short}: ${f}`)).join("; ")}.
            </li>
          )}
        </ul>
      </details>

      <details className="card fold">
        <summary><h2>All runs</h2><span>{allRuns.length} runs, one row each</span></summary>
        <div className="reqtable">
          <div className="reqtable-scroll">
            <table>
              <thead>
                <tr>
                  <th>board</th><th>model</th><th>subset</th><th>run directory</th>
                  <th>score<i>%</i></th><th>decode<i>tok/s</i></th><th>per token<i>J</i></th>
                  <th>power<i>W</i></th><th>energy<i>Wh</i></th><th>temp<i>°C</i></th>
                  <th>gpu<i>%</i></th><th>minutes</th>
                </tr>
              </thead>
              <tbody>
                {allRuns.map(({ b, m, s, r }) => {
                  const dv = r.device || {};
                  return (
                    <tr key={`${b.id}-${m}-${s}`} className={r.score == null ? "dim" : ""}>
                      <td>{DEV[b.id].short}</td>
                      <td>{m.toUpperCase()}</td><td>{s}</td>
                      <td className="runname">{r.run}</td>
                      <td>{r.score == null ? "running" : fmt(r.score, 1)}</td>
                      <td>{fmt(dv.decode_tok_s, 2)}</td><td>{fmt(dv.j_per_token, 2)}</td>
                      <td>{fmt(dv.mean_w, 2)}</td><td>{fmt(dv.energy_wh, 2)}</td>
                      <td>{fmt(dv.temp_max, 1)}</td>
                      <td>{dv.gpu_mean == null ? "n/a" : fmt(dv.gpu_mean, 1)}</td>
                      <td>{fmt(r.minutes)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        <p className="foot">GPU n/a: the Pi 5 has no CUDA device to sample.
          {!MODELS.some(([m]) => rowsFor("iphone", m).length) && " No iPhone runs uploaded yet."}</p>
      </details>
    </main>
  );
}
