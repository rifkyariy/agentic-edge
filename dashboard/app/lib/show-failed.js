"use client";
// Whether failed runs and jobs are shown. Off by default: they stay on disk
// and in the record (AGENTS §5), but the pages list them only when asked.
// One switch for every page and the sidebar, kept per browser; a change in
// one component (or another tab) reaches the rest through the store below.
import { useCallback, useSyncExternalStore } from "react";

const KEY = "showFailed";
const EVENT = "showfailed";

const read = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };

function subscribe(cb) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useShowFailed() {
  const show = useSyncExternalStore(subscribe, read, () => false);
  const set = useCallback((v) => {
    try { localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* private mode */ }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [show, set];
}
