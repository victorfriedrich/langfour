// One sync run: create or link Rems for Langfour's new learning words, then
// report every card and graded review back. RemNote owns the schedule; this
// only copies what RemNote decided into Langfour.

import type { Card, PluginRem as RemObject, RNPlugin } from '@remnote/plugin-sdk';
import { ApiError, LangfourApi, SyncBusyError, type CardPayload, type NotePayload, type PendingWord, type PushResult } from './api';
import { apiUrl, forgetToken, NotConnectedError, readToken } from './connection';
import {
  DAY_MS,
  LANGUAGE_NAMES,
  POWERUP,
  ROOT_DOC,
  SETTING_DIRECTION,
  SETTING_LINK_EXISTING,
  SLOT_WORD_ID,
  STORAGE_LANGUAGES,
  STORAGE_LAST_SYNC,
  STORAGE_LAYOUT_VERSION,
} from './constants';
import { buildIndex, findExisting, plainSides, type Candidate } from './match';
import { gradedReviews } from './stats';

export interface SyncSummary {
  at: number;
  lastSuccessAt: number | null;
  lastFullAt: number | null;
  created: number;
  linked: number;
  notes: number;
  reviews: number;
  removed: number;
  disabled: number; // words stopped because their cards were turned off, or
  enabled: number;  // resumed because they were turned back on
  rejected: number;
  error?: string;
  warning?: string; // the sync went through, but something beside it failed
}

export interface LinkedWord {
  rem: RemObject;
  remId: string;
  wordId: number;
  language: string;
  root: string;
  cards: Card[];
  practiced: boolean; // false once the user turns the Rem's flashcards off
}

type Direction = 'forward' | 'backward' | 'both';

// RemNote resends nothing on its own, and a review done on another device
// reaches this one only after RemNote syncs it. Re-reading a week of history
// on every run covers that lag, and a weekly full pass covers a device that
// was offline for longer. The server ignores reviews it already has.
const OVERLAP_MS = 7 * DAY_MS;
const FULL_SYNC_EVERY_MS = 7 * DAY_MS;
const PAGE = 200;
const MAX_PAGES = 25;
// Bumped when the document layout changes, to reorganise existing Rems once.
const LAYOUT_VERSION = 4;

function cardsByRem(cards: Card[]): Map<string, Card[]> {
  const byRem = new Map<string, Card[]>();
  for (const card of cards) {
    const list = byRem.get(card.remId);
    if (list) list.push(card);
    else byRem.set(card.remId, [card]);
  }
  return byRem;
}

async function taggedRems(plugin: RNPlugin): Promise<RemObject[]> {
  const powerup = await plugin.powerup.getPowerupByCode(POWERUP);
  return powerup ? powerup.taggedRem() : [];
}

/** Every Rem tagged with the Langfour powerup, with its cards. A copied Rem
 *  carries the same word id; both are returned, and the server keeps the one
 *  the word is already linked to. Languages come from the last sync. */
export async function loadLinkedWords(plugin: RNPlugin, allCards?: Card[]): Promise<LinkedWord[]> {
  const tagged = await taggedRems(plugin);
  if (tagged.length === 0) return [];
  const byRem = cardsByRem(allCards ?? (await plugin.card.getAll()));
  const languages = (await plugin.storage.getSynced<Record<string, string>>(STORAGE_LANGUAGES)) ?? {};

  const words: LinkedWord[] = [];
  for (const rem of tagged) {
    const wordId = Number(await rem.getPowerupProperty(POWERUP, SLOT_WORD_ID));
    if (!Number.isInteger(wordId) || wordId <= 0) continue;
    words.push({
      rem,
      remId: rem._id,
      wordId,
      language: languages[wordId] ?? '?',
      root: plainSides(rem.text)[0]?.trim() ?? '',
      cards: byRem.get(rem._id) ?? [],
      practiced: await rem.getEnablePractice(),
    });
  }
  return words;
}

/** Langfour / <Language> / <Month Year>, created on first use. */
class Layout {
  private docs = new Map<string, Promise<RemObject>>();

  constructor(private plugin: RNPlugin) {}

  root() {
    return this.doc(ROOT_DOC, null);
  }

  async language(code: string) {
    return this.doc(LANGUAGE_NAMES[code] ?? code, await this.root());
  }

  async month(code: string, addedAt: string) {
    const name = new Date(addedAt).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
    return this.doc(name, await this.language(code));
  }

  private doc(name: string, parent: RemObject | null) {
    const key = `${parent?._id ?? ''}/${name}`;
    let doc = this.docs.get(key);
    if (!doc) {
      doc = this.findOrCreate(name, parent);
      this.docs.set(key, doc);
    }
    return doc;
  }

  private async findOrCreate(name: string, parent: RemObject | null) {
    const existing = await this.plugin.rem.findByName([name], parent?._id ?? null);
    if (existing) return existing;
    const rem = await this.plugin.rem.createRem();
    if (!rem) throw new Error(`Could not create the "${name}" document.`);
    await rem.setText([name]);
    // createRem files the Rem inside the plugin's scope, so place it
    // explicitly: the root at the top level, the rest last under their parent.
    await rem.setParent(parent ?? null, parent ? (parent.children?.length ?? 0) : undefined);
    await rem.setIsDocument(true);
    return rem;
  }
}

/** Flashcards the user made themselves: every Rem with cards that is not a
 *  Langfour Rem, indexed by the words on its sides. */
async function existingFlashcards(plugin: RNPlugin, cards: Card[], langfourRemIds: Set<string>) {
  const byRem = cardsByRem(cards.filter((c) => !langfourRemIds.has(c.remId)));
  const rems = (await plugin.rem.findMany([...byRem.keys()])) ?? [];
  const remsById = new Map(rems.map((r) => [r._id, r]));
  const candidates: Candidate[] = rems.map((rem) => ({
    remId: rem._id,
    sides: [...plainSides(rem.text), ...plainSides(rem.backText)],
    reviews: (byRem.get(rem._id) ?? []).reduce((n, c) => n + gradedReviews(c).length, 0),
  }));
  return { index: buildIndex(candidates), remsById };
}

async function tagRem(rem: RemObject, wordId: number) {
  await rem.addPowerup(POWERUP);
  await rem.setPowerupProperty(POWERUP, SLOT_WORD_ID, [String(wordId)]);
}

async function createWordRem(plugin: RNPlugin, parent: RemObject, word: PendingWord, direction: Direction) {
  const rem = await plugin.rem.createRem();
  if (!rem) throw new Error(`Could not create a Rem for "${word.root}"`);
  await rem.setParent(parent, parent.children?.length ?? 0);
  await rem.setText([word.root]);
  await rem.setBackText([word.translation || '(no translation in Langfour)']);
  await tagRem(rem, word.word_id);
  await rem.setPracticeDirection(direction);
  return rem;
}

function cardPayload(card: Card, since: number): CardPayload {
  return {
    card_id: card._id,
    kind: typeof card.type === 'string' ? card.type : 'cloze',
    next_due_at: card.nextRepetitionTime ?? null,
    reviews: (card.repetitionHistory ?? [])
      .filter((r) => r.date >= since)
      .map((r) => ({ at: r.date, score: r.score })),
  };
}

/** Once per layout version: clear the language field earlier versions wrote
 *  on every Rem, and move Rems still directly under a language document into
 *  their month. Rems the user moved elsewhere are left where they are. */
async function migrateLayout(plugin: RNPlugin, layout: Layout, words: LinkedWord[], details: Map<number, { language: string; added_at: string }>) {
  if (((await plugin.storage.getSynced<number>(STORAGE_LAYOUT_VERSION)) ?? 1) >= LAYOUT_VERSION) return;
  // The legacy field is no longer registered, so RemNote cannot resolve it by
  // code. Find its definition under the powerup, then delete each Rem's
  // property line that points at it; the word id field is left alone.
  const powerup = await plugin.powerup.getPowerupByCode(POWERUP);
  const slot = (await powerup?.getChildrenRem())?.find((r) => plainSides(r.text)[0]?.trim() === 'Language');
  const pointsAtSlot = (rem: RemObject) =>
    !!slot && (rem.text ?? []).some((el) => typeof el === 'object' && (el as { _id?: string })._id === slot._id);
  const languageDocIds = new Set<string>();
  for (const code of new Set([...details.values()].map((d) => d.language))) {
    languageDocIds.add((await layout.language(code))._id);
  }
  const sorted = [...words].sort((a, b) =>
    (details.get(a.wordId)?.added_at ?? '').localeCompare(details.get(b.wordId)?.added_at ?? ''),
  );
  for (const word of sorted) {
    if (slot) {
      for (const child of (await word.rem.getChildrenRem()).filter(pointsAtSlot)) await child.remove();
    }
    const detail = details.get(word.wordId);
    if (detail && word.rem.parent && languageDocIds.has(word.rem.parent)) {
      const month = await layout.month(detail.language, detail.added_at);
      await word.rem.setParent(month, month.children?.length ?? 0);
    }
  }
  await plugin.storage.setSynced(STORAGE_LAYOUT_VERSION, LAYOUT_VERSION);
}

async function readSettings(plugin: RNPlugin, runId: string) {
  const token = await readToken(plugin);
  if (!token) throw new NotConnectedError();
  const direction = ((await plugin.settings.getSetting<string>(SETTING_DIRECTION)) || 'both') as Direction;
  const linkExisting = (await plugin.settings.getSetting<boolean>(SETTING_LINK_EXISTING)) ?? true;
  return { api: new LangfourApi(await apiUrl(plugin), token, runId), direction, linkExisting };
}

type Settings = Awaited<ReturnType<typeof readSettings>>;

async function run(plugin: RNPlugin, { api, direction, linkExisting }: Settings, previous: SyncSummary | undefined): Promise<SyncSummary> {
  const startedAt = Date.now();
  // Everything on the first run and once a week, an overlapping window otherwise.
  const lastSuccess = previous?.lastSuccessAt ?? 0;
  const lastFull = previous?.lastFullAt ?? 0;
  const full = !lastSuccess || startedAt - lastFull > FULL_SYNC_EVERY_MS;
  const since = full ? 0 : lastSuccess - OVERLAP_MS;
  const summary: SyncSummary = {
    at: startedAt, lastSuccessAt: startedAt, lastFullAt: full ? startedAt : lastFull,
    created: 0, linked: 0, notes: 0, reviews: 0, removed: 0, disabled: 0, enabled: 0, rejected: 0,
  };

  const layout = new Layout(plugin);
  const details = new Map((await api.linked()).words.map((w) => [w.word_id, w]));
  const languages: Record<string, string> = {};
  for (const [id, d] of details) languages[id] = d.language;

  const allCards = await plugin.card.getAll();
  const existingWords = await loadLinkedWords(plugin, allCards);
  // Tidying up existing Rems must never block syncing: on failure it is
  // retried next run, and the reason is shown on the progress page.
  await migrateLayout(plugin, layout, existingWords, details).catch((error) => {
    summary.warning = `Tidying up existing cards failed: ${error instanceof Error ? error.message : String(error)}`;
  });

  // 1. New words: link a flashcard the user already has, or create one. Each
  //    page is linked on the server before the next is requested, so
  //    `pending` shrinks, and a crash half-way loses nothing: a Rem made but
  //    not yet reported is found by its word id next time.
  const byWord = new Map(existingWords.map((w) => [w.wordId, w.rem]));
  const fresh = new Set<number>(); // created or linked this run: send all history
  let existing: Awaited<ReturnType<typeof existingFlashcards>> | undefined;
  const taken = new Set<string>();

  for (let page = 0; page < MAX_PAGES; page++) {
    const { words, remaining } = await api.pending(PAGE);
    if (words.length === 0) break;

    const notes: NotePayload[] = [];
    for (const word of words) {
      languages[word.word_id] = word.language;
      let rem = byWord.get(word.word_id);
      if (!rem && linkExisting) {
        existing ??= await existingFlashcards(plugin, allCards, new Set(existingWords.map((w) => w.remId)));
        const match = findExisting(existing.index, word.root);
        const matchRem = match && !taken.has(match.remId) ? existing.remsById.get(match.remId) : undefined;
        if (matchRem) {
          await tagRem(matchRem, word.word_id);
          taken.add(matchRem._id);
          rem = matchRem;
          summary.linked += 1;
        }
      }
      if (!rem) {
        rem = await createWordRem(plugin, await layout.month(word.language, word.added_at), word, direction);
        summary.created += 1;
      }
      byWord.set(word.word_id, rem);
      fresh.add(word.word_id);
      notes.push({ word_id: word.word_id, rem_id: rem._id, cards: [] });
    }
    const result = await api.push({ notes });
    summary.rejected += result.rejected_word_ids.length;
    if (remaining === 0) break;
  }
  await plugin.storage.setSynced(STORAGE_LANGUAGES, languages);

  // 2. Cards and reviews, re-read so new Rems' cards are included. Only notes
  //    with something new are sent; each carries its complete card list.
  const linked = await loadLinkedWords(plugin);
  const changed = linked.filter(
    (w) =>
      since === 0 ||
      fresh.has(w.wordId) ||
      // Card.lastRepetitionTime is never filled in by the SDK, so look at the
      // history itself.
      w.cards.some((c) => c.createdAt >= since || (c.repetitionHistory ?? []).some((r) => r.date >= since)),
  );
  for (let i = 0; i < changed.length; i += PAGE) {
    const notes = changed.slice(i, i + PAGE).map((w) => ({
      word_id: w.wordId,
      rem_id: w.rem._id,
      cards: w.cards.map((c) => cardPayload(c, fresh.has(w.wordId) ? 0 : since)),
      practiced: w.practiced,
    }));
    const result = await api.push({ notes });
    summary.notes += result.notes;
    summary.reviews += result.reviews;
    summary.rejected += result.rejected_word_ids.length;
  }

  // 3. Full sweep: a Rem that is gone from RemNote is marked removed, so the
  //    word is not offered again. Reversible: the Rem coming back restores it.
  //    A Rem whose flashcards are turned off disables its word in Langfour;
  //    turning them on again makes it a learning word again.
  //    It also reports the top-level Langfour document, which the web app and
  //    the extension link to for reviews. Looked up, never created here.
  const root = await plugin.rem.findByName([ROOT_DOC], null);
  const sweep = await api.push({
    present_rem_ids: linked.map((w) => w.rem._id),
    disabled_rem_ids: linked.filter((w) => !w.practiced).map((w) => w.rem._id),
    root_rem_id: root?._id,
  });
  summary.removed = sweep.removed;
  summary.disabled = sweep.disabled;
  summary.enabled = sweep.enabled;

  return summary;
}

/** Run `work` holding the server's sync lease, and translate the errors every
 *  caller treats alike. */
let running = 0;

/** True while this device runs a sync, whose own edits to Rems are not news. */
export function isSyncing(): boolean {
  return running > 0;
}

async function withSync<T>(plugin: RNPlugin, work: (settings: Settings) => Promise<T>): Promise<T> {
  let settings: Settings | undefined;
  running += 1;
  try {
    settings = await readSettings(plugin, crypto.randomUUID());
    return await work(settings);
  } catch (error) {
    // Revoked in Langfour (Disconnect, or a newer connection replaced it):
    // drop the token so the plugin asks to connect again.
    if (error instanceof ApiError && error.status === 401) {
      await forgetToken(plugin);
      throw new NotConnectedError();
    }
    throw error;
  } finally {
    running -= 1;
    await settings?.api.release().catch(() => undefined);
  }
}

/** Report some Rems right away, between syncs: their cards, the last day's
 *  reviews and whether their flashcards are on. Rems that are not Langfour
 *  words are skipped. The next sync resends anything this misses. Throws
 *  SyncBusyError while a sync holds the server's lease. */
export async function pushRems(plugin: RNPlugin, remIds: string[]): Promise<PushResult | null> {
  const since = Date.now() - DAY_MS;
  const notes: NotePayload[] = [];
  for (const rem of (await plugin.rem.findMany(remIds)) ?? []) {
    if (!(await rem.hasPowerup(POWERUP))) continue;
    const wordId = Number(await rem.getPowerupProperty(POWERUP, SLOT_WORD_ID));
    if (!Number.isInteger(wordId) || wordId <= 0) continue;
    notes.push({
      word_id: wordId,
      rem_id: rem._id,
      cards: (await rem.getCards()).map((c) => cardPayload(c, since)),
      practiced: await rem.getEnablePractice(),
    });
  }
  if (notes.length === 0) return null;
  return withSync(plugin, ({ api }) => api.push({ notes }));
}

/** Run a sync and record its outcome. Throws, without recording anything,
 *  NotConnectedError when there is no token and SyncBusyError when another run
 *  (on this device or another) holds the server's sync lease. */
export async function syncNow(plugin: RNPlugin): Promise<SyncSummary> {
  const previous = await plugin.storage.getSynced<SyncSummary>(STORAGE_LAST_SYNC);
  let summary: SyncSummary;
  try {
    summary = await withSync(plugin, (settings) => run(plugin, settings, previous));
  } catch (error) {
    if (error instanceof SyncBusyError || error instanceof NotConnectedError) throw error;
    summary = {
      at: Date.now(),
      lastSuccessAt: previous?.lastSuccessAt ?? null,
      lastFullAt: previous?.lastFullAt ?? null,
      created: 0, linked: 0, notes: 0, reviews: 0, removed: 0, disabled: 0, enabled: 0, rejected: 0,
      error: error instanceof Error ? error.message : String(error),
    };
  }
  await plugin.storage.setSynced(STORAGE_LAST_SYNC, summary);
  return summary;
}

/** For words whose Rem the plugin created but the user already had a
 *  flashcard for: point the word at the user's flashcard and delete the copy.
 *  Only copies inside the Langfour document that were never reviewed. Then
 *  send the full history of every linked flashcard outside the Langfour
 *  document, so their earlier reviews count; safe to run again. */
export async function linkExistingFlashcards(plugin: RNPlugin): Promise<number> {
  return withSync(plugin, async ({ api }) => {
    const root = await plugin.rem.findByName([ROOT_DOC], null);
    if (!root) return 0;
    const insideLangfour = new Set((await root.getDescendants()).map((r) => r._id));
    const allCards = await plugin.card.getAll();
    const words = await loadLinkedWords(plugin, allCards);
    const { index, remsById } = await existingFlashcards(plugin, allCards, new Set(words.map((w) => w.remId)));

    let count = 0;
    for (const word of words) {
      if (!insideLangfour.has(word.remId) || word.cards.some((c) => gradedReviews(c).length)) continue;
      const match = findExisting(index, word.root);
      const target = match && remsById.get(match.remId);
      if (!target) continue;
      try {
        await api.relink({ word_id: word.wordId, from_rem_id: word.remId, to_rem_id: target._id });
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) continue; // taken, or reviewed meanwhile
        throw error;
      }
      await tagRem(target, word.wordId);
      await word.rem.remove();
      count += 1;
    }

    const outside = (await loadLinkedWords(plugin)).filter((w) => !insideLangfour.has(w.remId));
    for (let i = 0; i < outside.length; i += PAGE) {
      await api.push({
        notes: outside.slice(i, i + PAGE).map((w) => ({
          word_id: w.wordId,
          rem_id: w.remId,
          cards: w.cards.map((c) => cardPayload(c, 0)),
          practiced: w.practiced,
        })),
      });
    }
    return count;
  });
}

export function describeSync(summary: SyncSummary): string {
  if (summary.error) return `Langfour sync failed: ${summary.error}`;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const parts = [];
  if (summary.created) parts.push(`${plural(summary.created, 'new card')}`);
  if (summary.linked) parts.push(`${plural(summary.linked, 'existing flashcard')} linked`);
  if (summary.reviews) parts.push(`${plural(summary.reviews, 'review')} reported`);
  if (summary.removed) parts.push(`${plural(summary.removed, 'deleted Rem')} noted`);
  if (summary.disabled) parts.push(`${plural(summary.disabled, 'word')} with cards turned off stopped`);
  if (summary.enabled) parts.push(`${plural(summary.enabled, 'word')} with cards turned back on resumed`);
  return parts.length ? `Langfour: ${parts.join(', ')}` : 'Langfour: already up to date';
}
