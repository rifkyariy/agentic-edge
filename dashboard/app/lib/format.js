// Number and time formatting shared by every page. One definition each, so a
// duration reads the same on the monitor, the queue and the history.

export const fmt = (n, d = 0) =>
  n === null || n === undefined || Number.isNaN(n) ? "—"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// A duration given in seconds: "3h 12m", or "12m" under an hour.
export const durSeconds = (s) => {
  if (s === null || s === undefined) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};

// The same, for the minute counts lm-eval and run_detail.py report.
export const durMinutes = (m) => (m === null || m === undefined ? "—" : durSeconds(m * 60));

// An epoch in seconds (what the boards send) as the Mac's local clock time.
export const clock = (epoch, seconds = false) =>
  epoch ? new Date(epoch * 1000).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}),
  }) : null;
