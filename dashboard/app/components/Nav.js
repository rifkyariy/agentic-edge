"use client";
// The sidebar: every page one click away, with what the queues are doing right
// now, and the alerts toggle, which therefore works whichever page is open.
import Link from "next/link";
import { usePathname } from "next/navigation";
import JobAlerts from "../JobAlerts";
import { queueCounts, useQueue } from "../lib/queue-context";
import { useShowFailed } from "../lib/show-failed";

// Add a page here and it appears in the sidebar; nothing else to wire.
export const PAGES = [
  { href: "/", label: "Monitor", hint: "live device state and the experiment matrix" },
  { href: "/queue", label: "Queue", hint: "queue runs, see prechecks and logs", badge: true },
  { href: "/history", label: "History", hint: "every run on disk; failures on request" },
  { href: "/compare", label: "Compare", hint: "Pi 5, Orin Nano and iPhone, paired" },
];

// The iPhone has no daemon to be up or down; it is as alive as its last upload.
export const ago = (s) => s == null ? "—" : s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago`
  : s < 172800 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
export const PHONE_STATE = {
  running: (p) => `running a benchmark, last upload ${ago(p.age_s)}`,
  lost: (p) => `lost contact: a run stopped uploading ${ago(p.age_s)}`,
  idle: (p) => `idle, last upload ${ago(p.age_s)}`,
  never: () => "no runs uploaded yet",
};

const active = (path, href) => (href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`));

export default function Nav() {
  const path = usePathname() || "/";
  const { boxes, phone, loaded } = useQueue();
  const c = queueCounts(boxes);
  // Failed jobs count only while "show failed" is on, like the lists they open.
  const [showFailed] = useShowFailed();
  const attention = c.blocked + (showFailed ? c.failed : 0);

  return (
    <nav className="sidenav" aria-label="dashboard">
      <Link href="/" className="brand">
        <span className="brand-mark" aria-hidden="true">AE</span>
        <span><b>Agentic Edge</b><i>Gemma 4 on the edge</i></span>
      </Link>

      <ul>
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link href={p.href} title={p.hint}
                  className={active(path, p.href) ? "on" : ""}
                  aria-current={active(path, p.href) ? "page" : undefined}>
              <span>{p.label}</span>
              {p.badge && loaded && (
                <span className="badges">
                  {c.running > 0 && <em className="b-running" title="running">{c.running}</em>}
                  {c.queued > 0 && <em className="b-queued" title="queued">{c.queued}</em>}
                  {attention > 0 &&
                    <em className="b-blocked" title={showFailed ? "blocked or failed" : "blocked"}>{attention}</em>}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>

      <div className="boards">
        {boxes.map((b) => (
          <span key={b.id} title={!b.ok ? b.error : b.daemon_alive ? "queue daemon running" : "queue daemon down"}>
            <i className={`dot-static ${!b.ok ? "down" : b.daemon_alive ? "up" : "down"}`} />
            {b.id}
          </span>
        ))}
        {phone && (
          <span title={PHONE_STATE[phone.state]?.(phone) ?? phone.state}>
            <i className={`dot-static ${phone.state === "running" ? "up live" : phone.state === "idle" ? "up" : phone.state === "lost" ? "down" : ""}`} />
            iphone
          </span>
        )}
      </div>

      <div className="nav-foot"><JobAlerts boxes={boxes} /></div>
    </nav>
  );
}
