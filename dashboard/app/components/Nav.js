"use client";
// The sidebar: every page one click away, with what the queues are doing right
// now, and the alerts toggle, which therefore works whichever page is open.
import Link from "next/link";
import { usePathname } from "next/navigation";
import JobAlerts from "../JobAlerts";
import { queueCounts, useQueue } from "../lib/queue-context";

// Add a page here and it appears in the sidebar; nothing else to wire.
export const PAGES = [
  { href: "/", label: "Monitor", hint: "live device state and the experiment matrix" },
  { href: "/queue", label: "Queue", hint: "queue runs, see prechecks and logs", badge: true },
  { href: "/history", label: "History", hint: "every run on disk, failures included" },
  { href: "/compare", label: "Compare", hint: "Pi 5 versus Orin Nano, paired" },
];

const active = (path, href) => (href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`));

export default function Nav() {
  const path = usePathname() || "/";
  const { boxes, loaded } = useQueue();
  const c = queueCounts(boxes);

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
                  {c.blocked + c.failed > 0 &&
                    <em className="b-blocked" title="blocked or failed">{c.blocked + c.failed}</em>}
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
      </div>

      <div className="nav-foot"><JobAlerts boxes={boxes} /></div>
    </nav>
  );
}
