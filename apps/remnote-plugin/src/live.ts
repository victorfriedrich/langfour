// Between syncs: send a word to Langfour as soon as one of its cards is
// answered, or its flashcards are turned off or on. Full syncs still run and
// cover anything missed here. A push that fails (offline, the API restarting)
// is retried with backoff, and the Rems waiting for it survive a reload.
//
// Also checks Langfour's inbox (inbox.ts) when a review session starts and
// every few minutes, so practice results and new words arrive between syncs.

import { AppEvents, type RNPlugin } from '@remnote/plugin-sdk';
import { SyncBusyError } from './api';
import { STORAGE_UNSENT_REMS } from './constants';
import { checkInbox } from './inbox';
import { isSyncing, pushRems } from './sync';

// Answers arrive one after another in a review session; one request for a
// burst of them. RemNote also reports a card's answer only after the next
// card has loaded, so a short wait is needed anyway.
const DEBOUNCE_MS = 5_000;
const BUSY_RETRY_MS = 60_000;
// After a failed push: wait this long, then longer, then stay at the last.
const FAILURE_BACKOFF_MS = [30_000, 120_000, 600_000];
const INBOX_EVERY_MS = 10 * 60_000;

export function watchForChanges(plugin: RNPlugin): () => void {
  const dirty = new Set<string>(); // Rem ids
  let timer: ReturnType<typeof setTimeout> | undefined;
  let flushing = false;
  let failures = 0;

  const schedule = (ms: number) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void flush(), ms);
  };

  const remember = () => plugin.storage.setLocal(STORAGE_UNSENT_REMS, [...dirty]).catch(() => undefined);

  async function flush() {
    timer = undefined;
    if (dirty.size === 0) return;
    if (flushing || isSyncing()) return schedule(BUSY_RETRY_MS);
    const remIds = [...dirty];
    dirty.clear();
    flushing = true;
    try {
      const result = await pushRems(plugin, remIds);
      failures = 0;
      if (result?.disabled) await plugin.app.toast(`Langfour: word stopped, its cards are turned off`);
      if (result?.enabled) await plugin.app.toast(`Langfour: word resumed, its cards are back on`);
    } catch (error) {
      remIds.forEach((id) => dirty.add(id));
      if (error instanceof SyncBusyError) {
        schedule(BUSY_RETRY_MS);
      } else {
        schedule(FAILURE_BACKOFF_MS[Math.min(failures, FAILURE_BACKOFF_MS.length - 1)]);
        failures += 1;
      }
    } finally {
      flushing = false;
      await remember();
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
    await remember();
    schedule(DEBOUNCE_MS);
  });

  plugin.event.addListener(AppEvents.QueueEnter, undefined, () => void checkInbox(plugin));
  plugin.event.addListener(AppEvents.QueueExit, undefined, () => schedule(0));
  const inboxTimer = setInterval(() => void checkInbox(plugin), INBOX_EVERY_MS);

  // Answers a previous session could not send.
  void plugin.storage.getLocal<string[]>(STORAGE_UNSENT_REMS).then((ids) => {
    (ids ?? []).forEach((id) => dirty.add(id));
    if (dirty.size) schedule(DEBOUNCE_MS);
  });

  return () => {
    if (timer) clearTimeout(timer);
    clearInterval(inboxTimer);
    plugin.event.removeListener(AppEvents.GlobalRemChanged, undefined);
    plugin.event.removeListener(AppEvents.QueueCompleteCard, undefined);
    plugin.event.removeListener(AppEvents.QueueEnter, undefined);
    plugin.event.removeListener(AppEvents.QueueExit, undefined);
  };
}
