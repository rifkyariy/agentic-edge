"use client";
// One queue feed for the whole app. The sidebar's counts, the alerts, the
// monitor's matrix, the queue page and the job page all read the same answer,
// so a tab polls /api/queue once rather than once per component that cares.
import { createContext, useCallback, useContext, useState } from "react";
import { usePoll } from "./usePoll";

const VISIBLE_MS = 10000;
// A hidden tab keeps asking, slowly: the blocked/failed alerts depend on it.
const HIDDEN_MS = 60000;

const QueueContext = createContext({ boxes: [], ts: null, loaded: false, refresh: async () => {} });

export function QueueProvider({ children }) {
  const [state, setState] = useState({ boxes: [], ts: null, loaded: false });

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/queue", { cache: "no-store" });
      const data = await res.json();
      setState({ boxes: data.boxes || [], ts: data.ts, loaded: true });
    } catch { /* keep the last answer; the next tick tries again */ }
  }, []);

  usePoll(refresh, VISIBLE_MS, { hiddenMs: HIDDEN_MS });

  return (
    <QueueContext.Provider value={{ ...state, refresh }}>{children}</QueueContext.Provider>
  );
}

export const useQueue = () => useContext(QueueContext);

// The newest job per run. A blocked job that was requeued stays in queue.json
// as history; counting it would show "blocked" long after the run completed.
export function latestPerRun(jobs) {
  const seen = new Map();
  for (const j of jobs || []) seen.set(j.output_dir || j.id, j);
  return [...seen.values()];
}

// What the queues are doing, for badges: counts by state, newest job per run.
export function queueCounts(boxes) {
  const c = { running: 0, queued: 0, blocked: 0, failed: 0 };
  for (const b of boxes || []) {
    for (const j of latestPerRun(b.jobs)) {
      if (["prechecking", "fingerprinting", "running"].includes(j.state)) c.running += 1;
      else if (j.state in c) c[j.state] += 1;
    }
  }
  return c;
}
