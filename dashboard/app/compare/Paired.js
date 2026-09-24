"use client";
import { useState } from "react";
import { fmt } from "../Charts";
import { ALPHA } from "../lib/paired";

const pfmt = (p) => (p < 0.001 ? "< 0.001" : p.toFixed(p < 0.01 ? 3 : 2));

// A verdict is only ever a test result: below ALPHA the side with more
// questions to itself wins, otherwise the row says "no difference" in words —
// a one-point gap is never drawn as a win (same rule as the accuracy chart).
function Verdict({ r, a, b }) {
  if (!r) return <span className="sub">—</span>;
  if (!r.sig) return <span className="pillv tie">= no difference</span>;
  return <span className="pillv win">▲ {r.winner === "b" ? b : a}</span>;
}

function Row({ label, r, a, b, sub, extra }) {
  return (
    <tr className={sub ? "dim" : ""}>
      <th>{label}{r && <em> n={r.n}</em>}</th>
      {r ? (
        <>
          <td>{fmt(r.aAcc, 1)}%</td>
          <td>{fmt(r.bAcc, 1)}%</td>
          <td>{r.delta >= 0 ? "+" : ""}{fmt(r.delta, 1)}</td>
          <td className="paired-cells">{r.both} · {r.neither} · <b>{r.aOnly}</b> · <b>{r.bOnly}</b></td>
          <td><b>p = {pfmt(r.p)}</b></td>
        </>
      ) : <td colSpan={5} className="sub">waiting — no subset finished on both sides yet</td>}
      <td><Verdict r={r} a={a} b={b} />{extra}</td>
    </tr>
  );
}

function Block({ title, a, b, groups }) {
  const [open, setOpen] = useState(false);
  if (!groups.some((g) => g.pooled || g.pending.length)) return null;
  const subsets = groups.filter((g) => g.label !== "both models").flatMap((g) => g.rows);
  return (
    <div className="paired-block">
      <h3>{title}</h3>
      <div className="table-wrap">
        <table className="score paired">
          <thead>
            <tr><th /><th>{a}</th><th>{b}</th><th>Δ pts</th>
              <th title={`both right · both wrong · only ${a} · only ${b}`}>
                both ✓ · both ✗ · {a} only · {b} only</th>
              <th>McNemar</th><th>Result</th></tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <Row key={g.label} label={g.label} r={g.pooled} a={a} b={b}
                   extra={<>
                     {g.pending.length > 0 && (
                       <em className="paired-note">pooled over {g.subsets} of {g.subsets + g.pending.length};
                         waiting on {g.pending.join(", ")}</em>)}
                     {g.pooled?.missing > 0 && (
                       <em className="paired-note bad">{g.pooled.missing} questions answered by
                         one side only — question sets differ, do not cite</em>)}
                     {(g.noAnswer.a > 0 || g.noAnswer.b > 0) && g.pooled && (
                       <em className="paired-note">no stated answer: {a} {g.noAnswer.a},
                         {" "}{b} {g.noAnswer.b}</em>)}
                   </>} />
            ))}
          </tbody>
          {open && (
            <tbody className="paired-subsets">
              {subsets.map((r) => (
                <Row key={`${r.model}-${r.subset}`} label={`${r.model.toUpperCase()} ${r.subset}`}
                     r={r} a={a} b={b} sub />
              ))}
            </tbody>
          )}
        </table>
      </div>
      {subsets.length > 0 && (
        <button type="button" className="paired-toggle" onClick={() => setOpen(!open)}>
          {open ? "▾ hide" : "▸ show"} per subset ({subsets.length})
        </button>
      )}
    </div>
  );
}

export default function Paired({ data, err }) {
  return (
    <section className="card paired-card">
      <h2>Paired accuracy <i className="sub">computed from the boards, updates as runs finish</i></h2>
      <p className="sub">
        Every pair of runs is compared question by question on the identical subsets.
        Only the questions exactly one side gets right carry information; the exact
        McNemar test asks whether those split evenly. &ldquo;No difference&rdquo; means
        p ≥ {ALPHA}, not that the scores are equal. Pooled rows cover only subsets
        finished on <em>both</em> sides; the rest are named.
      </p>
      {err && <p className="pre-error"><b>{err}</b></p>}
      {!data && !err && <p className="sub">Reading per-question answers from both boards…</p>}
      {data?.unreachable?.length > 0 && (
        <p className="pre-error">No answers from {data.unreachable.join("; ")}. Its runs are
          missing from every comparison below.</p>
      )}
      {data && (
        <>
          {data.board.map((c) => (
            <Block key={c.condition}
                   title={c.condition === "off" ? "Pi 5 vs Orin Nano — baseline (thinking off)"
                                                : "Pi 5 vs Orin Nano — thinking on (budget 320)"}
                   a={c.a} b={c.b} groups={c.groups} />
          ))}
          {data.thinking.map((c) => (
            <Block key={c.board} title={`Thinking vs baseline — ${c.a.replace(" baseline", "")}`}
                   a="baseline" b="thinking" groups={c.groups} />
          ))}
          <p className="sub paired-foot">
            Read at {new Date(data.ts).toLocaleString()}
            {data.running.length > 0 && <> · not finished: {data.running.map((k) => k.replaceAll(":", " ")).join(", ")}</>}
          </p>
        </>
      )}
    </section>
  );
}
