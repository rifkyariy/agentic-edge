// One ssh call per board per poll interval, however many tabs are open.
//
// Every open tab polls /api/status and /api/queue, and each of those used to
// start a Python process on each board over ssh. The Pi runs with one core
// spare while benchmarking, so N tabs cost it N probes every 5 s. shared()
// hands every caller inside the ttl the same answer, and callers that arrive
// while a fetch is in flight wait on that fetch instead of starting another.
// Nothing polls when no tab asks, so a closed dashboard costs the boards
// nothing.
//
// The cache lives on globalThis because Next bundles each route separately,
// and in dev re-evaluates modules on every edit; module scope would give each
// route (and each reload) a cache of its own.
const store = (globalThis.__aeShared ??= new Map());

export async function shared(key, ttlMs, fetcher) {
  const now = Date.now();
  const hit = store.get(key);
  if (hit?.value && now - hit.at < ttlMs) return hit.value;
  if (hit?.pending) return hit.pending;

  // Only the fetch still on record may write back: one that was in flight
  // across an invalidate() started before the write and would cache stale data.
  const mine = () => store.get(key)?.pending === pending;
  const pending = fetcher().then(
    (value) => { if (mine()) store.set(key, { value, at: Date.now() }); return value; },
    (err) => { if (mine()) store.delete(key); throw err; },
  );
  store.set(key, { ...hit, pending });
  return pending;
}

// After a write (queue, cancel) the next read must see it, not a copy from
// before the write.
export function invalidate(key) {
  store.delete(key);
}
