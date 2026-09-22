// The two boards, and how to reach them. Everything is overridable from
// .env.local so a fresh clone can point at its own machines without a patch.
//
// PI_HOST / JETSON_HOST are whatever `ssh <name>` accepts: an ssh_config alias
// (what this lab uses) or plain user@address. Paths follow the case convention
// on each board — ~/Research on the Pi, ~/research on the Jetson.
const env = (k, d) => process.env[k]?.trim() || d;

export const HOSTS = [
  {
    id: "pi",
    label: env("PI_LABEL", "Raspberry Pi 5"),
    sub: env("PI_SUB", "CPU only · Cortex-A76 ×4"),
    host: env("PI_HOST", "MITLAB-EDGE"),
    repo: env("PI_REPO", "~/Research/agentic-edge"),
    py: env("PI_PY", "~/Research/eval-venv/bin/python3"),
  },
  {
    id: "jetson",
    label: env("JETSON_LABEL", "Jetson Orin Nano"),
    sub: env("JETSON_SUB", "CUDA · 15W mode"),
    host: env("JETSON_HOST", "MITLAB-JETSON"),
    repo: env("JETSON_REPO", "~/research/agentic-edge"),
    py: env("JETSON_PY", "~/venvs/eval/bin/python3"),
  },
];

export const byId = (id) => HOSTS.find((h) => h.id === id);

// Shared ssh flags: never prompt (the web app has no tty), give up quickly.
// ControlMaster reuses one connection per board across calls — the dashboard
// polls every 5s, which is ~11,500 handshakes over an 8h run, each forking an
// sshd and a python on a board AGENTS §5 requires to be otherwise quiet.
// ControlPath lives in /tmp so a stale socket dies with the machine.
export const SSH = "-o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new"
  + " -o ControlMaster=auto -o ControlPersist=300"
  + " -o ControlPath=/tmp/agentic-edge-cm-%r@%h:%p";

// ssh failures are cryptic out of context; say what to actually do about them.
export function hint(err, h) {
  const e = (err || "").toLowerCase();
  if (e.includes("could not resolve") || e.includes("name or service not known")
      || e.includes("no such host")) {
    return `"${h.host}" is not a host this Mac knows. Add it to ~/.ssh/config, `
         + `or set ${h.id === "pi" ? "PI_HOST" : "JETSON_HOST"} in dashboard/.env.local.`;
  }
  if (e.includes("permission denied") || e.includes("publickey")) {
    return `${h.host} refused the key. Run: ssh-copy-id ${h.host}`;
  }
  if (e.includes("connection refused") || e.includes("timed out")
      || e.includes("no route to host")) {
    return `${h.host} is not answering — check it is powered on and on this network.`;
  }
  if (e.includes("no such file") || e.includes("not found")) {
    return `The repo is not at ${h.repo} on ${h.host}, or python3 is missing there.`;
  }
  return `Run "npm run check" for a step-by-step diagnosis.`;
}
