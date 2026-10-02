// Finding a flashcard the user already has for a Langfour word, so the plugin
// links it instead of creating a duplicate. Pure functions: tested without
// RemNote.
//
// Deliberately strict: a word matches a card only when one side of the card,
// or one of its comma/slash-separated parts, is that word once case, accents
// in composition, articles and brackets are normalised. A card whose front is
// a sentence containing the word does not match; a wrong link would attach
// someone's reviews of a different card to this word.

// Leading articles of the languages Langfour teaches, and "to" for English
// verb glosses. Removed only at the start of a part.
const ARTICLES = new Set([
  'el', 'la', 'los', 'las', 'lo', 'un', 'una', 'unos', 'unas',
  'il', 'i', 'gli', 'le', 'uno',
  'les', 'une', 'des', 'du',
  'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einen', 'einem', 'einer',
  'to',
]);

/** A normalised form for comparison, or '' when nothing is left. */
export function normalize(text: string): string {
  const words = text
    .normalize('NFC')
    .toLowerCase()
    .replace(/\(.*?\)|\[.*?\]/g, ' ') // "(m.)", "[coll.]"
    .replace(/^\s*l['’]\s*/, '') // l'acqua, l'eau
    .replace(/[^\p{L}\p{N}\s'-]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);
  while (words.length > 1 && ARTICLES.has(words[0])) words.shift();
  return words.join(' ');
}

/** Every normalised form a card side offers: the whole side and each part
 *  of a list such as "el truco, la trampa" or "coche / carro". */
export function forms(side: string): string[] {
  const parts = [side, ...side.split(/[,;/|]| [-–—] /)];
  return [...new Set(parts.map(normalize).filter(Boolean))];
}

type RichText = unknown[] | undefined;

/** Plain text of a RemNote rich text: text runs only. A card delimiter
 *  (">>" typed inline) splits the text, as front and back. */
export function plainSides(richText: RichText): string[] {
  const sides = [''];
  for (const el of richText ?? []) {
    if (typeof el === 'string') sides[sides.length - 1] += el;
    else if (el && typeof el === 'object') {
      const item = el as { i?: string; text?: string };
      if (item.i === 'm' && typeof item.text === 'string') sides[sides.length - 1] += item.text;
      else if (item.i === 's') sides.push('');
    }
  }
  return sides.filter((s) => s.trim());
}

export interface Candidate {
  remId: string;
  sides: string[];
  reviews: number;
}

/** Normalised form -> the Rem to link. When several cards match, the one
 *  with the most reviews wins: it carries the most learning. */
export function buildIndex(candidates: Candidate[]): Map<string, Candidate> {
  const index = new Map<string, Candidate>();
  for (const candidate of candidates) {
    for (const form of candidate.sides.flatMap(forms)) {
      const current = index.get(form);
      if (!current || candidate.reviews > current.reviews) index.set(form, candidate);
    }
  }
  return index;
}

export function findExisting(index: Map<string, Candidate>, root: string): Candidate | undefined {
  const key = normalize(root);
  return key ? index.get(key) : undefined;
}
