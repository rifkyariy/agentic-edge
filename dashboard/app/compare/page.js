"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bar, BarChart, CartesianGrid, LabelList,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt } from "../Charts";

const MODELS = [["e2b", "Gemma 4 E2B"], ["e4b", "Gemma 4 E4B"]];
const DEV = {
  pi: { label: "Raspberry Pi 5", short: "Pi 5", color: "var(--pi)" },
  jetson: { label: "Jetson Orin Nano", short: "Orin Nano", color: "var(--jetson)" },
};

const TIP = {
  background: "var(--panel)", border: "1px solid var(--line-2)", borderRadius: "8px",
  font: "11px var(--mono)", padding: "6px 9px", boxShadow: "0 4px 14px rgba(0,0,0,.14)",
};
const axis = { stroke: "var(--line-2)",
               tick: { fill: "var(--ink-3)", fontSize: 10, fontFamily: "var(--mono)" } };

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

function Chart({ title, note, data, unit, decimals = 2, better }) {
  return (
    <figure className="cmp-fig">
      <figcaption>
        <h3>{title}</h3>
        {note && <p>{note}</p>}
        {/* Our own key rather than recharts' Legend: it renders a bottom
            legend in its own order, which did not match the bars. */}
        <ul className="cmp-key">
          {Object.entries(DEV).map(([id, v]) => (
            <li key={id}><i style={{ background: v.color }} />{v.short}</li>
          ))}
        </ul>
      </figcaption>
      <ResponsiveContainer width="100%" height={168}>
        <BarChart data={data} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} barGap={6}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="model" {...axis} />
          <YAxis width={52} tickFormatter={(v) => fmt(v, decimals)} {...axis} />
          <Tooltip contentStyle={TIP} cursor={{ fill: "var(--line)", opacity: 0.4 }}
                   isAnimationActive={false}
                   formatter={(v, n) => [`${fmt(v, decimals)} ${unit}`, DEV[n]?.short ?? n]} />
          {Object.keys(DEV).map((id) => (
            <Bar key={id} dataKey={id} name={id} fill={DEV[id].color}
                 radius={[4, 4, 0, 0]} maxBarSize={54} isAnimationActive={false}>
              <LabelList dataKey={id} position="top"
                         formatter={(v) => (v == null ? "" : fmt(v, decimals))}
                         style={{ fill: "var(--ink-2)", font: "11px var(--mono)" }} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
      {better && <p className="cmp-better">{better}</p>}
    </figure>
  );
}

export default function Compare() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch("/api/baseline", { cache: "no-store" })
      .then((r) => r.json())
      .then(setD)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <main><p className="err">{err}</p></main>;
  if (!d) return <main><p className="sub">Reading both boards…</p></main>;

  const box = Object.fromEntries(d.boxes.map((b) => [b.id, b]));
  const runs = Object.fromEntries(d.boxes.map((b) => [b.id, canonical(b.runs || [])]));

  const rowsFor = (id, model) =>
    ["s1", "s2", "s3"].map((s) => runs[id]?.[`${model}-${s}`]).filter(Boolean);
  const devMean = (id, model, key) => {
    const v = rowsFor(id, model).map((r) => r.device?.[key])
      .filter((x) => x !== null && x !== undefined);
    return v.length ? mean(v) : null;
  };

  const series = (key, decimals) => MODELS.map(([m, label]) => ({
    model: label,
    pi: devMean("pi", m, key), jetson: devMean("jetson", m, key),
  }));

  const acc = MODELS.map(([m, label]) => {
    const p = pooled(rowsFor("pi", m)), j = pooled(rowsFor("jetson", m));
    return { model: label, pi: p?.pct ?? null, jetson: j?.pct ?? null, _p: p, _j: j };
  });

  // the headline ratios, computed rather than written down
  const ratio = (key, inverse) => {
    const v = MODELS.map(([m]) => {
      const p = devMean("pi", m, key), j = devMean("jetson", m, key);
      return p && j ? (inverse ? p / j : j / p) : null;
    }).filter(Boolean);
    return v.length ? mean(v) : null;
  };
  const speedX = ratio("decode_tok_s");
  const energyX = ratio("j_per_token", true);
  const powerX = ratio("mean_w");

  const gpu = {
    mean: devMean("jetson", "e4b", "gpu_mean"),
    max: devMean("jetson", "e4b", "gpu_max"),
    mhz: devMean("jetson", "e4b", "gpu_mhz_mean"),
  };

  const pending = MODELS.flatMap(([m, label]) =>
    Object.entries(runs).flatMap(([id, r]) =>
      ["s1", "s2", "s3"].filter((s) => !r[`${m}-${s}`]?.score)
        .map((s) => `${DEV[id].short} ${label} ${s}`)));

  return (
    <main className="cmp">
      <header className="top">
        <div>
          <p className="eyebrow">Agentic Edge · baseline</p>
          <h1>Raspberry Pi 5 versus Jetson Orin Nano</h1>
          <p className="sub">
            Gemma 4 E2B and E4B, same Q4_K_XL QAT weights, same MMLU-Pro subsets,
            greedy decoding. Only the board differs.
          </p>
        </div>
        <Link className="pill muted" href="/">← live monitor</Link>
      </header>

      {/* The three numbers the comparison exists to produce. */}
      <section className="card cmp-hero">
        <div className="cmp-heronum">
          <span className="tile-label">Decode throughput</span>
          <b>{fmt(speedX, 1)}×</b>
          <em>faster on the Orin</em>
        </div>
        <div className="cmp-heronum">
          <span className="tile-label">Energy per token</span>
          <b>{fmt(energyX, 1)}×</b>
          <em>lower on the Orin</em>
        </div>
        <div className="cmp-heronum alt">
          <span className="tile-label">Board power draw</span>
          <b>{fmt(powerX, 1)}×</b>
          <em>higher on the Orin</em>
        </div>
        <p className="cmp-lede">
          The Orin draws about half as much power again as the Pi, yet spends
          less energy per token — it finishes so much sooner that the higher
          draw is billed for a fraction of the time. On accuracy the two are
          tied: a paired test over the same questions finds no significant
          difference, even though they pick the same letter only 70% of the
          time.
        </p>
      </section>

      {/* What is fixed here and what is still open, so the page is not read as
          a final result for the paper. */}
      <section className="card scope">
        <h2>What this page is — and what it is not yet</h2>
        <p>
          Every number here is the <b>baseline condition on both boards</b>: Gemma 4
          served by <b>llama.cpp</b>, thinking off
          (<code>-rea off --reasoning-budget -1</code>), greedy decoding, the same
          Q4_K_XL QAT weights and the same MMLU-Pro subsets. That holds the model,
          the engine and the decoding fixed so the only variable left is the board.
        </p>
        <ul className="scope-list">
          <li>
            <span className="scope-tag open">planned</span>
            <div>
              <b>Reasoning mode on.</b> A second row with <code>THINKING=on</code>
              (budget 320) against this baseline. Not the same thing as the
              <code>-rea</code> flag above, which only controls where the thinking
              text is returned. Unrun on either board — <code>std_mmlupro_jetson.sh</code>
              has no <code>THINKING</code> switch yet.
            </div>
          </li>
          <li>
            <span className="scope-tag undecided">undecided</span>
            <div>
              <b>Inference engine.</b> llama.cpp is what these runs use, not a
              conclusion. The engine axis also holds <code>little-gemma</code> and
              this project&apos;s own pipeline; LiteRT-LM was dropped. Which engine
              carries the standard-benchmark rows has not been decided, so treat
              these as llama.cpp figures rather than device figures.
            </div>
          </li>
          <li>
            <span className="scope-tag open">planned</span>
            <div>
              <b>Capability (b) and (c).</b> Tool calling still rests on the custom
              10-case suite — IFEval and BFCL are installed but unrun. No safety
              benchmark has been chosen.
            </div>
          </li>
        </ul>
      </section>

      <div className="cmp-grid">
        <Chart title="Accuracy" note="MMLU-Pro, pooled over the finished subsets"
               data={acc} unit="%" decimals={1}
               better="The boards are statistically tied — see below" />
        <Chart title="Decode throughput" note="tokens per second, generation only"
               data={series("decode_tok_s")} unit="tok/s" decimals={2}
               better="Higher is better" />
        <Chart title="Energy per generated token" note="board DC draw ÷ tokens produced"
               data={series("j_per_token")} unit="J/tok"
               better="Lower is better" />
        <Chart title="Throughput per watt" note="decode tokens per second per watt"
               data={series("tok_s_per_w")} unit="tok/s/W" decimals={3}
               better="Higher is better" />
        <Chart title="Board power while working" note="PMIC rails (Pi) / INA3221 VDD_IN (Orin)"
               data={series("mean_w")} unit="W"
               better="Excludes power-supply conversion loss — not wall power" />
        <Chart title="Peak temperature" note="SoC, across the whole run"
               data={series("temp_max", 1)} unit="°C" decimals={1}
               better="Neither board throttled on any completed run" />
      </div>

      {/* What the Orin actually brings: the GPU the Pi does not have. */}
      <section className="card gpucard">
        <div className="card-head">
          <div>
            <h2>What the Orin&apos;s GPU is doing</h2>
            <p className="sub">
              The entire speed and efficiency gap comes from here. The Pi 5 has no
              CUDA device: llama.cpp runs Gemma on four Cortex-A76 cores, and every
              token is CPU work.
            </p>
          </div>
        </div>

        <div className="tiles">
          <div className="tile">
            <span className="tile-label">GPU utilisation</span>
            <b className="tile-value" style={{ color: "var(--jetson)" }}>
              {fmt(gpu.mean, 1)}<i>%</i></b>
            <em className="delta flat">{fmt(Math.min(100, gpu.max), 0)}% peak · E4B runs</em>
          </div>
          <div className="tile">
            <span className="tile-label">GPU clock</span>
            <b className="tile-value">{fmt(gpu.mhz, 0)}<i>MHz</i></b>
            <em className="delta flat">306–612 MHz observed</em>
          </div>
          <div className="tile">
            <span className="tile-label">Layers offloaded</span>
            <b className="tile-value">all<i>-ngl 99</i></b>
            <em className="delta flat">nothing left on the CPU</em>
          </div>
          <div className="tile">
            <span className="tile-label">Host CPU while decoding</span>
            <b className="tile-value" style={{ color: "var(--pi)" }}>
              {fmt(devMean("jetson", "e4b", "cpu_mean"), 1)}<i>%</i></b>
            <em className="delta flat">
              vs {fmt(devMean("pi", "e4b", "cpu_mean"), 0)}% on the Pi</em>
          </div>
        </div>

        <div className="gpunote">
          <p>
            <b>Ampere GPU, compute capability sm_87</b>, on a Jetson Orin Nano Super
            developer kit in its <b>15 W</b> power mode. llama.cpp is built for sm_87
            and offloads every layer, so the six Cortex-A78AE cores sit near idle at{" "}
            {fmt(devMean("jetson", "e4b", "cpu_mean"), 1)}% while the GPU holds{" "}
            {fmt(gpu.mean, 0)}%. On the Pi the same work pins the CPU at{" "}
            {fmt(devMean("pi", "e4b", "cpu_mean"), 0)}%.
          </p>
          <p>
            The catch is memory, and it is not capacity — the two boards are within
            600 MB of each other, <b>8,062 MB</b> on the Pi against <b>7,485 MB</b> on
            the Orin. It is what the memory is spent on. The Pi mmaps the GGUF, so
            the weights live in evictable page cache and an E4B run peaks at about{" "}
            <b>4,162 MB</b> in use. Offloading every layer to CUDA makes that
            allocation pinned device memory in the Orin&apos;s shared pool, which has
            no swap: the same run peaks at <b>6,874 MB</b>, roughly 600 MB from the
            ceiling. Two E4B runs were killed by the OOM killer when a second user
            logged in and took 1.25 GB; both are kept under{" "}
            <code>stdbench/failed/</code>. The Pi&apos;s ceiling is speed, the
            Orin&apos;s is memory.
          </p>
        </div>
      </section>

      <section className="card caveats">
        <h2>Reading this fairly</h2>
        <ul>
          <li className="bad">
            <b>The accuracy difference is not significant.</b> The bars differ by a
            few points, but the two boards answer the <em>same</em> questions, so the
            honest test is paired, not two independent intervals. On E2B s2 with both
            boards configured identically: 44 questions right on both, 46 wrong on
            both, 7 only the Pi, 3 only the Orin. Ten discordant pairs gives an exact
            McNemar <b>p = 0.34</b> — no detectable difference. Read the accuracy
            chart as a tie until the other subsets are re-run and pooled.
          </li>
          <li>
            <b>They do disagree on the answers themselves, though.</b> The same two
            boards pick the same letter on only <b>70 of 100</b> questions, while
            landing on near-identical scores. Same weights, same prompts, greedy
            decoding — so the divergence is CPU versus CUDA arithmetic tipping
            near-ties, and it happens to be accuracy-neutral. That is the interesting
            result here, not the score gap.
          </li>
          <li>
            <b>Five Orin runs are still invalid and excluded from this reading.</b>{" "}
            They ran without <code>-rea off --reasoning-budget -1</code>, so llama.cpp
            split Gemma&apos;s thinking into <code>reasoning_content</code> and
            lm-eval — which reads only <code>content</code> — scored what was left:
            a 993-character median against the Pi&apos;s 1,880, and 11 answers
            returned completely empty. Fixing it restored full-length responses (2,028
            median, zero empty) and moved the score by <b>one point, downward</b>, so
            the bug was real data loss but not the reason for the gap. Only E2B s2 has
            been re-run so far.
          </li>
          <li>
            <b>Uncertainty is from question sampling</b>, not repeats: ±9.7 points at
            n=100 and ±5.6 pooled at n=300, at 95%. Differences smaller than that
            are not differences.
          </li>
          {pending.length > 0 && (
            <li>
              <b>Not finished yet:</b> {pending.join(", ")}. Those models pool over
              fewer than three subsets, so their interval is wider than ±5.6.
            </li>
          )}
          <li>
            <b>Power is board DC draw</b> — the Pi&apos;s PMIC rails summed, the
            Orin&apos;s INA3221 <code>VDD_IN</code>. Same method on both, so the
            comparison holds, but it is not wall power and excludes PSU conversion
            loss.
          </li>
          {d.boxes.some((b) => b.failed?.length > 0) && (
            <li>
              <b>Failed runs are kept, not hidden.</b>{" "}
              {d.boxes.flatMap((b) => (b.failed || []).map((f) => `${DEV[b.id].short}: ${f}`)).join("; ")}.
            </li>
          )}
        </ul>
      </section>

      <section className="card">
        <h2>Every run behind these numbers</h2>
        <div className="reqtable">
          <div className="reqtable-scroll">
            <table>
              <thead>
                <tr>
                  <th>board</th><th>model</th><th>subset</th>
                  <th>score<i>%</i></th><th>decode<i>tok/s</i></th><th>per token<i>J</i></th>
                  <th>power<i>W</i></th><th>energy<i>Wh</i></th><th>temp<i>°C</i></th>
                  <th>gpu<i>%</i></th><th>minutes</th>
                </tr>
              </thead>
              <tbody>
                {d.boxes.flatMap((b) =>
                  MODELS.flatMap(([m]) => ["s1", "s2", "s3"].map((s) => {
                    const r = runs[b.id]?.[`${m}-${s}`];
                    const dv = r?.device || {};
                    return (
                      <tr key={`${b.id}-${m}-${s}`} className={r?.score == null ? "dim" : ""}>
                        <td>{DEV[b.id].short}</td>
                        <td>{m.toUpperCase()}</td><td>{s}</td>
                        <td>{r?.score == null ? (r ? "running" : "—") : fmt(r.score, 1)}</td>
                        <td>{fmt(dv.decode_tok_s, 2)}</td><td>{fmt(dv.j_per_token, 2)}</td>
                        <td>{fmt(dv.mean_w, 2)}</td><td>{fmt(dv.energy_wh, 2)}</td>
                        <td>{fmt(dv.temp_max, 1)}</td>
                        <td>{dv.gpu_mean == null ? "n/a" : fmt(dv.gpu_mean, 1)}</td>
                        <td>{fmt(r?.minutes)}</td>
                      </tr>
                    );
                  })))}
              </tbody>
            </table>
          </div>
        </div>
        <p className="foot">
          n/a in the GPU column is the Pi 5, which has no CUDA device to sample —
          not a missing measurement.
        </p>
      </section>
    </main>
  );
}
