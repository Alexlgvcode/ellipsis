import { useEffect, useRef, useState } from "react";

export interface PollState<T> {
  data: T | null;        // last good payload (kept while the API is down)
  error: string | null;  // set while the latest attempt failed
  lastOkAt: number | null;
}

/** Calls `load` now and every `everyMs`, keeping the last good result when a call fails. */
export function usePolling<T>(load: () => Promise<T>, everyMs: number): PollState<T> {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, lastOkAt: null });
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const data = await loadRef.current();
        if (alive) setState({ data, error: null, lastOkAt: Date.now() });
      } catch (e) {
        if (alive) setState((s) => ({ ...s, error: (e as Error).message }));
      }
      if (alive) timer = setTimeout(tick, everyMs);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [everyMs]);

  return state;
}
