// Every API route reaches a board the same way: ssh, run one device-side
// script (AGENTS §7), parse the one JSON object it prints. This is that way,
// once, so a route is a few lines and a fix here fixes all of them.
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, SSH, hint } from "./hosts";

const run = promisify(execFile);

// execFile, not exec: the local shell never sees the command, so nothing in it
// is re-parsed on the Mac. The REMOTE shell still reads it, which is the one
// level shq() quotes for.
const SSH_ARGS = SSH.trim().split(/\s+/);
export const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

// Some scripts print a warning (a venv, lm-eval) before their JSON; the object
// starts at the first "{".
const parse = (text) => JSON.parse(text.slice(text.indexOf("{")));

/**
 * Run benchmark/<script> on a board and return {ok: true, data} or
 * {ok: false, error, hint}. Never throws.
 *
 * python: "venv" (the eval venv, for scripts that import lm-eval's
 * dependencies) or "system" (stdlib-only scripts, and faster to start).
 * args are passed through verbatim: quote anything user-supplied with shq().
 */
export async function onBoard(box, script, args = [],
                              { python = "system", timeout = 30000, maxBuffer = 8 << 20 } = {}) {
  const py = python === "venv" ? box.py : "python3";
  const remote = [py, `${box.repo}/benchmark/${script}`, ...args].join(" ");
  try {
    const { stdout } = await run("ssh", [...SSH_ARGS, box.host, remote], { timeout, maxBuffer });
    return { ok: true, data: parse(stdout) };
  } catch (e) {
    // A script that handled its own error still printed {"error": ...} and
    // exited 1; that message beats "Command failed: ssh ...".
    let parsed = null;
    try { parsed = parse(e.stdout || ""); } catch { /* not ours */ }
    const error = parsed?.error
      || (e.stderr || e.message || "failed").toString().trim().slice(0, 400);
    return { ok: false, error, hint: hint(error, box) };
  }
}

/**
 * The same call on every board, shaped the way the pages expect:
 * {...host, ok: true, ...data} or {...host, ok: false, error, hint, ...empty}.
 * `empty` fills in the fields a page iterates, so a down board renders.
 */
export async function onEveryBoard(script, args, opts = {}, empty = {}) {
  return Promise.all(HOSTS.map(async (h) => {
    const r = await onBoard(h, script, args, opts);
    return r.ok ? { ...h, ok: true, ...(opts.wrap ? { [opts.wrap]: r.data } : r.data) }
                : { ...h, ok: false, error: r.error, hint: r.hint, ...empty };
  }));
}
