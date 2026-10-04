"use client";
import { ArrowRight, ArrowUp, ChevronRight, Equal, Hourglass } from "lucide-react";
import { fmt } from "../Charts";
import { ALPHA } from "../lib/paired";

const pfmt = (p) => (p < 0.001 ? "< 0.001" : p.toFixed(p < 0.01 ? 3 : 2));

// A verdict is only ever a test result: below ALPHA the side with more
// questions to itself wins, otherwise it says "same" in words — a one-point
// gap is never drawn as a win (same rule as the accuracy bars).
function Verdict({ r, a, b }) {
  if (!r) return null;
  if (!r.sig) return <span className="pillv tie"><Equal className="ic" /> same</span>;
  return <span className="pillv win"><ArrowUp className="ic" /> {r.winner === "b" ? b : a}</span>;
}

/* One cell of the summary line: both scores, then the verdict. The p-value is
   there for whoever wants it, small, after the answer rather than instead of it. */
function Cell({ r, a, b, model }) {
  const tag = <span className="pc-model">{model}</span>;
  if (!r) return <div className="pc wait">{tag}—</div>;
  return (
    <div className="pc" title={`n = ${r.n} questions, exact McNemar p = ${pfmt(r.p)}`}>
      {tag}
      <span className="pc-scores">{fmt(r.aAcc, 1)}<ArrowRight className="ic" />{fmt(r.bAcc, 1)}<i>%</i></span>
      <Verdict r={r} a={a} b={b} />
      <em>p {pfmt(r.p)}</em>
    </div>
  );
}

// The full numbers behind one line: what used to be the whole section, now
// opened only on request.
function Detail({ a, b, groups }) {
  const subsets = groups.filter((g) => g.label !== "both models").flatMap((g) => g.rows);
  const row = (key, label, r, sub) => (
    <tr key={key} className={sub ? "dim" : ""}>
      <th>{label}{r && <em> n={r.n}</em>}</th>
      {r ? (
        <>
          <td>{fmt(r.aAcc, 1)}%</td>
          <td>{fmt(r.bAcc, 1)}%</td>
          <td>{r.delta >= 0 ? "+" : ""}{fmt(r.delta, 1)}</td>
          <td className="paired-cells">{r.both} · {r.neither} · <b>{r.aOnly}</b> · <b>{r.bOnly}</b></td>
          <td>p = {pfmt(r.p)}</td>
        </>
      ) : <td colSpan={5} className="sub">no subset finished on both sides yet</td>}
    </tr>
  );
  return (
    <div className="pcmp-detail">
      <div className="table-wrap">
        <table className="score paired">
          <thead>
            <tr><th /><th>{a}</th><th>{b}</th><th>Δ pts</th>
              <th>both right · both wrong · {a} only · {b} only</th><th>McNemar</th></tr>
          </thead>
          <tbody>
            {groups.map((g) => row(g.label, g.label, g.pooled))}
            {subsets.map((r) => row(`${r.model}-${r.subset}`, `${r.model.toUpperCase()} ${r.subset}`, r, true))}
          </tbody>
        </table>
      </div>
      {groups.map((g) => (
        <p key={g.label} className="paired-note">
          {g.pending.length > 0 && <>{g.label}: pooled over {g.subsets} of {g.subsets + g.pending.length},
            waiting on {g.pending.join(", ")}. </>}
          {g.pooled?.missing > 0 && <b className="bad">{g.label}: {g.pooled.missing} questions answered by
            one side only — question sets differ, do not cite. </b>}
          {g.label === "both models" && g.pooled && (g.noAnswer.a > 0 || g.noAnswer.b > 0) &&
            <>No stated answer: {a} {g.noAnswer.a}, {b} {g.noAnswer.b}.</>}
        </p>
      ))}
    </div>
  );
}

function Comparison({ title, a, b, groups }) {
  return (
    <details className="pcmp">
      <summary>
        <span className="pcmp-title">
          <ChevronRight className="ic pcmp-chev" />
          <span><b>{title}</b><em>{a} <ArrowRight className="ic" /> {b}</em></span>
        </span>
        {groups.map((g) => <Cell key={g.label} r={g.pooled} a={a} b={b} model={g.label} />)}
      </summary>
      <Detail a={a} b={b} groups={groups} />
    </details>
  );
}

const ready = (c) => c.groups.some((g) => g.pooled);

export default function Paired({ data, err }) {
  // Every question the paper asks of MMLU-Pro, as one line each, grouped by
  // what is being changed.
  const sections = data ? [
    ["Pi 5 vs Orin Nano", "Does the board change the answer?",
      data.board.map((c) => ({ key: `board-${c.condition}`, a: c.a, b: c.b, groups: c.groups,
        title: c.condition === "off" ? "Thinking off" : "Thinking on" }))],
    ["Thinking off vs on", "Does letting the model reason first help? (budget 320 tokens)",
      data.thinking.map((c) => ({ key: `think-${c.board}-${c.engine}`, a: "off", b: "on", groups: c.groups,
        title: `${c.a.replace(" baseline", "")}${c.engine && c.engine !== "llama.cpp" ? `, ${c.engine}` : ""}` }))],
    ["llama.cpp vs little-gemma", "Does the engine matter? Orin Nano only.",
      (data.engine || []).map((c) => ({ key: `engine-${c.condition}`, a: c.a, b: c.b, groups: c.groups,
        title: c.condition === "off" ? "Thinking off" : "Thinking on" }))],
    ["Boards vs iPhone", "llama.cpp on the board against MLX on the phone, thinking off.",
      (data.phone || []).map((c) => ({ key: `phone-${c.board}`, a: c.a, b: c.b, groups: c.groups,
        title: c.a }))],
  ] : [];
  const all = sections.flatMap(([, , cs]) => cs);
  const done = all.filter(ready);
  const waiting = all.filter((c) => !ready(c));
  const differ = done.filter((c) => c.groups.some((g) => g.pooled?.sig));

  return (
    <section className="card paired-card">
      <div>
        <h2>Does anything change accuracy?</h2>
        <p className="sub">
          Each line runs two setups on the same questions. <b>Same</b> means the gap is
          within noise (paired McNemar test, p ≥ {ALPHA}). Click a line for the full numbers.
        </p>
      </div>
      {err && <p className="pre-error"><b>{err}</b></p>}
      {!data && !err && <p className="sub">Reading per-question answers from both boards…</p>}
      {data?.unreachable?.length > 0 && (
        <p className="pre-error">No answers from {data.unreachable.join("; ")}. Its runs are
          missing from every comparison below.</p>
      )}
      {data && done.length > 0 && (
        <p className={`paired-headline ${differ.length ? "differ" : ""}`}>
          {differ.length === 0
            ? <><Equal className="ic" /> None of the {done.length} comparisons changes accuracy.</>
            : <><ArrowUp className="ic" /> {differ.length} of {done.length} comparisons show a real difference.</>}
        </p>
      )}
      {data && (
        <div className="pcmp-list">
          <div className="pcmp-head"><span /><span>E2B</span><span>E4B</span><span>Both models</span></div>
          {sections.map(([name, question, cs]) => cs.some(ready) && (
            <div key={name} className="pcmp-group">
              <h3>{name} <span>{question}</span></h3>
              {cs.filter(ready).map(({ key, ...c }) => <Comparison key={key} {...c} />)}
            </div>
          ))}
        </div>
      )}
      {data && (
        <p className="sub paired-foot">
          {waiting.length > 0 && <><Hourglass className="ic" /> No runs yet for{" "}
            {waiting.map((c) => `${c.a} vs ${c.b}`).join(", ")}. </>}
          Read at {new Date(data.ts).toLocaleString()}
          {data.running.length > 0 && <> · not finished: {data.running.map((k) => k.replaceAll(":", " ")).join(", ")}</>}
        </p>
      )}
    </section>
  );
}
