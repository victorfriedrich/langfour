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
import { practiceVerdict, reviewAddedSince } from './practice';
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
    // Per result, until the report succeeds: the decision, or, while a card is
    // being changed, how many reviews it had just before. Kept across reloads,
    // so a result is never added twice.
    const saved = (await plugin.storage.getSynced<Record<string, Attempt>>(STORAGE_PRACTICE_DECISIONS)) ?? {};
    const save = (attempt: Attempt) => {
      saved[attempt.event_id] = attempt;
      return plugin.storage.setSynced(STORAGE_PRACTICE_DECISIONS, saved);
    };
    const decisions: PracticeDecision[] = [];
    const touched = new Set<string>();

    for (const item of await api.practice()) {
      let decision = decided(saved[item.event_id]);
      if (!decision) {
        const card = await plugin.card.findOne(item.card_id);
        const before = saved[item.event_id];
        // An earlier try stopped between changing the card and saving the decision.
        const landed = before && 'applying' in before ? reviewAddedSince(before.applying, card?.repetitionHistory ?? []) : undefined;
        if (landed !== undefined) {
          decision = { event_id: item.event_id, status: 'applied', review_at: landed };
        } else {
          const rem = card && (await plugin.rem.findOne(item.rem_id));
          const practiced = rem ? await rem.getEnablePractice() : false;
          const verdict = practiceVerdict(item, card, practiced, Date.now());
          if (verdict !== 'apply' || !card) {
            decision = { event_id: item.event_id, status: 'skipped', reason: verdict };
          } else {
            const count = card.repetitionHistory?.length ?? 0;
            await save({ event_id: item.event_id, applying: count });
            await card.updateCardRepetitionStatus(SCORES[item.outcome]);
            const history = (await plugin.card.findOne(item.card_id))?.repetitionHistory ?? [];
            decision = { event_id: item.event_id, status: 'applied', review_at: reviewAddedSince(count, history) ?? Date.now() };
          }
        }
        await save(decision);
      }
      // Also for a decision saved earlier: its review may not have reached Langfour.
      if (decision.status === 'applied') touched.add(item.rem_id);
      decisions.push(decision);
    }

    // The new reviews go to Langfour like any other answer, then the report.
    const notes = await remNotes(plugin, [...touched]);
    if (notes.length) await api.push({ notes });
    if (decisions.length) await api.reportPractice(decisions);
    await plugin.storage.setSynced(STORAGE_PRACTICE_DECISIONS, {});
  });
}

type Attempt = PracticeDecision | { event_id: number; applying: number };

function decided(attempt: Attempt | undefined): PracticeDecision | undefined {
  return attempt && 'status' in attempt ? attempt : undefined;
}
