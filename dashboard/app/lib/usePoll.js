"use client";
import { useEffect, useRef } from "react";

// Run `tick` now and every `ms` while the tab is visible. A hidden tab either
// stops (hiddenMs null — nobody is looking at a chart in a background tab) or
// slows to hiddenMs, for polls whose answer matters unseen: the queue feeds
// the blocked/failed alerts. Coming back into view ticks at once, so the page
// is never showing a minute-old answer.
//
// `tick` is read through a ref, so callers may pass a fresh closure on every
// render without restarting the timer.
export function usePoll(tick, ms, { hiddenMs = null, deps = [] } = {}) {
  const fn = useRef(tick);
  fn.current = tick;

  useEffect(() => {
    let timer = null, busy = false, stopped = false;
    const hidden = () => document.visibilityState === "hidden";
    const schedule = () => {
      clearTimeout(timer);
      const wait = hidden() ? hiddenMs : ms;
      if (!stopped && wait != null) timer = setTimeout(run, wait);
    };
    // One tick at a time: a slow ssh round trip must not stack up behind it.
    const run = async () => {
      if (busy || stopped) return;
      busy = true;
      try { await fn.current(); } catch { /* the tick owns its errors */ }
      busy = false;
      schedule();
    };
    const onVis = () => {
      if (hidden()) schedule();          // slow down or stop
      else { clearTimeout(timer); run(); }
    };
    run();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [ms, hiddenMs, ...deps]);            // eslint-disable-line react-hooks/exhaustive-deps
}
