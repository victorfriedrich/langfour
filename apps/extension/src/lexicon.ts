// Classifying the words of a text against a downloaded dictionary.
//
// The reader used to send every article's tokens to classify_words
// (apps/api/sql/classify_words.sql). Each call read pages scattered over
// the dictionary tables, which the database does not keep in memory, so a
// long article took ~9 s cold, or failed on the 8 s statement timeout. The
// valid dictionary of a language is ~3 MB, so the background downloads it
// once (lexiconCache.ts, from lexicon_page in apps/api/sql/lexicon.sql) and
// this file applies classify_words' rules to it locally.
import type { ClassifiedWord, WordStatus } from './messages';

export type Lexicon = {
  /** Dictionary form → word id; roots are unique within a language. */
  roots: Map<string, number>;
  /** Word form → word id, or ids when a spelling belongs to several words ("como"). */
  forms: Map<string, number | number[]>;
};

/** Parses lexicon_page entries: "id<TAB>root<TAB>form<TAB>form..." per line. */
export function parseLexicon(pages: string[]): Lexicon {
  const roots = new Map<string, number>();
  const forms = new Map<string, number | number[]>();
  for (const page of pages) {
    for (const line of page.split('\n')) {
      const fields = line.split('\t');
      const id = Number(fields[0]);
      if (!Number.isInteger(id) || !fields[1]) continue;
      roots.set(fields[1], id);
      for (let i = 2; i < fields.length; i++) {
        const form = fields[i];
        const existing = forms.get(form);
        if (existing === undefined) forms.set(form, id);
        else if (Array.isArray(existing)) existing.push(id);
        else if (existing !== id) forms.set(form, [existing, id]);
      }
    }
  }
  return { roots, forms };
}

const STATUS_RANK: Record<WordStatus, number> = { known: 1, ignored: 2, learning: 3, new: 4 };
const ROOT = 1;
const FORM = 2;

/**
 * Same result as classify_words: for each distinct token, the word it
 * belongs to and the user's status, or no entry when it is not vocabulary.
 * A token matches as written or lowercased, as a root or a word form. When
 * it matches several words the user's best relation wins (a spelling is
 * only new if none of its words is known), then root over form, then the
 * lower id. Words missing from statuses are new.
 */
export function classifyTokens(
  tokens: Iterable<string>,
  lexicon: Lexicon,
  statuses: ReadonlyMap<number, WordStatus>,
): ClassifiedWord[] {
  const words: ClassifiedWord[] = [];
  for (const token of new Set(tokens)) {
    // classify_words' length between 1 and 64, counted in characters.
    if (!token || [...token].length > 64) continue;

    const candidates: [id: number, priority: number][] = [];
    for (const key of new Set([token, token.toLowerCase()])) {
      const root = lexicon.roots.get(key);
      if (root !== undefined) candidates.push([root, ROOT]);
      const form = lexicon.forms.get(key);
      if (Array.isArray(form)) form.forEach((id) => candidates.push([id, FORM]));
      else if (form !== undefined) candidates.push([form, FORM]);
    }

    let best: { id: number; status: WordStatus; priority: number } | null = null;
    for (const [id, priority] of candidates) {
      const status = statuses.get(id) ?? 'new';
      if (
        !best
        || STATUS_RANK[status] < STATUS_RANK[best.status]
        || (STATUS_RANK[status] === STATUS_RANK[best.status]
          && (priority < best.priority || (priority === best.priority && id < best.id)))
      ) {
        best = { id, status, priority };
      }
    }
    if (best) words.push({ token, word_id: best.id, status: best.status });
  }
  return words;
}
