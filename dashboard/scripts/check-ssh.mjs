#!/usr/bin/env node
// Preflight for a fresh clone: can this Mac actually reach both boards, and is
// the benchmark repo where the dashboard expects it? Run before `npm run dev`.
//
//   npm run check
//
// Each board is checked in five steps, and the first failure says what to fix
// rather than leaving you with a bare ssh error in the browser.
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFileSync, existsSync } from "node:fs";

// .env.local is Next's, not Node's — read it here so the check and the running
// app agree on which hosts they are talking about.
if (existsSync(".env.local")) {
  for (const line of readFileSync(".env.local", "utf8").split("\n")) {
    const m = /^\s*([A-Z_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
const { HOSTS } = await import("../app/lib/hosts.js");

const run = promisify(execFile);
const SSH = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             "-o", "StrictHostKeyChecking=accept-new"];

const ok = (s) => `  \x1b[32m✓\x1b[0m ${s}`;
const bad = (s, fix) => `  \x1b[31m✗\x1b[0m ${s}\n    \x1b[33m→ ${fix}\x1b[0m`;

async function sh(host, cmd) {
  const { stdout } = await run("ssh", [...SSH, host, cmd], { timeout: 20000 });
  return stdout.trim();
}

let failed = 0;
for (const h of HOSTS) {
  console.log(`\n\x1b[1m${h.label}\x1b[0m  ssh ${h.host}`);
  const envVar = h.id === "pi" ? "PI_HOST" : "JETSON_HOST";

  try {
    await sh(h.host, "true");
    console.log(ok(`reachable over ssh with key auth`));
  } catch (e) {
    const m = (e.stderr || e.message || "").trim().split("\n").pop();
    const fix = /resolve|not known/i.test(m)
      ? `no such host. Add it to ~/.ssh/config:\n\n        Host ${h.host}\n          HostName <ip-or-name>\n          User <user>\n\n      …or set ${envVar}=user@host in dashboard/.env.local`
      : /permission denied|publickey/i.test(m)
        ? `key not accepted. Run: ssh-copy-id ${h.host}`
        : `${m}\n      Check the board is powered on and on this network.`;
    console.log(bad(`cannot ssh to ${h.host}`, fix));
    failed++;
    continue;
  }

  for (const [what, cmd, fix] of [
    ["repo present", `test -d ${h.repo}/benchmark && echo yes`,
     `clone the repo to ${h.repo} on ${h.host}, or set ${h.id.toUpperCase()}_REPO in .env.local`],
    ["probe_status.py runs", `python3 ${h.repo}/benchmark/probe_status.py >/dev/null && echo yes`,
     `python3 could not run the probe — check python3 exists on ${h.host}`],
    ["eval venv python", `test -x $(eval echo ${h.py}) && echo yes`,
     `no python at ${h.py} — run detail will fail. Set ${h.id.toUpperCase()}_PY in .env.local`],
    // The daemon is what makes a run survive this Mac going to sleep, so a
    // dead one is worth catching here rather than when a queued job silently
    // never starts.
    ["queue daemon running",
     `${h.py} ${h.repo}/benchmark/queue_ctl.py --status | `
     + `python3 -c "import json,sys;print('yes' if json.load(sys.stdin).get('daemon_alive') else 'no')"`,
     `the queue daemon is not running. Start it with:\n`
     + `        ssh ${h.host} 'cd ${h.repo} && ./benchmark/install_queue.sh'`],
  ]) {
    try {
      if ((await sh(h.host, cmd)) !== "yes") throw new Error("not found");
      console.log(ok(what));
    } catch (e) {
      console.log(bad(what, fix));
      failed++;
    }
  }
}

console.log(failed
  ? `\n\x1b[31m${failed} check(s) failed.\x1b[0m Fix the above, then re-run: npm run check\n`
  : `\n\x1b[32mAll good.\x1b[0m Start the dashboard with: npm run dev\n`);
process.exit(failed ? 1 : 0);
