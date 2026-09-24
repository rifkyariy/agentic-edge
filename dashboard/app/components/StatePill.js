// A job or run state as a coloured pill. `family` picks the palette: "state"
// for queue jobs (queued, running, blocked ...), "hist" for runs on disk
// (done, failed, superseded ...). The label defaults to the state itself.
export default function StatePill({ state, label, family = "state" }) {
  return <i className={`state-pill ${family}-${state}`}>{label ?? state}</i>;
}
