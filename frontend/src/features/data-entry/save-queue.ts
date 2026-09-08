export interface SaveState { dirty: boolean; saving: boolean; error: string; savedAt: string }

// Every queued value is captured before awaiting authorization or network I/O.
// Failed writes retain the newest snapshot, and never clear a newer edit's dirty flag.
export function createSaveQueue<T>(
  state: SaveState,
  write: (snapshot: T, isCurrent: () => boolean) => Promise<void>,
  changed: () => void,
  failed: (error: unknown) => void,
) {
  let revision = 0;
  let pending: { revision: number; value: T } | null = null;
  let running: Promise<void> | null = null;
  function edit() {
    revision++;
    // An unvalidated newer edit must not be replaced by an older queued retry.
    pending = null;
    state.dirty = true;
    changed();
  }
  function run(): Promise<void> {
    if (running) return running;
    running = (async () => {
      state.saving = true;
      state.error = '';
      changed();
      try {
        while (pending) {
          const current = pending;
          pending = null;
          try { await write(current.value, () => current.revision === revision); }
          catch (error) {
            if (current.revision === revision) pending ??= current;
            state.dirty = true;
            state.error = error instanceof Error ? error.message : String(error);
            failed(error);
            return;
          }
          state.savedAt = new Date().toLocaleTimeString();
          state.dirty = current.revision !== revision;
        }
      } finally { state.saving = false; changed(); }
    })().finally(() => {
      running = null;
      if (pending && !state.error) return run();
    });
    return running;
  }
  function save(snapshot: T): Promise<void> {
    pending = { revision, value: structuredClone(snapshot) };
    state.dirty = true;
    changed();
    return run();
  }
  return { edit, save, retry: run, idle: () => running || Promise.resolve() };
}
