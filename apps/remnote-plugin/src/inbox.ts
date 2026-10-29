// Between syncs: what Langfour has waiting for RemNote. Checked when a review
// session starts (so practice results are on the cards before they are shown),
// after the startup sync, and every few minutes while RemNote is open.
//
//  - Practice results from ChatGPT (apps/api/practice.py) are added to their
//    cards as reviews, under the server's sync lease so two devices never add
//    the same one. Conservative on purpose: RemNote can't tell these reviews
//    from its own, so a right answer only counts for a card that is due.
//  - New learning words start an ordinary sync, which creates their cards.
//
// RemNote has no way to be told about either (no backend API, no webhooks),
// so the plugin asks.

import { QueueInteractionScore, type RNPlugin } from '@remnote/plugin-sdk';
import { LangfourApi, type PracticeDecision } from './api';
import { apiUrl, readToken } from './connection';
import { STORAGE_PRACTICE_DECISIONS } from './constants';
import { practiceVerdict } from './practice';
import { describeSync, isSyncing, remNotes, syncNow, withSync } from './sync';

const SCORES = { again: QueueInteractionScore.AGAIN, good: QueueInteractionScore.GOOD };

let checking = false;

export async function checkInbox(plugin: RNPlugin): Promise<void> {
  if (checking || isSyncing()) return;
  const token = await readToken(plugin);
  if (!token) return;
  checking = true;
  try {
    const inbox = await new LangfourApi(await apiUrl(plugin), token, crypto.randomUUID()).inbox();
    if (inbox.practice > 0) await applyPractice(plugin);
    if (inbox.pending_words > 0) {
      const summary = await syncNow(plugin);
      if (summary.created || summary.error) await plugin.app.toast(describeSync(summary));
    }
  } catch {
    // Offline, busy, disconnected: the next check or sync picks it up.
  } finally {
    checking = false;
  }
}

async function applyPractice(plugin: RNPlugin): Promise<void> {
  await withSync(plugin, async ({ api }) => {
    // Decisions made but not yet reported, kept across reloads: a result is
    // never added twice because the report after it failed.
    const unreported = (await plugin.storage.getSynced<Record<string, PracticeDecision>>(STORAGE_PRACTICE_DECISIONS)) ?? {};
    const decisions: PracticeDecision[] = [];
    const touched = new Set<string>();

    for (const item of await api.practice()) {
      const earlier = unreported[item.event_id];
      if (earlier) {
        decisions.push(earlier);
        continue;
      }
      const card = await plugin.card.findOne(item.card_id);
      const verdict = practiceVerdict(item, card, Date.now());
      let decision: PracticeDecision;
      if (verdict !== 'apply' || !card) {
        decision = { event_id: item.event_id, status: 'skipped', reason: verdict };
      } else {
        await card.updateCardRepetitionStatus(SCORES[item.outcome]);
        const history = (await plugin.card.findOne(item.card_id))?.repetitionHistory ?? [];
        decision = { event_id: item.event_id, status: 'applied', review_at: history[history.length - 1]?.date ?? Date.now() };
        touched.add(item.rem_id);
      }
      unreported[item.event_id] = decision;
      await plugin.storage.setSynced(STORAGE_PRACTICE_DECISIONS, unreported);
      decisions.push(decision);
    }

    // The new reviews go to Langfour like any other answer, then the report.
    const notes = await remNotes(plugin, [...touched]);
    if (notes.length) await api.push({ notes });
    if (decisions.length) await api.reportPractice(decisions);
    await plugin.storage.setSynced(STORAGE_PRACTICE_DECISIONS, {});
  });
}
