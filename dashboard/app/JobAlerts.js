"use client";
import { useEffect, useState } from "react";

// A browser notification when a queued job ends blocked or failed, or a
// board's queue daemon goes down. A job blocked at 2 am otherwise wastes the
// night unnoticed until someone opens the dashboard.
//
// It needs an open dashboard tab (hidden is fine: the queue poll keeps going
// at a slower rate there). Anything that reaches a phone with no tab open
// needs an outside service such as ntfy, which this deliberately is not.
//
// What has been announced is kept in localStorage, so a reload, or a second
// tab, does not announce the same job twice. The first time a browser sees the
// dashboard it records the current failures without announcing them: they are
// history, not news.
const ON = "ae.alerts.on";
const SEEN = "ae.alerts.seen";
const KEEP = 500;
const ALERT_STATES = new Set(["blocked", "failed"]);

const read = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

function notify(title, body, tag, href) {
  try {
    const n = new Notification(title, { body, tag, requireInteraction: true });
    n.onclick = () => { window.focus(); if (href) window.location.href = href; n.close(); };
  } catch { /* the browser refused; the pill already says so */ }
}

// boxes: the /api/queue answer. Boards that did not answer are skipped rather
// than read as "daemon down": an ssh hiccup is not a dead daemon.
function check(boxes, enabled) {
  const raw = read(SEEN);
  const first = raw === null;
  const seen = new Set(first ? [] : JSON.parse(raw));
  const fresh = [];

  for (const b of boxes) {
    if (!b.ok) continue;
    for (const j of b.jobs || []) {
      if (!ALERT_STATES.has(j.state)) continue;
      const key = `${b.id}:${j.id}:${j.state}`;
      if (seen.has(key)) continue;
      seen.add(key);
      fresh.push({
        key, href: `/queue/${b.id}/${j.id}`,
        title: `${b.label}: ${j.label} ${j.state}`,
        body: j.note || `the job ended ${j.state}`,
      });
    }
    // Down is a condition, not an event: forget it once the daemon is back,
    // so the next time it dies is announced again.
    const down = `${b.id}:daemon-down`;
    if (b.daemon_alive === false && !seen.has(down)) {
      seen.add(down);
      fresh.push({
        key: down, href: "/queue",
        title: `${b.label}: queue daemon down`,
        body: "No queued job will start until queue_runner is restarted on the board.",
      });
    } else if (b.daemon_alive) {
      seen.delete(down);
    }
  }

  write(SEEN, JSON.stringify([...seen].slice(-KEEP)));
  if (first || !enabled) return;
  for (const f of fresh) notify(f.title, f.body, f.key, f.href);
}

export default function JobAlerts({ boxes }) {
  const [perm, setPerm] = useState(null);     // null until mounted: no SSR guess
  const [on, setOn] = useState(false);

  useEffect(() => {
    setPerm(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    setOn(read(ON) === "1");
  }, []);

  const enabled = on && perm === "granted";
  useEffect(() => {
    if (boxes?.length) check(boxes, enabled);
  }, [boxes, enabled]);

  if (perm === null) return null;
  if (perm === "unsupported") {
    return <span className="pill muted" title="this browser has no Notification API">alerts n/a</span>;
  }
  if (perm === "denied") {
    return (
      <span className="pill danger" title="notifications are blocked for this site; allow them in the browser's site settings">
        alerts blocked
      </span>
    );
  }

  const toggle = async () => {
    if (enabled) { write(ON, "0"); setOn(false); return; }
    const p = perm === "granted" ? perm : await Notification.requestPermission();
    setPerm(p);
    if (p === "granted") {
      write(ON, "1"); setOn(true);
      notify("Alerts on", "You will be told here when a job is blocked or fails, or a queue daemon goes down, while a dashboard tab is open.", "ae-alerts-on");
    }
  };

  return (
    <button type="button" className={`pill nav ${enabled ? "live" : "muted"}`} onClick={toggle}
            title={enabled
              ? "browser notification when a job is blocked or fails, or a daemon goes down — needs a dashboard tab open (hidden is fine). Click to turn off."
              : "turn on browser notifications for blocked or failed jobs"}>
      {enabled && <i className="dot" />}{enabled ? "alerts on" : "alerts off"}
    </button>
  );
}
