// Between syncs: send a word to Langfour as soon as one of its cards is
// answered, or its flashcards are turned off or on. Full syncs still run and
// cover anything missed here (an event during a sync, a failed request).

import { AppEvents, type RNPlugin } from '@remnote/plugin-sdk';
import { SyncBusyError } from './api';
import { isSyncing, pushRems } from './sync';

// Answers arrive one after another in a review session; one request for a
// burst of them. RemNote also reports a card's answer only after the next
// card has loaded, so a short wait is needed anyway.
const DEBOUNCE_MS = 5_000;
const BUSY_RETRY_MS = 60_000;

export function watchForChanges(plugin: RNPlugin): () => void {
  const dirty = new Set<string>(); // Rem ids
  let timer: ReturnType<typeof setTimeout> | undefined;
  let flushing = false;

  const schedule = (ms: number) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void flush(), ms);
  };

  async function flush() {
    timer = undefined;
    if (dirty.size === 0) return;
    if (flushing || isSyncing()) return schedule(BUSY_RETRY_MS);
    const remIds = [...dirty];
    dirty.clear();
    flushing = true;
    try {
      const result = await pushRems(plugin, remIds);
      if (result?.disabled) await plugin.app.toast(`Langfour: word stopped, its cards are turned off`);
      if (result?.enabled) await plugin.app.toast(`Langfour: word resumed, its cards are back on`);
    } catch (error) {
      if (error instanceof SyncBusyError) {
        remIds.forEach((id) => dirty.add(id));
        schedule(BUSY_RETRY_MS);
      }
      // Anything else (offline, not connected) waits for the next sync.
    } finally {
      flushing = false;
    }
  }

  // Fires for every edit anywhere, often thousands of times: only note the
  // id here; whether it is a Langfour word is checked once, at flush. A
  // sync's own edits are skipped, since the sync reports those Rems itself.
  plugin.event.addListener(AppEvents.GlobalRemChanged, undefined, (data?: { remId?: string }) => {
    if (!data?.remId || isSyncing()) return;
    dirty.add(data.remId);
    schedule(DEBOUNCE_MS);
  });

  plugin.event.addListener(AppEvents.QueueCompleteCard, undefined, async (data?: { cardId?: string }) => {
    if (!data?.cardId) return;
    const card = await plugin.card.findOne(data.cardId);
    if (!card) return;
    dirty.add(card.remId);
    schedule(DEBOUNCE_MS);
  });

  plugin.event.addListener(AppEvents.QueueExit, undefined, () => schedule(0));

  return () => {
    if (timer) clearTimeout(timer);
    plugin.event.removeListener(AppEvents.GlobalRemChanged, undefined);
    plugin.event.removeListener(AppEvents.QueueCompleteCard, undefined);
    plugin.event.removeListener(AppEvents.QueueExit, undefined);
  };
}
